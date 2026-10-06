"""
Offline proof for bq_reads.py's urgency clock — see docs/specs/modules/bq_reads.md
"## Derived" (R5-R8) and the per-function rules R12, R14, R15, R18.

Input: nothing from BigQuery. _query_with_schema_retry is stubbed to run the
built SQL string through a fake instead of the real client, and _tickets_cols()
is stubbed to say grant_tickets has last_member_activity_at. Output: the SQL
text each function would have sent. These tests read that text, never a live
table, so they prove the query a coach's screen is built from — not just that
the code agrees with itself.

Run with: PATH=/opt/anaconda3/bin:$PATH python -m pytest tests/test_bq_reads_urgency.py -q
Never `pytest tests/` — that also collects smoke_test.py, which writes to the
live ticket_metadata table.
"""

import pandas as pd

import bq_reads


def _stub_schema_retry(monkeypatch, captured):
    """Makes _query_with_schema_retry run build_sql() and remember the SQL
    text in `captured`, instead of calling real BigQuery. Returns a one-row
    DataFrame carrying every column the callers touch afterwards (domain,
    and the four get_open_stats fields), so none of them crash on the fake
    result."""
    def _fake(build_sql):
        captured.append(build_sql())
        return pd.DataFrame([{
            "domain": None, "open": 0, "normal": 0, "urgent": 0, "critical": 0,
        }])
    monkeypatch.setattr(bq_reads, "_query_with_schema_retry", _fake)


def _stub_tickets_cols(monkeypatch):
    """Makes _tickets_cols() say grant_tickets already has
    last_member_activity_at, so every query builds the R5/R6 clock branch
    instead of the old-schema fallback."""
    monkeypatch.setattr(bq_reads, "_tickets_cols", lambda: {"last_member_activity_at"})


# The R5/R6 clock expression, exactly as _urgency_clock_expr() should build it:
# the member's reopening comment when the ticket was closed before it came in,
# created_at otherwise. Deliberately does not test tm.status (R7).
_CLOCK_PIECES = ("tm.closed_at", "gt.last_member_activity_at", "gt.created_at")


def test_get_tickets_urgency_case_and_filter_both_read_urgency_since(monkeypatch):
    captured = []
    _stub_tickets_cols(monkeypatch)
    _stub_schema_retry(monkeypatch, captured)

    bq_reads.get_tickets(urgency="Normal")

    sql = captured[0]
    assert "AS urgency_since" in sql
    clock = sql.split("AS urgency_since", 1)[0]
    for piece in _CLOCK_PIECES:
        assert piece in clock

    # R12: the badge CASE (outside the `live` CTE) reads urgency_since, not created_at.
    badge = sql.split("AS urgency_since", 1)[1]
    assert "TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), urgency_since, HOUR) < 24 THEN 'normal'" in badge
    assert "TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), urgency_since, HOUR) < 48 THEN 'urgent'" in badge

    # R12: the urgency='Normal' filter reads urgency_since too.
    assert "TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), urgency_since, HOUR) < 24" in sql
    assert sql.count("TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), created_at, HOUR)") == 0


def test_get_ticket_detail_urgency_derives_from_the_clock(monkeypatch):
    captured = []
    _stub_tickets_cols(monkeypatch)
    _stub_schema_retry(monkeypatch, captured)

    bq_reads.get_ticket_detail("content_1")

    sql = captured[0]
    assert "AS urgency" in sql
    for piece in _CLOCK_PIECES:
        assert piece in sql
    assert "TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), gt.created_at, HOUR) < 24 THEN 'normal'" not in sql


def test_get_member_thread_tickets_urgency_derives_from_the_clock(monkeypatch):
    captured = []
    _stub_tickets_cols(monkeypatch)
    _stub_schema_retry(monkeypatch, captured)

    bq_reads.get_member_thread_tickets("thread_1", "member_1")

    sql = captured[0]
    assert "AS urgency" in sql
    for piece in _CLOCK_PIECES:
        assert piece in sql
    assert "TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), gt.created_at, HOUR) < 24 THEN 'normal'" not in sql


def test_get_open_stats_countifs_bucket_on_the_clock_not_created_at(monkeypatch):
    captured = []
    _stub_tickets_cols(monkeypatch)
    _stub_schema_retry(monkeypatch, captured)

    bq_reads.get_open_stats()

    sql = captured[0]
    assert "AS urgency_since" in sql
    for piece in _CLOCK_PIECES:
        assert piece in sql
    assert "TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), urgency_since, HOUR) < 24)" in sql
    assert "TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), urgency_since, HOUR) BETWEEN 24 AND 47)" in sql
    assert "TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), urgency_since, HOUR) >= 48)" in sql
    assert sql.count("TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), created_at, HOUR)") == 0


def test_r7_clock_does_not_test_ticket_status(monkeypatch):
    """The trap named in the brief: copying the reopen clause's tm.status =
    'closed' guard into the clock would snap a reopened-then-answered ticket
    back to critical on one coach click. The clock expression must not gate
    on tm.status at all."""
    captured = []
    _stub_tickets_cols(monkeypatch)
    _stub_schema_retry(monkeypatch, captured)

    bq_reads.get_ticket_detail("content_1")

    sql = captured[0]
    # Isolate the urgency CASE: it is the block between the ticket_status
    # CASE that precedes it and the "AS urgency" that follows it.
    urgency_block = sql.split("AS ticket_status,", 1)[1].split("AS urgency", 1)[0]
    assert "tm.status" not in urgency_block
