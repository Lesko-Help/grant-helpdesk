"""
Offline proof for the bulk close sweep — docs/specs/modules/bq_writes.md,
`### execute_bulk_close(...)`, rules R2, R3, R4 and R9.

Input: nothing from BigQuery. The `client` of bq_reads and bq_writes is swapped
for a fake that only remembers the SQL text it was asked to run. Output: that
text. Every test reads the SQL a coach's click would send, never a live table.

Run with: PATH=/opt/anaconda3/bin:$PATH python -m pytest tests/test_bulk_close.py -q
Never `pytest tests/` — that also collects smoke_test.py, which writes to the
live ticket_metadata table.
"""

import json
import pathlib
import re
from collections import Counter

import pytest

import bq_reads
import bq_writes


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
    def run(which, status="answered", assigned="", before=""):
        fake = _FakeClient()
        monkeypatch.setattr(bq_reads, "client", fake)
        monkeypatch.setattr(bq_writes, "client", fake)
        if which == "execute":
            bq_writes.execute_bulk_close(status, assigned, before, "coach@x.org")
        else:
            bq_reads.preview_bulk_close(status, assigned, before)
        return fake.sql
    return run


def _where(sql: str) -> str:
    """The helper's WHERE line, without the keyword: its AND-ed conditions."""
    return re.search(r"WHERE (t\.effective_status NOT IN.*)", sql).group(1)


# R2 -------------------------------------------------------------------------

def test_r2_empty_filters_add_no_constraint():
    """All three "" -> the widest sweep: only the not-closed exclusion remains."""
    where = _where(bq_reads.bulk_close_rows_sql("", "", ""))
    assert "AND" not in where
    assert "effective_status =" not in where
    assert "effective_assigned_to" not in where
    assert "DATE(" not in where


def test_r2_each_filter_adds_only_its_own_condition():
    """One filter set -> exactly one extra condition, and not the others."""
    status = _where(bq_reads.bulk_close_rows_sql("answered", "", ""))
    coach = _where(bq_reads.bulk_close_rows_sql("", "coach@x.org", ""))
    date = _where(bq_reads.bulk_close_rows_sql("", "", "2026-01-01"))
    assert status.count(" AND ") == 1 and "effective_status = 'answered'" in status
    assert coach.count(" AND ") == 1 and "effective_assigned_to = 'coach@x.org'" in coach
    assert date.count(" AND ") == 1 and "DATE(t.created_at) < '2026-01-01'" in date


def test_r2_filters_are_anded_together():
    """All three set -> three extra conditions joined by AND, never OR."""
    where = _where(bq_reads.bulk_close_rows_sql("answered", "coach@x.org", "2026-01-01"))
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
        where = _where(bq_reads.bulk_close_rows_sql(*filters))
        listed = re.search(r"NOT IN \(([^)]*)\)", where).group(1)
        assert sorted(re.findall(r"'(\w+)'", listed)) == ["archived", "cancelled", "closed"]


def test_r4_archived_is_excluded_even_when_the_status_filter_asks_for_it():
    """status_filter="archived" is ANDed with the exclusion, so it matches nothing."""
    where = _where(bq_reads.bulk_close_rows_sql("archived", "", ""))
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
    selection = bq_reads.bulk_close_rows_sql(*filters)
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
# helper columns preview now carries.
_ALLOWED_EXECUTE = {
    "added": [") r", "FROM (", "SELECT r.content_id, r.assigned_to, r.domain",
              "WHERE r.content_id NOT IN ("],
    "removed": ["AND t.content_id NOT IN ("],
}
_ALLOWED_PREVIEW = {
    "added": [")", "COALESCE(tm.assigned_to, gt.assigned_to) AS assigned_to,",
              "COALESCE(tm.domain, gt.domain)           AS domain,",
              "SELECT t.content_id, t.assigned_to, t.domain", "WITH filtered AS ("],
    "removed": ["),", "SELECT t.content_id", "filtered AS ("],
}


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
    assert sorted((new - old).elements()) == sorted(allowed["added"])
    assert sorted((old - new).elements()) == sorted(allowed["removed"])
