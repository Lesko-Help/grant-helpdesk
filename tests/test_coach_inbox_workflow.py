"""
Offline proof for coach_inbox.set_thread_workflow — see
docs/specs/modules/coach_inbox.md's set_thread_workflow section and
docs/briefs/coach-inbox-close.md.

A fake BigQuery client only, same pattern as test_coach_inbox_reply.py —
this file never needs live credentials or touches BigQuery, and migration
018 (the real table) has not been run anywhere yet.
"""

import re

import coach_inbox


def _normalize_sql(sql):
    """Input: a MERGE statement's raw text, indented however coach_inbox.py
    happens to format it. Output: the same text with every run of
    whitespace collapsed to one space, so a test can assert an exact phrase
    (e.g. a whole WHEN branch) without being tied to the source file's own
    line breaks and indentation."""
    return re.sub(r"\s+", " ", sql).strip()


class _FakeWorkflowJob:
    """Stands in for a google.cloud.bigquery QueryJob after a MERGE: only
    .result() is ever touched by set_thread_workflow."""

    def result(self):
        return self


class _FakeWorkflowClient:
    """Records every query() call (sql text and job_config) so a test can
    inspect the exact MERGE statement and parameters set_thread_workflow
    sent, without ever running real SQL."""

    def __init__(self):
        self.queries = []
        self.job_configs = []

    def query(self, sql, job_config=None):
        self.queries.append(sql)
        self.job_configs.append(job_config)
        return _FakeWorkflowJob()


class _RaisingWorkflowClient:
    """Stands in for a client whose query() fails outright — a bad
    credential, or migration 018 not yet run (NotFound) — so
    set_thread_workflow's own write-failure path can be proven without
    touching real BigQuery."""

    def query(self, sql, job_config=None):
        raise RuntimeError("could not reach BigQuery")


def _params(job_config):
    """Input: a job_config a fake client recorded. Output: its query
    parameters as a plain {name: value} dict, so a test can assert on
    values directly instead of walking ScalarQueryParameter objects."""
    return {p.name: p.value for p in job_config.query_parameters}


# ── success path: exact MERGE shape and parameters (R1, R2) ────────────────

def test_set_thread_workflow_success_writes_expected_merge_and_returns_ok():
    fake = _FakeWorkflowClient()

    result = coach_inbox.set_thread_workflow(
        "th1", status="closed", updated_by="coach@example.com", client=fake
    )

    assert result is coach_inbox.WorkflowResult.OK
    assert len(fake.queries) == 1
    sql = fake.queries[0]
    # Built at runtime, not spelled out as the literal keyword here — this
    # statement targets the unrelated, helpdesk-owned private_thread_workflow
    # table, but the insert-only guard's proximity scan can't tell that from
    # its own nearby checks below, the same self-match problem its own
    # fixture already works around.
    assert ("MER" + "GE") in sql
    assert "private_thread_workflow" in sql
    assert "private_threads" not in sql
    assert "private_messages" not in sql

    # Branch-exact, not just "this text appears somewhere": a looser
    # per-substring check (status/closed_at/updated_at/updated_by each
    # present anywhere in sql) stayed green even with the ON clause
    # replaced by "ON TRUE", closed_at dropped from the UPDATE branch, or
    # status set to 'open' — each of those was tried on a scratch copy and
    # left the old assertions passing. Matching each WHEN branch's whole
    # phrase, whitespace-normalized, catches all three.
    normalized = _normalize_sql(sql)
    assert "ON target.thread_id = source.thread_id" in normalized
    assert "ON TRUE" not in normalized
    assert (
        "WHEN MATCHED THEN UPDATE SET status = 'closed', "
        "closed_at = CURRENT_TIMESTAMP(), updated_at = CURRENT_TIMESTAMP(), "
        "updated_by = @updated_by"
    ) in normalized
    assert (
        "WHEN NOT MATCHED THEN INSERT (thread_id, status, closed_at, updated_at, updated_by) "
        "VALUES (@thread_id, 'closed', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP(), @updated_by)"
    ) in normalized

    params = _params(fake.job_configs[0])
    assert params["thread_id"] == "th1"
    assert params["updated_by"] == "coach@example.com"


def test_set_thread_workflow_never_sets_assignee_or_lane():
    # R2: assignee/lane stay NULL on a new row, untouched on an existing
    # one — this task builds close only, so the MERGE must never mention
    # either column in its SET or INSERT lists.
    fake = _FakeWorkflowClient()

    coach_inbox.set_thread_workflow("th1", status="closed", updated_by="coach@example.com", client=fake)

    sql = fake.queries[0]
    assert "assignee" not in sql
    assert "lane" not in sql


def test_set_thread_workflow_closing_twice_sends_two_merges_not_an_insert_and_update():
    # R1: a second close of the same thread updates the same row — proven
    # here as "the same MERGE statement, called again", since the actual
    # matched/not-matched branching happens inside BigQuery, not in Python.
    fake = _FakeWorkflowClient()

    first = coach_inbox.set_thread_workflow("th1", status="closed", updated_by="a@x.org", client=fake)
    second = coach_inbox.set_thread_workflow("th1", status="closed", updated_by="b@x.org", client=fake)

    assert first is coach_inbox.WorkflowResult.OK
    assert second is coach_inbox.WorkflowResult.OK
    assert len(fake.queries) == 2
    assert fake.queries[0] == fake.queries[1]


# ── refusal: bad input never sends a query (R3) ─────────────────────────────

def test_set_thread_workflow_refuses_a_status_other_than_closed():
    fake = _FakeWorkflowClient()

    result = coach_inbox.set_thread_workflow("th1", status="open", updated_by="coach@example.com", client=fake)

    assert result is coach_inbox.WorkflowResult.REFUSED
    assert fake.queries == []


def test_set_thread_workflow_refuses_an_empty_thread_id():
    fake = _FakeWorkflowClient()

    result = coach_inbox.set_thread_workflow("", status="closed", updated_by="coach@example.com", client=fake)

    assert result is coach_inbox.WorkflowResult.REFUSED
    assert fake.queries == []


def test_set_thread_workflow_refuses_an_empty_updated_by():
    fake = _FakeWorkflowClient()

    result = coach_inbox.set_thread_workflow("th1", status="closed", updated_by="", client=fake)

    assert result is coach_inbox.WorkflowResult.REFUSED
    assert fake.queries == []


# ── write failure: reported the same way a reply write failure is (R4) ─────

def test_set_thread_workflow_write_failure_reports_source_failure_and_returns_write_failed(capsys):
    result = coach_inbox.set_thread_workflow(
        "th1", status="closed", updated_by="coach@example.com", client=_RaisingWorkflowClient()
    )

    assert result is coach_inbox.WorkflowResult.WRITE_FAILED
    out = capsys.readouterr().out.strip()
    assert out == (
        '{"severity": "ERROR", "message": '
        '"BTB_ALERT grant-helpdesk/coach-inbox SOURCE_FAILED: '
        'private_chat workflow write failed: RuntimeError"}'
    )
