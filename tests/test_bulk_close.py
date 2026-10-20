"""
Offline proof for the bulk close sweep — docs/specs/modules/bulk_close.md,
`### execute_bulk_close(...)`, rules R2, R3, R4, R9, R11 (one lane per sweep) and R12 (the panel exists once).

Input: nothing from BigQuery. The `client` of bq_reads and bq_writes is swapped
for a fake that only remembers the SQL text it was asked to run. Output: that
text. Every test reads the SQL a coach's click would send, never a live table.

Run with: PATH=/opt/anaconda3/bin:$PATH python -m pytest tests/test_bulk_close.py -q
Never `pytest tests/` — that also collects smoke_test.py, which writes to the
live ticket_metadata table.
"""

import ast
import json
import pathlib
import re
from collections import Counter

import pytest

import bq_base
import bq_reads
import bq_writes
import config


class _FakeJob:
    """Stands in for a BigQuery job: no rows, no affected rows."""
    num_dml_affected_rows = 0

    def result(self):
        return [{"total": 0, "skipped_followup": 0}]


class _FakeClient:
    """Remembers the last SQL text passed to query(), runs nothing."""

    def __init__(self):
        self.sql = None

    def query(self, sql):
        self.sql = sql
        return _FakeJob()


@pytest.fixture
def sent_sql(monkeypatch):
    """
    In: nothing. Out: a function (execute|preview, filters) -> the SQL text
    that function sent. Why: lets a test see the statement without BigQuery.
    """
    def run(which, status="answered", assigned="", before="", lane=config.LANE_QUESTION,
            table_cols=frozenset({"lane"})):
        fake = _FakeClient()
        monkeypatch.setattr(bq_reads, "client", fake)
        monkeypatch.setattr(bq_writes, "client", fake)
        # Prime the schema cache so the callers' column probe needs no client.
        monkeypatch.setitem(bq_base._TICKETS_COLS_CACHE, "cols", set(table_cols))
        monkeypatch.setitem(bq_base._TICKETS_COLS_CACHE, "expires_at", float("inf"))
        if which == "execute":
            bq_writes.execute_bulk_close(status, assigned, before, "coach@x.org", lane=lane)
        else:
            bq_reads.preview_bulk_close(status, assigned, before, lane=lane)
        return fake.sql
    return run


# The lane every older test sweeps: Tickets. gt_cols matches sent_sql's default.
_Q = {"lane": config.LANE_QUESTION, "gt_cols": {"lane"}}


def _raw_where(sql: str) -> str:
    """The helper's WHERE line, without the keyword: its AND-ed conditions."""
    return re.search(r"WHERE (t\.effective_status NOT IN.*)", sql).group(1)


def _where(sql: str) -> str:
    """
    _raw_where without the lane condition, so R2 and R4 keep counting only the
    conditions they are about; R11's tests read _raw_where to see the lane.
    """
    return re.sub(r" AND t\.lane = '\w+'$", "", _raw_where(sql))


# R2 -------------------------------------------------------------------------

def test_r2_empty_filters_add_no_constraint():
    """All three "" -> the widest sweep: only the not-closed exclusion remains."""
    where = _where(bq_reads.bulk_close_rows_sql("", "", "", **_Q))
    assert "AND" not in where
    assert "effective_status =" not in where
    assert "effective_assigned_to" not in where
    assert "DATE(" not in where


def test_r2_each_filter_adds_only_its_own_condition():
    """One filter set -> exactly one extra condition, and not the others."""
    status = _where(bq_reads.bulk_close_rows_sql("answered", "", "", **_Q))
    coach = _where(bq_reads.bulk_close_rows_sql("", "coach@x.org", "", **_Q))
    date = _where(bq_reads.bulk_close_rows_sql("", "", "2026-01-01", **_Q))
    assert status.count(" AND ") == 1 and "effective_status = 'answered'" in status
    assert coach.count(" AND ") == 1 and "effective_assigned_to = 'coach@x.org'" in coach
    assert date.count(" AND ") == 1 and "DATE(t.created_at) < '2026-01-01'" in date


def test_r2_filters_are_anded_together():
    """All three set -> three extra conditions joined by AND, never OR."""
    where = _where(bq_reads.bulk_close_rows_sql("answered", "coach@x.org", "2026-01-01", **_Q))
    assert where.count(" AND ") == 3
    assert " OR " not in where


# R3 -------------------------------------------------------------------------
# R3 is guarded in TWO places on purpose (Martin, 2026-10-19): execute excludes
# pending follow-ups with NOT IN, preview counts them with a LEFT JOIN, so the
# predicate stayed per caller and each caller's string is asserted here.

def test_r3_execute_never_selects_a_ticket_with_a_pending_followup(sent_sql):
    """Execute's MERGE source must exclude ids with a pending follow-up row."""
    sql = " ".join(sent_sql("execute").split())
    assert ("NOT IN ( SELECT DISTINCT ticket_id FROM "
            f"`{bq_writes.config.FOLLOWUP_QUEUE_TABLE}` WHERE status = 'pending' )") in sql


def test_r3_preview_counts_pending_followups_as_skipped(sent_sql):
    """Preview must join the pending set and report it as skipped_followup."""
    sql = " ".join(sent_sql("preview").split())
    assert "COUNTIF(fq.ticket_id IS NOT NULL) AS skipped_followup" in sql
    assert ("SELECT DISTINCT ticket_id FROM "
            f"`{bq_reads.config.FOLLOWUP_QUEUE_TABLE}` WHERE status = 'pending'") in sql


# R4 -------------------------------------------------------------------------

def test_r4_closed_cancelled_and_archived_are_all_excluded():
    """The exclusion list holds exactly these three statuses, in every sweep."""
    for filters in (("", "", ""), ("answered", "coach@x.org", "2026-01-01")):
        where = _where(bq_reads.bulk_close_rows_sql(*filters, **_Q))
        listed = re.search(r"NOT IN \(([^)]*)\)", where).group(1)
        assert sorted(re.findall(r"'(\w+)'", listed)) == ["archived", "cancelled", "closed"]


def test_r4_archived_is_excluded_even_when_the_status_filter_asks_for_it():
    """status_filter="archived" is ANDed with the exclusion, so it matches nothing."""
    where = _where(bq_reads.bulk_close_rows_sql("archived", "", "", **_Q))
    assert "'archived'" in where.split(" AND ")[0]
    assert "effective_status = 'archived'" in where


# R9 -------------------------------------------------------------------------

@pytest.mark.parametrize("filters", [
    ("answered", "", ""),
    ("", "", ""),
    ("", "coach@x.org", "2026-01-01"),
])
def test_r9_preview_and_execute_both_embed_the_helpers_selection(sent_sql, filters):
    """
    The helper's exact text appears in what BOTH callers send. A caller that
    inlines its own copy of the selection makes this red.
    """
    selection = bq_reads.bulk_close_rows_sql(*filters, **_Q)
    assert selection in sent_sql("execute", *filters)
    assert selection in sent_sql("preview", *filters)


# Slice 1 fixture -------------------------------------------------------------
# tests/fixtures/bulk_close_sql_before.json is the SQL both functions built on
# origin/main before the extraction, for four filter sets. These tests are the
# only readers of it. They compare LINES (a multiset: each distinct line with
# how often it occurs), not the whole string, so whitespace and the nesting do
# not matter but any other added or removed line does: an extra WHERE clause
# in one caller, a changed pending-follow-up join, a changed MERGE value.

_FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "bulk_close_sql_before.json"

# The ONLY lines allowed to differ from the fixture (after 'archived' is
# stripped from the exclusion list, which R4 tests separately). Each is
# either nesting (the helper wrapped in a subselect or CTE) or the two extra
# helper columns preview now carries. The lane (R11, 2026-10-20) adds, for BOTH
# callers: the `AS lane` column of base (written out here, not read from
# bq_reads, so the test cannot agree with itself), the trailing comma that
# column puts on the line before it, and a WHERE line that is the fixture's own
# WHERE line plus ` AND t.lane = 'question'` — that pair is built per case in
# _allowed_for() from the fixture, since the WHERE line differs per filter set.
_LANE_COLUMN = ("CASE WHEN tm.lane IS NOT NULL AND tm.lane != '' "
                "THEN tm.lane ELSE gt.lane END AS lane")
_EFFECTIVE_ASSIGNED = "COALESCE(tm.assigned_to, gt.assigned_to) AS effective_assigned_to"
_LANE_ADDED = [_LANE_COLUMN, _EFFECTIVE_ASSIGNED + ","]
_LANE_REMOVED = [_EFFECTIVE_ASSIGNED]
_ALLOWED_EXECUTE = {
    "added": [") r", "FROM (", "SELECT r.content_id, r.assigned_to, r.domain",
              "WHERE r.content_id NOT IN ("] + _LANE_ADDED,
    "removed": ["AND t.content_id NOT IN ("] + _LANE_REMOVED,
}
_ALLOWED_PREVIEW = {
    "added": [")", "COALESCE(tm.assigned_to, gt.assigned_to) AS assigned_to,",
              "COALESCE(tm.domain, gt.domain)           AS domain,",
              "SELECT t.content_id, t.assigned_to, t.domain", "WITH filtered AS ("]
             + _LANE_ADDED,
    "removed": ["),", "SELECT t.content_id", "filtered AS ("] + _LANE_REMOVED,
}


def _allowed_for(case: dict, which: str, allowed: dict) -> tuple:
    """
    In: one fixture case, the caller name, that caller's pinned lists.
    Out: (added, removed) with this case's WHERE pair included: the fixture's
    own WHERE line is removed and the same line plus the Tickets-lane
    predicate is added. Why: the WHERE line is the one line that differs per
    filter set, and reading it from the fixture keeps the expectation
    independent of the code under test.
    """
    old_where = [line for line in _lines(case[which]) if line.startswith("WHERE t.")]
    assert len(old_where) == 1, "the fixture must hold exactly one helper WHERE line"
    added = allowed["added"] + [old_where[0] + " AND t.lane = 'question'"]
    removed = allowed["removed"] + old_where
    return sorted(added), sorted(removed)


def _lines(sql: str) -> Counter:
    """
    In: SQL text. Out: each stripped non-blank line with its count, with the
    clock value and the 'archived' addition normalised away. Why: what is left
    is exactly what must not change.
    """
    sql = sql.replace(", 'archived'", "")
    return Counter(re.sub(r"TIMESTAMP '[^']*'", "TIMESTAMP 'T'", line.strip())
                   for line in sql.splitlines() if line.strip())


def _fixture_cases():
    return json.loads(_FIXTURE.read_text())


@pytest.mark.parametrize("case", _fixture_cases(), ids=lambda c: "|".join(c["filters"][:3]))
@pytest.mark.parametrize("which,allowed", [("execute", _ALLOWED_EXECUTE),
                                          ("preview", _ALLOWED_PREVIEW)])
def test_r9_sql_differs_from_the_before_fixture_only_where_allowed(
        sent_sql, case, which, allowed):
    """
    Same filters as the fixture -> the same lines, except the pinned nesting
    lines. A condition added or dropped in either caller makes this red, which
    is what the substring check in test_r9_preview_and_execute_both_embed_...
    cannot see.
    """
    status, assigned, before, _closed_by = case["filters"]
    old = _lines(case[which])
    new = _lines(sent_sql(which, status, assigned, before))
    added, removed = _allowed_for(case, which, allowed)
    assert sorted((new - old).elements()) == added
    assert sorted((old - new).elements()) == removed


# R11 ------------------------------------------------------------------------
# One lane per sweep. The Tickets tab (config.LANE_QUESTION) must never close a
# Conversations (config.LANE_GENERAL) row and the reverse. Both branches of the
# migration guard are covered: grant_tickets has a `lane` column, or it does
# not yet (the expression then reads the 'question' literal).

_LANES = [config.LANE_QUESTION, config.LANE_GENERAL]
_OTHER = {config.LANE_QUESTION: config.LANE_GENERAL,
          config.LANE_GENERAL: config.LANE_QUESTION}
_GUARD_BRANCHES = [pytest.param({"lane", "content_id"}, id="gt-has-lane"),
                   pytest.param({"content_id"}, id="gt-lacks-lane")]


def _lane_predicate(lane: str) -> str:
    """The one WHERE condition that confines a sweep to `lane`."""
    return f"t.lane = '{lane}'"


@pytest.mark.parametrize("gt_cols", _GUARD_BRANCHES)
@pytest.mark.parametrize("lane", _LANES)
def test_r11_helper_confines_the_selection_to_its_lane(lane, gt_cols):
    """
    The helper's WHERE carries this lane's predicate and not the other lane's,
    and its base CTE computes lane with the live-lane expression for this
    gt_cols (so a coach's tm.lane override counts, R11).
    """
    sql = bq_reads.bulk_close_rows_sql("", "", "", lane=lane, gt_cols=gt_cols)
    assert _lane_predicate(lane) in _raw_where(sql)
    assert _lane_predicate(_OTHER[lane]) not in sql
    assert f"{bq_reads._live_lane_expr(gt_cols)} AS lane" in " ".join(sql.split())


@pytest.mark.parametrize("lane", _LANES)
def test_r11_helper_lane_condition_is_anded_with_the_filters(lane):
    """Lane is one more AND-ed condition: three filters + lane = four ANDs."""
    where = _raw_where(bq_reads.bulk_close_rows_sql(
        "answered", "coach@x.org", "2026-01-01", lane=lane, gt_cols={"lane"}))
    assert where.count(" AND ") == 4 and " OR " not in where


def test_r11_helper_without_a_lane_raises():
    """No default, no "both lanes": a call that names no lane is a TypeError."""
    with pytest.raises(TypeError):
        bq_reads.bulk_close_rows_sql("", "", "", gt_cols={"lane"})


def test_r11_helper_does_not_probe_the_table_schema(monkeypatch):
    """The helper is pure: it must not call _tickets_cols (a BigQuery call)."""
    def boom():
        raise AssertionError("bulk_close_rows_sql probed the schema")
    monkeypatch.setattr(bq_reads, "_tickets_cols", boom)
    bq_reads.bulk_close_rows_sql("", "", "", lane=config.LANE_QUESTION, gt_cols=set())


@pytest.mark.parametrize("which", ["execute", "preview"])
@pytest.mark.parametrize("table_cols", _GUARD_BRANCHES)
@pytest.mark.parametrize("lane", _LANES)
def test_r11_both_callers_send_one_lane_only(sent_sql, which, lane, table_cols):
    """
    Preview and execute each send this lane's predicate, built from the live
    expression for the table's real columns, and never the other lane's. A
    `general` row survives a `question` sweep and the reverse.
    """
    sql = sent_sql(which, lane=lane, table_cols=table_cols)
    assert _lane_predicate(lane) in sql
    assert _lane_predicate(_OTHER[lane]) not in sql
    assert bq_reads._live_lane_expr(table_cols) in " ".join(sql.split())


@pytest.mark.parametrize("which", ["execute", "preview"])
def test_r11_a_caller_without_a_lane_raises(monkeypatch, which):
    """Neither caller may default to a lane or to both: no lane is a TypeError."""
    fake = _FakeClient()
    monkeypatch.setattr(bq_reads, "client", fake)
    monkeypatch.setattr(bq_writes, "client", fake)
    call = (bq_writes.execute_bulk_close if which == "execute"
            else bq_reads.preview_bulk_close)
    with pytest.raises(TypeError):
        call("answered", "", "")
    assert fake.sql is None  # nothing was sent


@pytest.mark.parametrize("lane", _LANES)
def test_r11_preview_and_execute_embed_the_lane_helpers_selection(sent_sql, lane):
    """R9 with lane: the helper's text for this lane sits inside BOTH callers."""
    selection = bq_reads.bulk_close_rows_sql(
        "answered", "", "", lane=lane, gt_cols={"lane"})
    assert selection in sent_sql("execute", lane=lane)
    assert selection in sent_sql("preview", lane=lane)


def test_r11_execute_given_previews_gt_cols_builds_the_same_lane_expression(
        sent_sql, monkeypatch):
    """
    Preview runs while grant_tickets has no `lane` column; the Dataform
    migration then adds it; the coach presses confirm. Execute is handed the
    gt_cols preview returned, so its lane expression is byte-identical to
    preview's (ELSE 'question'), not the new table's (ELSE gt.lane) — otherwise
    it would close more rows than the number the coach agreed to (R9).
    """
    fake = _FakeClient()
    monkeypatch.setattr(bq_reads, "client", fake)
    monkeypatch.setattr(bq_writes, "client", fake)
    monkeypatch.setitem(bq_base._TICKETS_COLS_CACHE, "cols", {"content_id"})
    monkeypatch.setitem(bq_base._TICKETS_COLS_CACHE, "expires_at", float("inf"))
    result = bq_reads.preview_bulk_close(lane=config.LANE_GENERAL)
    preview_sql = fake.sql
    # The migration lands: the live table now has `lane`.
    monkeypatch.setitem(bq_base._TICKETS_COLS_CACHE, "cols", {"content_id", "lane"})
    bq_writes.execute_bulk_close(lane=config.LANE_GENERAL, closed_by="c@x.org",
                                 gt_cols=result["gt_cols"])
    execute_sql = fake.sql
    expr = bq_reads._live_lane_expr({"content_id"})
    assert expr in " ".join(preview_sql.split())
    assert expr in " ".join(execute_sql.split())
    assert "gt.lane" not in execute_sql


def test_r11_preview_returns_the_gt_cols_it_used(sent_sql, monkeypatch):
    """preview's result carries the sorted column list, for the panel to keep."""
    monkeypatch.setattr(bq_reads, "client", _FakeClient())
    monkeypatch.setitem(bq_base._TICKETS_COLS_CACHE, "cols", {"b", "a"})
    monkeypatch.setitem(bq_base._TICKETS_COLS_CACHE, "expires_at", float("inf"))
    result = bq_reads.preview_bulk_close(lane=config.LANE_QUESTION)
    assert result["gt_cols"] == ["a", "b"]


# R12 ------------------------------------------------------------------------
# The panel lives in app.py, which cannot be imported (it runs the login gate)
# and which AppTest cannot get past. So these tests read app.py as SOURCE: they
# parse it with ast, and run only the one pure function that builds the keys.

_APP_TREE = ast.parse((pathlib.Path(__file__).parent.parent / "app.py").read_text())


def _app_function(name: str) -> ast.FunctionDef:
    """In: a top-level function name. Out: its ast node in app.py (must exist once)."""
    found = [n for n in _APP_TREE.body if isinstance(n, ast.FunctionDef) and n.name == name]
    assert len(found) == 1, f"app.py must define {name} exactly once"
    return found[0]


def _bulk_close_keys(lane: str) -> dict:
    """Runs app.py's own bulk_close_keys, alone, with no Streamlit around it."""
    namespace: dict = {}
    exec(compile(ast.Module([_app_function("bulk_close_keys")], []), "app.py", "exec"), namespace)
    return namespace["bulk_close_keys"](lane)


def test_r12_the_two_lanes_use_disjoint_widget_and_state_keys():
    """
    Both tabs render on one Streamlit run: a key shared by the two lanes raises
    a duplicate-key error. So the key sets must not overlap, every key must
    carry its lane, and no lane may use one key twice.
    """
    per_lane = {lane: _bulk_close_keys(lane) for lane in _LANES}
    for lane, keys in per_lane.items():
        assert len(set(keys.values())) == len(keys)
        assert all(lane in key for key in keys.values())
    assert not set(per_lane[config.LANE_QUESTION].values()) & set(per_lane[config.LANE_GENERAL].values())


def test_r12_no_bulk_close_key_is_written_out_bare_in_app():
    """
    A bare "bc_status" literal anywhere in app.py is a second, lane-less copy of
    the panel (or a leftover of the old one). Only bulk_close_keys may spell keys.
    """
    in_keys_function = {id(n) for n in ast.walk(_app_function("bulk_close_keys"))}
    bare = [n.value for n in ast.walk(_APP_TREE)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and re.match(r"_?bc_", n.value) and id(n) not in in_keys_function]
    assert bare == []
    assert not [n for n in ast.walk(_APP_TREE)
                if isinstance(n, ast.Attribute) and n.attr == "_bc_preview"]


def _calls_to(name: str) -> list:
    """Every call in app.py to something named `name`, as ast.Call nodes."""
    return [n for n in ast.walk(_APP_TREE) if isinstance(n, ast.Call)
            and getattr(n.func, "attr", getattr(n.func, "id", None)) == name]


def test_r12_preview_and_execute_are_called_once_each_with_the_panels_lane():
    """
    One call site each (one panel), both passing the renderer's `lane`, and
    execute also passing the gt_cols that preview returned (R9, R11).
    """
    preview, execute = _calls_to("preview_bulk_close"), _calls_to("execute_bulk_close")
    assert len(preview) == 1 and len(execute) == 1
    for call in (preview[0], execute[0]):
        lane_kw = {k.arg: k.value for k in call.keywords}["lane"]
        assert isinstance(lane_kw, ast.Name) and lane_kw.id == "lane"
    gt_cols_kw = {k.arg: k.value for k in execute[0].keywords}["gt_cols"]
    assert ast.unparse(gt_cols_kw) == "_p['gt_cols']"


_WIDGET_LOCALS = {"_bc_status", "_bc_coach", "_bc_before",
                  "_bc_status_val", "_bc_coach_val", "_bc_before_val"}


def _confirm_branch() -> ast.If:
    """
    In: nothing (reads app.py's source). Out: the innermost `if` of the panel
    that contains the execute_bulk_close call, i.e. the confirm-button branch.
    Why: R9 is about what that branch may read; this finds it without running it.
    """
    panel = _app_function("render_bulk_close_panel")
    execute_call = _calls_to("execute_bulk_close")[0]
    enclosing = [n for n in ast.walk(panel) if isinstance(n, ast.If)
                 and execute_call in list(ast.walk(n))]
    return min(enclosing, key=lambda n: len(list(ast.walk(n))))


def test_r9_execute_filters_come_from_the_stored_preview():
    """
    The number a coach consents to was counted with the filters Preview used.
    So the execute call must read all three from the stored preview entry `_p`,
    never from the widgets as they stand at confirm time (R9).
    """
    keywords = {k.arg: ast.unparse(k.value) for k in _calls_to("execute_bulk_close")[0].keywords}
    for name in ("status_filter", "assigned_to", "before_date"):
        assert keywords[name] == f"_p['{name}']"


def test_r9_confirm_branch_does_not_read_the_filter_widgets():
    """
    Nothing inside the confirm branch may mention a widget or a widget-derived
    local: that is the only way a changed filter could reach the sweep.
    """
    used = {n.id for n in ast.walk(_confirm_branch()) if isinstance(n, ast.Name)}
    assert used & _WIDGET_LOCALS == set()


def test_r9_preview_returns_the_three_filters_it_used(sent_sql, monkeypatch):
    """preview's result carries the filter values it counted with, beside gt_cols."""
    monkeypatch.setattr(bq_reads, "client", _FakeClient())
    result = bq_reads.preview_bulk_close("flagged", "ann@x.org", "2026-01-01", lane=config.LANE_QUESTION)
    assert (result["status_filter"], result["assigned_to"], result["before_date"]) == (
        "flagged", "ann@x.org", "2026-01-01")


def test_r12_each_tab_calls_the_renderer_with_its_own_lane():
    """The Tickets tab passes LANE_QUESTION, the Conversations tab LANE_GENERAL."""
    lanes = sorted(ast.unparse(c.args[0]) for c in _calls_to("render_bulk_close_panel"))
    assert lanes == ["config.LANE_GENERAL", "config.LANE_QUESTION"]
