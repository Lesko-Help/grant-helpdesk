"""
Offline proof for the REOPENED chip in app.py — bq_reads.md R1a, R13a, R15a,
R18a. Slice 2 of the reopened-mark brief.

app.py cannot be imported here (it starts Streamlit and reads secrets), so
this test pulls the one pure function, _reopened_chip, out of app.py's source
with `ast` and runs it on its own, and reads the same source to prove that
each of the three render sites calls it. Input: app.py's text. Output: a
pass/fail on what the chip shows for a row and where it is drawn.

Run with: PATH=/opt/anaconda3/bin:$PATH python -m pytest tests/test_reopened_chip.py -q
Never `pytest tests/` — that also collects smoke_test.py, which writes to the
live ticket_metadata table.
"""

import ast
from pathlib import Path

import pandas as pd

APP_SOURCE = (Path(__file__).resolve().parent.parent / "app.py").read_text()
APP_TREE = ast.parse(APP_SOURCE)


def _function_source(name):
    """Source text of the top-level function `name` in app.py, or a failed
    assert if it does not exist (so a missing helper is red, not an error)."""
    for node in APP_TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(APP_SOURCE, node)
    raise AssertionError(f"app.py has no top-level function {name}")


def _chip(row):
    """Runs app.py's real _reopened_chip on `row` (a dict or Series)."""
    namespace = {"pd": pd}
    exec(_function_source("_reopened_chip"), namespace)
    return namespace["_reopened_chip"](row)


def test_chip_shows_for_a_reopened_row_and_only_then():
    assert "REOPENED" in _chip({"is_reopened": True})
    assert "REOPENED" in _chip(pd.Series({"is_reopened": True}))
    assert _chip({"is_reopened": False}) == ""


def test_chip_is_empty_when_the_column_is_missing_or_null():
    """A cached row from before this change has no column; a pandas NaN is
    truthy in Python and must not draw the chip."""
    assert _chip({}) == ""
    assert _chip({"is_reopened": None}) == ""
    assert _chip({"is_reopened": float("nan")}) == ""
    assert _chip(pd.Series({"is_reopened": pd.NA})) == ""


def test_chip_is_drawn_at_the_list_row_the_detail_header_and_both_group_cards():
    """Four draw points in three places: render_ticket_table's ticket row,
    show_ticket_dialog's badge row, and show_group_dialog's open and done cards."""
    for function_name, expected_calls in (
        ("render_ticket_table", 1),
        ("show_ticket_dialog", 1),
        ("show_group_dialog", 2),
    ):
        source = _function_source(function_name)
        assert source.count("_reopened_chip(") == expected_calls, function_name


def test_chip_never_replaces_the_status_badge_or_touches_the_dropdown():
    """R18a/R13a: the mark sits beside the status, the dropdown list and the
    open/done split stay on ticket_status alone."""
    detail = _function_source("show_ticket_dialog")
    assert 'badge badge-{_status}' in detail
    group = _function_source("show_group_dialog")
    assert "is_reopened" not in group.replace("_reopened_chip(t)", "")
    assert "config.is_open_status" in group
