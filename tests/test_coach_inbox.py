"""
Offline proof for coach_inbox.py — see docs/specs/modules/coach_inbox.md.

Slice A1 (docs/briefs/coach-inbox-list.md): the merge_into_tickets tracer.
Nothing here touches BigQuery — fixture frames only.
"""

import pandas as pd

import coach_inbox


def _ticket_row(content_id, member_id, member_name, created_at):
    return {
        "content_id": content_id,
        "member_id": member_id,
        "member_name": member_name,
        "created_at": created_at,
    }


def _question_row(content_id, member_id, member_name, created_at, last_activity_at, status):
    return {
        "content_id": content_id,
        "member_id": member_id,
        "member_name": member_name,
        "created_at": created_at,
        "last_activity_at": last_activity_at,
        "status": status,
    }


def _fixture_frames():
    tickets = pd.DataFrame([
        _ticket_row("t1", 1, "Alice", "2026-09-20T10:00:00Z"),
        _ticket_row("t2", 2, "Bob",   "2026-09-23T10:00:00Z"),
    ])
    questions = pd.DataFrame([
        _question_row("pc:th1", 3, "Carol", "2026-09-22T10:00:00Z", "2026-09-22T12:00:00Z", "waiting"),
        _question_row("pc:th2", 4, "Dave",  "2026-09-21T10:00:00Z", "2026-09-21T15:00:00Z", "answered"),
    ])
    return tickets, questions


def test_merge_into_tickets_puts_waiting_questions_first_then_newest_activity():
    # R1: waiting member questions on top, then everything else newest
    # last_activity_at first (tickets fall back to created_at).
    tickets, questions = _fixture_frames()
    merged = coach_inbox.merge_into_tickets(tickets, questions)
    assert merged["content_id"].tolist() == ["pc:th1", "t2", "pc:th2", "t1"]


def test_merge_into_tickets_assigns_source_column():
    # R2: every row is tagged 'ticket' or 'member_question'.
    tickets, questions = _fixture_frames()
    merged = coach_inbox.merge_into_tickets(tickets, questions)
    sources = dict(zip(merged["content_id"], merged["source"]))
    assert sources == {
        "t1": "ticket",
        "t2": "ticket",
        "pc:th1": "member_question",
        "pc:th2": "member_question",
    }


def test_merge_into_tickets_hardcoded_thread_tracer():
    # A1 tracer: one hardcoded thread, no tickets at all, still comes through
    # tagged and orderable — this is the frame app.py's Tickets tab renders.
    tickets = pd.DataFrame(columns=["content_id", "member_id", "member_name", "created_at"])
    hardcoded_thread = pd.DataFrame([
        _question_row("pc:thread-hardcoded-1", 999999, "Anna K.",
                       "2026-09-25T09:00:00Z", "2026-09-25T09:00:00Z", "waiting"),
    ])
    merged = coach_inbox.merge_into_tickets(tickets, hardcoded_thread)
    assert len(merged) == 1
    assert merged.iloc[0]["source"] == "member_question"
    assert merged.iloc[0]["content_id"] == "pc:thread-hardcoded-1"
