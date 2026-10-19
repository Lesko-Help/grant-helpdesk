"""
Offline proof for definitions/marts/grant_tickets.sqlx — slice 3 of the
reopened-mark brief; bq_reads.md "## Derived" (R1, R1a) and its 2026-10-19
decisions. Input: the .sqlx text. Output: pass/fail on what the table's SQL
says. Nothing is compiled or run against BigQuery.

The table's reopen must agree with the live CTE in bq_reads.py, and slice 3 is
additive: ticket_status keeps returning 'open' for a reopened row, and the new
is_reopened column is the same status-free test as the app's mark (R1a).

Run with: PATH=/opt/anaconda3/bin:$PATH python -m pytest tests/test_grant_tickets_sqlx_is_reopened.py -q
Never `pytest tests/` — that also collects smoke_test.py, which writes to the
live ticket_metadata table.
"""

import re
from pathlib import Path

SQLX = (
    Path(__file__).resolve().parent.parent / "definitions/marts/grant_tickets.sqlx"
).read_text()


def _select_expression(alias):
    """The SQL text a one-line SELECT column is computed from: the line that
    ends in `AS <alias>,`, without the alias. Fails if there is none."""
    match = re.search(r"^\s*(.*?)\s+AS\s+" + alias + r"\s*,\s*$", SQLX, re.MULTILINE)
    assert match, f"no column AS {alias} in grant_tickets.sqlx"
    return match.group(1)


def test_table_has_an_is_reopened_column_with_the_status_free_predicate():
    expression = _select_expression("is_reopened")
    assert "ma.last_member_activity_at > t.closed_at" in expression
    # R1a: the mark tests no status, so it survives a coach marking 'answered'.
    assert "t.status" not in expression
    # A missing side must read FALSE, never NULL, so SQL readers can filter on it.
    assert "COALESCE(" in expression and "FALSE" in expression


def test_ticket_status_still_reopens_to_open_and_stays_a_status_value():
    """Additive: rule (4) is untouched, so no existing reader of
    ticket_status sees a new value."""
    assert re.search(
        r"WHEN t\.status = 'closed'\s+AND ma\.last_member_activity_at > t\.closed_at\s+THEN 'open'",
        SQLX,
    )
    assert "'reopened'" not in SQLX
