"""
Offline guard: the single-row bq_writes statements bind every caller value.

Why it exists: these functions used to paste values into the SQL text, with
`.replace("'", "\\'")` on a few of them. That escapes a quote but not a
backslash, so a value ending in `\\` escapes the closing quote and breaks or
extends the statement; and some values (ids, status, assignee, domain,
submitted_by, feedback_type) were pasted with no escaping at all.

What each case checks, per function, with a hostile value `<label>-O'Brien\\`:
  1. the SQL text carries none of the caller's values (nor their labels);
  2. each value reaches BigQuery as a named STRING query parameter, and the
     SQL refers to every parameter as @name;
  3. the value in the parameter equals what the caller passed, byte for byte
     (so O'Brien\\ round-trips; nothing was escaped or dropped).

Nothing here touches BigQuery: a fake client remembers what it was handed.
Run: PATH=/opt/anaconda3/bin:$PATH python -m pytest tests/test_bq_writes_params.py -q
(never bare `pytest tests/`, which runs smoke_test.py against live BigQuery).
"""

import re

import pytest

import bq_writes


HOSTILE_TAIL = "-O'Brien\\"


def _hostile(label: str) -> str:
    """In: a short label. Out: a value like `zq_cid-O'Brien\\` that is unique per
    argument, holds a quote and ends in a backslash. Why: the label lets a test
    find the value in the SQL text; the tail is the input that broke the old code."""
    return f"zq_{label}{HOSTILE_TAIL}"


class _FakeJob:
    """Stands in for a BigQuery job: no rows."""
    num_dml_affected_rows = 0

    def result(self):
        return []


class _FakeClient:
    """Remembers the last SQL text and job_config passed to query(); runs nothing."""

    def __init__(self):
        self.sql = None
        self.job_config = None

    def query(self, sql, job_config=None):
        self.sql = sql
        self.job_config = job_config
        return _FakeJob()


def _params(job_config) -> dict:
    """In: the job_config handed to client.query (or None).
    Out: {parameter name: (type, value)}. Why: checked on what the client was
    handed, not on what the function says it did."""
    return {p.name: (p.type_, p.value)
            for p in (getattr(job_config, "query_parameters", None) or [])}


@pytest.fixture
def fake(monkeypatch):
    """In: nothing. Out: the fake client now installed in bq_writes. Why: lets a
    test call a writer and read the statement it sent. The assignment refresh
    (an HTTP call after update_ticket_meta) is switched off."""
    client = _FakeClient()
    monkeypatch.setattr(bq_writes, "client", client)
    monkeypatch.setattr(bq_writes, "trigger_assignment_refresh", lambda: None)
    return client


def _assert_all_bound(fake, values: dict, labels=()):
    """In: the fake after a call, {argument name: hostile value} the caller
    passed, and the labels that must not leak into SQL.
    Out: nothing; raises if a value is in the SQL text, is not a STRING
    parameter, or if some parameter is never referenced as @name.
    Why: the three promises in the module docstring, in one place."""
    sql, params = fake.sql, _params(fake.job_config)
    for arg, value in values.items():
        assert value not in sql, f"{arg}: value pasted into the SQL text"
        assert value.split("-")[0] not in sql, f"{arg}: label leaked into the SQL text"
        matches = [name for name, (type_, v) in params.items() if v == value]
        assert matches, f"{arg}: no query parameter carries the value unchanged"
        for name in matches:
            assert params[name][0] == "STRING", f"{arg}: parameter {name} is not STRING"
    for name in params:
        assert re.search(rf"@{name}\b", sql), f"parameter {name} is never used in the SQL"


def _assert_aliased(sql: str, columns):
    """In: the SQL a MERGE sent and the parameter/column names it must carry.
    Out: nothing; raises unless each `@name` is aliased `AS name` (its own column).
    Why: _assert_all_bound only proves a parameter is used somewhere; swapping
    `@status AS assigned_to` with `@assigned_to AS status` would pass it and
    write every status into the assignee column."""
    for name in columns:
        assert re.search(rf"@{name}\s+AS\s+{name}\b", sql), f"@{name} is not aliased AS {name}"


def _split_top_level(text: str):
    """In: SQL text like `a, f(b, c), d`. Out: ['a', 'f(b, c)', 'd'] (split on commas
    outside brackets, trimmed). Why: a VALUES list can hold function calls."""
    parts, depth, current = [], 0, ""
    for char in text:
        depth += char == "("
        depth -= char == ")"
        if char == "," and depth == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += char
    parts.append(current.strip())
    return parts


def _assert_columns_match(fake, renames=None, literal_columns=()):
    """In: the fake after a call (its SQL and parameters); `renames` {column:
    parameter name} for the few places the two differ; `literal_columns` the
    columns the code itself fills with a constant or its own timestamp (the
    only holes allowed).
    Out: nothing; raises unless
      - every `column = @param` (also `column = TIMESTAMP(@param)`) in the
        statement has param == column,
      - in an INSERT, the Nth column of the list takes the Nth value, i.e.
        `@<that column>`, unless it is a literal column, and
      - EVERY parameter that was sent was matched to a column this way.
    Why: _assert_all_bound cannot see a swap such as VALUES (@email, @full_name)
    for (full_name, email), which would write every name into the email column.
    The last rule is what stops this guard passing blind: if the SQL is reshaped
    (a trailing `;`, a CAST around a parameter) so the patterns below read
    nothing, the parameters stay unmatched and the test goes red instead."""
    sql = fake.sql
    renames = renames or {}
    matched = set()
    for column, param in re.findall(r"(\w+)\s*=\s*(?:TIMESTAMP\()?@(\w+)", sql):
        assert param == renames.get(column, column), f"{column} = @{param}"
        matched.add(param)
    insert = re.search(r"INSERT INTO\s+\S+\s*\(([^)]*)\)\s*VALUES\s*\((.*)\)\s*;?\s*$", sql, re.S)
    if insert:
        columns = [c.strip() for c in insert.group(1).split(",")]
        values = _split_top_level(insert.group(2))
        assert len(columns) == len(values), "column list and VALUES differ in length"
        for column, value in zip(columns, values):
            if column in literal_columns:
                assert "@" not in value, f"{column} should be a code-made literal"
            else:
                assert value == f"@{renames.get(column, column)}", f"{column} takes {value}"
                matched.add(renames.get(column, column))
    sent = set(_params(fake.job_config))
    assert sent, "no parameters were sent, nothing to check"
    assert sent <= matched, f"parameters never matched to a column: {sorted(sent - matched)}"


# --- update_ticket_meta ------------------------------------------------------

def test_update_ticket_meta_binds_every_value(fake):
    """Every string argument becomes a parameter; closed_by is NULL (SQL) when not closing."""
    values = {"content_id": _hostile("cid"), "status": _hostile("status"),
              "assigned_to": _hostile("assignee"), "domain": _hostile("domain"),
              "feedback_reason": _hostile("reason")}
    bq_writes.update_ticket_meta(**values)
    _assert_all_bound(fake, values)
    _assert_aliased(fake.sql, values)
    assert "CAST(NULL AS TIMESTAMP)" in fake.sql and "CAST(NULL AS STRING)" in fake.sql


def test_update_ticket_meta_closing_binds_closed_by(fake):
    """status 'closed' with a closer: closed_by is a parameter, closed_at stays a SQL timestamp."""
    values = {"content_id": _hostile("cid"), "assigned_to": _hostile("assignee"),
              "domain": _hostile("domain"), "feedback_reason": _hostile("reason"),
              "closed_by": _hostile("closer")}
    bq_writes.update_ticket_meta(status="closed", **values)
    _assert_all_bound(fake, values)
    _assert_aliased(fake.sql, values)
    assert "CAST(NULL AS TIMESTAMP)" not in fake.sql
    assert ("STRING", "closed") in _params(fake.job_config).values()


def test_update_ticket_meta_empty_optionals_are_still_bound(fake):
    """domain/reason left out: the SQL still has no pasted values and sends empty strings."""
    bq_writes.update_ticket_meta(_hostile("cid"), "open", "")
    params = _params(fake.job_config)
    assert _hostile("cid") not in fake.sql
    assert ("STRING", "") in params.values()
    assert all(t == "STRING" for t, _ in params.values())


# --- set_ticket_lane ---------------------------------------------------------

def test_set_ticket_lane_binds_every_value(fake):
    """content_id, lane and the reason are parameters."""
    values = {"content_id": _hostile("cid"), "lane": _hostile("lane"),
              "feedback_reason": _hostile("reason")}
    bq_writes.set_ticket_lane(**values)
    _assert_all_bound(fake, values)
    _assert_aliased(fake.sql, values)


def test_set_ticket_lane_without_reason_keeps_typed_null_in_sql(fake):
    """No reason: no reason parameter at all; the typed NULL stays SQL."""
    values = {"content_id": _hostile("cid"), "lane": _hostile("lane")}
    bq_writes.set_ticket_lane(**values)
    _assert_all_bound(fake, values)
    assert "CAST(NULL AS STRING)" in fake.sql
    assert len(_params(fake.job_config)) == 2


# --- set_ticket_assignee -----------------------------------------------------

def test_set_ticket_assignee_binds_every_value(fake):
    """In: a hostile content_id and coach name (quote, trailing backslash).
    Out: nothing; raises if either value is in the SQL text instead of a
    STRING parameter. Why: a coach called O'Brien must not end the SQL string."""
    values = {"content_id": _hostile("cid"), "assigned_to": _hostile("assignee")}
    bq_writes.set_ticket_assignee(**values)
    _assert_all_bound(fake, values)
    _assert_aliased(fake.sql, values)


# --- coaches -----------------------------------------------------------------

def test_add_grant_coach_binds_every_value(fake):
    """name, email, added_by are STRING parameters; member_id is an INT64 parameter."""
    values = {"full_name": _hostile("name"), "email": _hostile("email"),
              "added_by": _hostile("adder")}
    bq_writes.add_grant_coach(member_id=4242, **values)
    _assert_all_bound(fake, values)
    _assert_columns_match(fake, literal_columns={"added_at"})
    assert ("INT64", 4242) in _params(fake.job_config).values()
    assert "4242" not in fake.sql


def test_link_coach_login_email_binds_every_value(fake):
    """login_email is a STRING parameter; member_id is an INT64 parameter."""
    values = {"login_email": _hostile("login")}
    bq_writes.link_coach_login_email(member_id=4242, **values)
    _assert_all_bound(fake, values)
    _assert_columns_match(fake)
    assert ("INT64", 4242) in _params(fake.job_config).values()
    assert "4242" not in fake.sql


# --- follow-ups --------------------------------------------------------------

def test_update_followup_status_binds_every_value(fake):
    """id, status, both timestamps and the reason are STRING parameters."""
    values = {"followup_id": _hostile("fid"), "status": _hostile("status"),
              "sent_at": _hostile("sent"), "skipped_at": _hostile("skipped"),
              "skipped_reason": _hostile("why")}
    bq_writes.update_followup_status(**values)
    _assert_all_bound(fake, values)
    _assert_columns_match(fake, renames={"id": "followup_id"})


def test_update_followup_status_only_sets_what_it_was_given(fake):
    """Just id and status: no timestamp or reason column is touched."""
    values = {"followup_id": _hostile("fid"), "status": _hostile("status")}
    bq_writes.update_followup_status(**values)
    _assert_all_bound(fake, values)
    assert "sent_at" not in fake.sql and "skipped" not in fake.sql
    assert len(_params(fake.job_config)) == 2


# --- team feedback -----------------------------------------------------------

def test_submit_team_feedback_binds_every_value(fake):
    """submitter, type, title and body are parameters; the new id is one too."""
    values = {"submitted_by": _hostile("by"), "feedback_type": _hostile("type"),
              "title": _hostile("title"), "body": _hostile("body")}
    bq_writes.submit_team_feedback(**values)
    _assert_all_bound(fake, values)
    _assert_columns_match(fake, literal_columns={"status", "created_at"})


def test_reply_team_feedback_binds_every_value(fake):
    """id, reply text, replier and new status are parameters."""
    values = {"feedback_id": _hostile("fbid"), "reply_text": _hostile("reply"),
              "replied_by": _hostile("replier"), "new_status": _hostile("newstatus")}
    bq_writes.reply_team_feedback(**values)
    _assert_all_bound(fake, values)
    _assert_columns_match(fake)


# --- NaN guard ---------------------------------------------------------------
# merge_into_tickets fills the columns the questions frame lacks with float NaN.
# bool(nan) is True, so `v or ""` passes it on, and a float bound as a STRING
# parameter is not legal JSON (revision 00081) or is written as 'nan' (00080).

_NAN = float("nan")

# writer -> (arguments that are fine, the string arguments a caller may hand NaN)
_STRING_WRITERS = {
    "update_ticket_meta": (
        dict(content_id="c1", status="closed", assigned_to="a@x", domain="d",
             feedback_reason="r", closed_by="b@x"),
        ["content_id", "status", "assigned_to", "domain", "feedback_reason", "closed_by"]),
    "set_ticket_lane": (
        dict(content_id="c1", lane="question", feedback_reason="r"),
        ["content_id", "lane", "feedback_reason"]),
    "add_grant_coach": (
        dict(member_id=1, full_name="n", email="e", added_by="b"),
        ["full_name", "email", "added_by"]),
    "link_coach_login_email": (
        dict(member_id=1, login_email="e"), ["login_email"]),
    "update_followup_status": (
        dict(followup_id="f1", status="skipped", skipped_reason="why"),
        ["followup_id", "status", "skipped_reason"]),
    "submit_team_feedback": (
        dict(submitted_by="b", feedback_type="t", title="ti", body="bo"),
        ["submitted_by", "feedback_type", "title", "body"]),
    "reply_team_feedback": (
        dict(feedback_id="f1", reply_text="r", replied_by="b", new_status="s"),
        ["feedback_id", "reply_text", "replied_by", "new_status"]),
    "save_standard_reply": (
        dict(reply_id="r1", title="t", body="b", saved_by="s"),
        ["reply_id", "title", "body", "saved_by"]),
    "archive_standard_reply": (dict(reply_id="r1"), ["reply_id"]),
}

_NAN_CASES = [(writer, arg) for writer, (_, args) in _STRING_WRITERS.items() for arg in args]


@pytest.mark.parametrize("writer,arg", _NAN_CASES)
def test_no_writer_binds_a_float(fake, writer, arg):
    """A float NaN in any one string argument never reaches BigQuery as a bound
    value; it arrives as None (SQL NULL), so COALESCE falls through to the
    derived value instead of 'nan' shadowing it."""
    kwargs = dict(_STRING_WRITERS[writer][0])
    kwargs[arg] = _NAN
    getattr(bq_writes, writer)(**kwargs)
    for name, (_, value) in _params(fake.job_config).items():
        assert not isinstance(value, float), f"{writer}({arg}=NaN) bound {name}={value!r}"


def test_nan_case_table_covers_every_binding_writer():
    """Every public writer that builds ScalarQueryParameter is in the table
    above, so a new writer cannot skip the NaN test."""
    import inspect
    binding = {name for name, fn in inspect.getmembers(bq_writes, inspect.isfunction)
               if fn.__module__ == "bq_writes" and "ScalarQueryParameter" in inspect.getsource(fn)}
    binding -= {"execute_bulk_close"}  # owned by bulk_close.md
    assert binding <= set(_STRING_WRITERS), sorted(binding - set(_STRING_WRITERS))


@pytest.mark.parametrize("arg", ["sent_at", "skipped_at"])
def test_followup_timestamp_nan_is_not_turned_into_text(fake, arg):
    """str(nan) is the text 'nan', which TIMESTAMP() rejects; NaN must go as NULL."""
    bq_writes.update_followup_status("f1", "sent", **{arg: _NAN})
    assert ("STRING", None) in _params(fake.job_config).values()
    assert "nan" not in [v for _, v in _params(fake.job_config).values()]
