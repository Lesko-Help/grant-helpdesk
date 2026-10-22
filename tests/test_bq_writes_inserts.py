"""
Offline guard: the bq_writes writers that insert JSON rows never send a NaN.

Why it exists: post_comment, log_rsvp and queue_followup bind no query
parameters; they hand a row dict to client.insert_rows_json, which sanitises
nothing. merge_into_tickets fills missing columns with float NaN, so a NaN
argument would reach BigQuery as a bare `NaN` in the JSON (a 400), or, once
wrapped in str(), as the text 'nan'.

What each case checks: with one argument at a time set to float("nan"), the
row handed to the client holds no float and no value equal to 'nan'.
A completeness check requires every writer that calls insert_rows_json to be
in the table below.

Nothing touches BigQuery: a fake client remembers the rows.
Run: PATH=/opt/anaconda3/bin:$PATH python -m pytest tests/test_bq_writes_inserts.py -q
"""

import ast
import inspect

import pytest

import bq_writes

NAN = float("nan")

# writer name -> (good keyword arguments, the arguments that carry a NaN in turn)
CASES = {
    "post_comment": (
        dict(content_id="c1", author="a", body="b"),
        ["content_id", "author", "body"]),
    "log_rsvp": (
        dict(content_id="c1", event_id=7, member_id="m1", rsvped_by="a"),
        ["content_id", "event_id", "member_id", "rsvped_by"]),
    "queue_followup": (
        dict(ticket_id="t1", content_id="c1", content_type="q", member_id="m1",
             member_name="n", message="hi", days=3, scheduled_by="a"),
        ["ticket_id", "content_id", "content_type", "member_id", "member_name",
         "message", "scheduled_by"]),
}


class _FakeClient:
    """Remembers the rows passed to insert_rows_json; sends nothing."""

    def __init__(self):
        self.rows = None

    def get_table(self, name):
        return name

    def insert_rows_json(self, table, rows):
        self.rows = rows
        return []


@pytest.fixture
def fake(monkeypatch):
    """In: nothing. Out: the fake client installed in bq_writes."""
    client = _FakeClient()
    monkeypatch.setattr(bq_writes, "client", client)
    return client


def _cases():
    """In: nothing. Out: (writer, nan argument) pairs, one per table entry."""
    return [(w, a) for w, (_, args) in CASES.items() for a in args]


@pytest.mark.parametrize("writer,argument", _cases())
def test_nan_argument_never_reaches_the_row(fake, writer, argument):
    """In: a writer and one argument set to NaN. Out: nothing; raises if any
    value in the row is a float or the text 'nan'. Why: both are 400s or bad data."""
    good, _ = CASES[writer]
    getattr(bq_writes, writer)(**{**good, argument: NAN})
    assert len(fake.rows) == 1
    for column, value in fake.rows[0].items():
        assert not isinstance(value, float), f"{argument}=NaN: {column} is a float"
        assert value != "nan", f"{argument}=NaN: {column} is the text 'nan'"


def test_every_insert_writer_is_in_the_table():
    """In: bq_writes source. Out: nothing; raises if a function that calls
    insert_rows_json is missing from CASES. Why: a new writer must not escape."""
    tree = ast.parse(inspect.getsource(bq_writes))
    users = {
        fn.name for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef)
        and any(isinstance(n, ast.Attribute) and n.attr == "insert_rows_json"
                for n in ast.walk(fn))}
    assert users, "found no insert_rows_json caller: the guard is vacuous"
    assert users <= set(CASES), f"not in CASES: {sorted(users - set(CASES))}"
