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


def test_get_tickets_falls_back_to_created_at_on_an_old_schema(monkeypatch):
    """
    Regression guard for the guard, not part of the red-first proof — this
    path exists unchanged on origin/main too (get_tickets has always read
    created_at when the reopen column is missing), so it does not go red
    against origin/main. It pins down that when grant_tickets has no
    last_member_activity_at column yet (mid-Dataform-rebuild), the fallback
    in _urgency_clock_expr() is deliberate behaviour, not an accident: the
    query must still be resolvable (urgency_since always exists, so the
    outer WHERE always has something to filter on) rather than erroring in
    front of a coach.
    """
    captured = []
    monkeypatch.setattr(bq_reads, "_tickets_cols", lambda: set())
    _stub_schema_retry(monkeypatch, captured)

    bq_reads.get_tickets(urgency="Normal")

    sql = captured[0]
    assert "AS urgency_since" in sql
    clock = sql.split("AS urgency_since", 1)[0].rsplit(",", 1)[-1]
    assert clock.strip() == "gt.created_at"
    assert "CASE" not in clock
    assert "TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), urgency_since, HOUR) < 24" in sql


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
    # Isolate the urgency CASE: it is the block between the is_reopened column
    # (which legitimately tests tm.status, R1a) and the "AS urgency" after it.
    urgency_block = sql.split("AS is_reopened,", 1)[1].split("AS urgency", 1)[0]
    assert "tm.status" not in urgency_block


# ---------------------------------------------------------------------------
# is_reopened — bq_reads.md R1a, R4a, R13a, R15a. Red first against 3ecd4d6,
# where "is_reopened" appears in no query.
# ---------------------------------------------------------------------------

# The four built queries: name -> how to call it. get_open_stats and
# get_daily_stats are the two readers of _live_status_cte(); one of them
# stands for that CTE here, the other is checked separately below.
_FOUR_QUERIES = {
    "get_tickets": lambda: bq_reads.get_tickets(),
    "get_ticket_detail": lambda: bq_reads.get_ticket_detail("content_1"),
    "get_member_thread_tickets": lambda: bq_reads.get_member_thread_tickets("t", "m"),
    "get_open_stats": lambda: bq_reads.get_open_stats(),
}


def _predicate_before_alias(sql):
    """The SQL text that is selected AS is_reopened: everything after the
    last line break before the alias, up to the alias."""
    head = sql.split("AS is_reopened", 1)[0]
    return head.rsplit("\n", 1)[1].strip()


def test_all_four_queries_select_is_reopened_from_the_reopen_branch_predicate(monkeypatch):
    """R1a/R13a/R15a: the boolean is the very condition the status branch
    tests, so the mark and the 'open' it explains cannot disagree."""
    _stub_tickets_cols(monkeypatch)
    for name, call in _FOUR_QUERIES.items():
        captured = []
        _stub_schema_retry(monkeypatch, captured)
        call()
        sql = captured[0]
        assert "AS is_reopened" in sql, name
        predicate = _predicate_before_alias(sql)
        assert "tm.status = 'closed'" in predicate, name
        assert "gt.last_member_activity_at > tm.closed_at" in predicate, name
        assert f"WHEN {predicate} THEN 'open'" in sql, name


def test_get_daily_stats_live_cte_selects_is_reopened_too(monkeypatch):
    captured = []
    _stub_tickets_cols(monkeypatch)
    _stub_schema_retry(monkeypatch, captured)

    bq_reads.get_daily_stats()

    assert "AS is_reopened" in captured[0]


def test_r4a_old_schema_still_selects_is_reopened_as_constant_false(monkeypatch):
    """R4a: grant_tickets without last_member_activity_at -> nothing reopens,
    but the column is still there so the app needs no branch for it."""
    monkeypatch.setattr(bq_reads, "_tickets_cols", lambda: set())
    for name, call in _FOUR_QUERIES.items():
        captured = []
        _stub_schema_retry(monkeypatch, captured)
        call()
        sql = captured[0]
        assert _predicate_before_alias(sql) == "FALSE", name
        assert "last_member_activity_at > tm.closed_at" not in sql, name


def test_is_reopened_already_in_the_table_is_excepted_not_duplicated(monkeypatch):
    """Slice 3 adds is_reopened to grant_tickets. gt.* would then carry it
    beside the live one and BigQuery rejects the duplicate name, so the live
    queries must list it in EXCEPT as soon as the table has it."""
    monkeypatch.setattr(
        bq_reads, "_tickets_cols", lambda: {"last_member_activity_at", "is_reopened"}
    )
    for name in ("get_tickets", "get_ticket_detail", "get_member_thread_tickets"):
        captured = []
        _stub_schema_retry(monkeypatch, captured)
        _FOUR_QUERIES[name]()
        except_list = captured[0].split("EXCEPT(", 1)[1].split(")", 1)[0]
        assert "is_reopened" in except_list, name
