"""
coach_inbox — members' private questions (from the questions zone) inside
the Tickets tab.

Spec: docs/specs/modules/coach_inbox.md. This file is built slice by slice —
see docs/briefs/coach-inbox-list.md (list) and its later siblings (reply,
workflow). Only the pieces named in the current slice exist below; a
function this module will need later is not stubbed in ahead of time.
"""

import pandas as pd


def merge_into_tickets(tickets: pd.DataFrame, questions: pd.DataFrame) -> pd.DataFrame:
    """
    Puts member questions into the same list a coach already scrolls — the
    Tickets tab.

    Input: `tickets`, one row per MN ticket (from bq_client.get_tickets);
    `questions`, one row per private-chat thread (from
    load_member_questions), carrying `status` ("waiting"/"answered") and a
    `last_activity_at` timestamp.

    Output: one combined frame with a `source` column ("ticket" or
    "member_question") so the caller can tell the two kinds of row apart —
    waiting member questions on top, then every row (tickets and answered
    questions alike) newest activity first.

    Why: a coach should not have to check two separate lists to see what is
    waiting for a reply.
    """
    tickets = tickets.copy()
    questions = questions.copy()

    if "source" not in tickets.columns:
        tickets["source"] = "ticket"
    if "source" not in questions.columns:
        questions["source"] = "member_question"

    for frame in (tickets, questions):
        if "last_activity_at" not in frame.columns:
            frame["last_activity_at"] = frame.get("created_at")

    if tickets.empty and questions.empty:
        return tickets

    combined = pd.concat([tickets, questions], ignore_index=True, sort=False)
    combined["_activity_at"] = pd.to_datetime(combined["last_activity_at"])

    is_waiting_question = (combined["source"] == "member_question") & (
        combined.get("status") == "waiting"
    )
    # Group 0 = waiting member questions (shown first), group 1 = everything
    # else — each group then sorted newest activity first.
    combined["_group"] = (~is_waiting_question).astype(int)
    combined = combined.sort_values(
        ["_group", "_activity_at"], ascending=[True, False]
    ).drop(columns=["_group", "_activity_at"])

    return combined.reset_index(drop=True)
