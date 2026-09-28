"""
Offline proof for coach_inbox.add_coach_reply — see
docs/specs/modules/coach_inbox.md's add_coach_reply stub and
docs/briefs/coach-inbox-reply.md.

A fake BigQuery client only, same as tests/test_coach_inbox.py — this file
never needs live credentials or touches BigQuery.
"""

import uuid

import coach_inbox


class _FakeInsertJob:
    """Stands in for a google.cloud.bigquery QueryJob after an INSERT: only
    .result() and .num_dml_affected_rows are ever touched by add_coach_reply."""

    def __init__(self, affected_rows):
        self._affected_rows = affected_rows

    def result(self):
        return self

    @property
    def num_dml_affected_rows(self):
        return self._affected_rows


class _FakeInsertClient:
    """Records every query() call (sql text and job_config) so a test can
    inspect the exact parameters add_coach_reply sent, without ever running
    real SQL. affected_rows simulates the INSERT...SELECT's own row count —
    0 is what an unknown thread_id looks like, since the SELECT's FROM
    private_threads WHERE thread_id = @thread_id then matches nothing."""

    def __init__(self, affected_rows=1):
        self.affected_rows = affected_rows
        self.queries = []
        self.job_configs = []

    def query(self, sql, job_config=None):
        self.queries.append(sql)
        self.job_configs.append(job_config)
        return _FakeInsertJob(self.affected_rows)


class _RaisingInsertClient:
    """Stands in for a client whose query() fails outright — a bad
    credential, a missing dataset, a BigQuery outage — so add_coach_reply's
    own write-failure path can be proven without touching real BigQuery."""

    def query(self, sql, job_config=None):
        raise RuntimeError("could not reach BigQuery")


def _params(job_config):
    return {p.name: p.value for p in job_config.query_parameters}


# ── success path: exact SQL shape and parameters ────────────────────────────

def test_add_coach_reply_success_writes_expected_params_and_returns_true():
    fake = _FakeInsertClient(affected_rows=1)

    result = coach_inbox.add_coach_reply("th1", 42, "  Thanks for reaching out!  ", client=fake)

    assert result is True
    assert len(fake.queries) == 1
    sql = fake.queries[0]
    assert "INSERT INTO" in sql
    assert "private_messages" in sql
    assert "private_threads" in sql
    assert "WHERE thread_id = @thread_id" in sql
    assert "'coach'" in sql  # author_role is a literal, not a parameter

    params = _params(fake.job_configs[0])
    assert params["thread_id"] == "th1"
    assert params["author_member_id"] == 42
    assert params["body"] == "Thanks for reaching out!"  # stripped
    assert uuid.UUID(params["message_id"]).version == 4
    assert "author_role" not in params  # 'coach' is written as a SQL literal


def test_add_coach_reply_generates_a_fresh_uuid_each_call():
    fake = _FakeInsertClient(affected_rows=1)

    coach_inbox.add_coach_reply("th1", 1, "first reply", client=fake)
    coach_inbox.add_coach_reply("th1", 1, "second reply", client=fake)

    ids = [_params(jc)["message_id"] for jc in fake.job_configs]
    assert ids[0] != ids[1]


def test_add_coach_reply_does_not_restrict_who_may_reply():
    # "Any coach may reply in any thread" — add_coach_reply takes whichever
    # author_member_id it is given and never checks it against an assignee.
    fake = _FakeInsertClient(affected_rows=1)

    assert coach_inbox.add_coach_reply("th1", 7, "from coach 7", client=fake) is True
    assert coach_inbox.add_coach_reply("th1", 99, "from coach 99", client=fake) is True

    author_ids = [_params(jc)["author_member_id"] for jc in fake.job_configs]
    assert author_ids == [7, 99]


# ── body validation: refused before any query ───────────────────────────────

def test_add_coach_reply_refuses_a_blank_body_without_sending_a_query():
    fake = _FakeInsertClient(affected_rows=1)

    assert coach_inbox.add_coach_reply("th1", 1, "   ", client=fake) is False
    assert coach_inbox.add_coach_reply("th1", 1, "", client=fake) is False
    assert fake.queries == []


def test_add_coach_reply_refuses_a_body_over_4000_chars_after_stripping():
    fake = _FakeInsertClient(affected_rows=1)

    too_long = "  " + ("x" * 4001) + "  "
    assert coach_inbox.add_coach_reply("th1", 1, too_long, client=fake) is False
    assert fake.queries == []


def test_add_coach_reply_accepts_the_1_and_4000_char_boundaries():
    fake = _FakeInsertClient(affected_rows=1)

    assert coach_inbox.add_coach_reply("th1", 1, "a", client=fake) is True
    assert coach_inbox.add_coach_reply("th1", 1, "x" * 4000, client=fake) is True

    bodies = [_params(jc)["body"] for jc in fake.job_configs]
    assert bodies == ["a", "x" * 4000]


# ── unknown thread: query runs, zero rows, False ────────────────────────────

def test_add_coach_reply_unknown_thread_sends_the_query_but_returns_false():
    fake = _FakeInsertClient(affected_rows=0)

    result = coach_inbox.add_coach_reply("no-such-thread", 1, "hello?", client=fake)

    assert result is False
    assert len(fake.queries) == 1  # the query WAS attempted — this is not the refusal path


# ── write failure: reported the same way a read failure is, body never logged ──

def test_add_coach_reply_write_failure_reports_source_failure_and_returns_false(capsys):
    result = coach_inbox.add_coach_reply("th1", 1, "hello there", client=_RaisingInsertClient())

    assert result is False
    out = capsys.readouterr().out.strip()
    assert out == (
        '{"severity": "ERROR", "message": '
        '"BTB_ALERT grant-helpdesk/coach-inbox SOURCE_FAILED: '
        'private_chat write failed: RuntimeError"}'
    )


def test_add_coach_reply_never_logs_the_body(capsys):
    secret = "please don't repeat this member's private secret phrase"

    # Success: no alert at all, so nothing to leak.
    coach_inbox.add_coach_reply("th1", 1, secret, client=_FakeInsertClient(affected_rows=1))
    assert capsys.readouterr().out == ""

    # Failure: the alert line names only the exception type, never the body.
    coach_inbox.add_coach_reply("th1", 1, secret, client=_RaisingInsertClient())
    out = capsys.readouterr().out
    assert "secret phrase" not in out
    assert "repeat" not in out
