"""
coach_inbox — members' private questions (from the questions zone) inside
the Tickets tab.

Spec: docs/specs/modules/coach_inbox.md. This file is built slice by slice —
see docs/briefs/coach-inbox-list.md (list) and its later siblings (reply,
workflow). Only the pieces named in the current slice exist below; a
function this module will need later is not stubbed in ahead of time.
"""

import pandas as pd
from google.cloud import bigquery

import config
import raillog

_QUESTION_COLUMNS = [
    "content_id", "source", "member_id", "member_name", "topic", "subject",
    "created_at", "last_activity_at", "messages", "status",
]


def load_member_questions(client: "bigquery.Client | None" = None) -> pd.DataFrame:
    """
    Reads every member's private-question thread, with its messages, from
    the questions zone's own tables (config.PRIVATE_CHAT_DATASET).

    Input: an optional BigQuery client — tests always pass a fake, so
    importing this module never needs live credentials; the real app calls
    it with no argument and gets bq_base's shared client at CALL time (the
    import below is inside the function, not at module load).

    Output: one row per thread — content_id ("pc:" + thread_id), member_id,
    member_name (from core_members, else "Member <id>"), topic, subject,
    created_at (the thread's own), last_activity_at (its newest message),
    messages (list of {author_role, body, created_at}, oldest first), and
    status ("waiting" when the member spoke last, "answered" when a coach
    did).

    Why: the Tickets tab needs one row per thread, not per message, and
    needs to know at a glance whether a reply is owed.

    R4: when the read itself fails (bad credentials, missing dataset, a
    BigQuery outage), it reports the failure via report_source_failure and
    returns an empty frame with the usual columns rather than raising, so
    the rest of the Tickets tab still renders the MN tickets it does have.
    """
    if client is None:
        from bq_base import client as _default_client
        client = _default_client

    dataset = config.PRIVATE_CHAT_DATASET
    try:
        threads_sql = f"""
            SELECT
                t.thread_id,
                t.member_id,
                t.subject,
                t.topic,
                t.created_at AS thread_created_at,
                ARRAY_AGG(
                    STRUCT(m.author_role AS author_role, m.body AS body, m.created_at AS created_at)
                    ORDER BY m.created_at
                ) AS messages
            FROM `{dataset}.private_threads` t
            JOIN `{dataset}.private_messages` m ON m.thread_id = t.thread_id
            GROUP BY t.thread_id, t.member_id, t.subject, t.topic, t.created_at
        """
        threads = client.query(threads_sql).to_dataframe()
        if threads.empty:
            return pd.DataFrame(columns=_QUESTION_COLUMNS)

        member_ids = sorted({int(mid) for mid in threads["member_id"].dropna().unique()})
        names = _member_names(client, member_ids)

        records = []
        for row in threads.itertuples():
            messages = list(row.messages)
            last_message = messages[-1]
            records.append({
                "content_id": f"pc:{row.thread_id}",
                "source": "member_question",
                "member_id": row.member_id,
                "member_name": names.get(row.member_id, f"Member {row.member_id}"),
                "topic": row.topic,
                "subject": row.subject,
                "created_at": row.thread_created_at,
                "last_activity_at": last_message["created_at"],
                "messages": messages,
                "status": "waiting" if last_message["author_role"] == "member" else "answered",
            })
        return pd.DataFrame.from_records(records, columns=_QUESTION_COLUMNS)
    except Exception as err:
        report_source_failure("read", err)
        return pd.DataFrame(columns=_QUESTION_COLUMNS)


def report_source_failure(operation: str, err: Exception) -> None:
    """
    Input: which private_chat operation failed ("read" so far) and the
    exception it raised. Output: none — logs one BTB_ALERT line via
    raillog.alert, so a failed read is never silently lost to an empty
    Tickets tab.

    Only the exception's own type name goes into the line, never its
    message: a BigQuery error can quote back query text or, worse, a
    member's private words, and this line is read by a wider team than
    the one thread it might be about.
    """
    raillog.alert(
        "coach-inbox", "SOURCE_FAILED",
        f"private_chat {operation} failed: {type(err).__name__}",
    )


def _member_names(client, member_ids: list) -> dict:
    """
    Input: a BigQuery client and the member ids seen in this batch of
    threads. Output: {member_id: full name} for the ones core_members
    knows, so load_member_questions can fall back to "Member <id>" for the
    rest without a query per thread.
    """
    if not member_ids:
        return {}
    sql = f"""
        SELECT
            member_id,
            TRIM(CONCAT(COALESCE(first_name, ''), ' ', COALESCE(last_name, ''))) AS full_name
        FROM `{config.PROJECT_ID}.dataform.core_members`
        WHERE member_id IN UNNEST(@member_ids)
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ArrayQueryParameter("member_ids", "INT64", member_ids)]
    )
    df = client.query(sql, job_config=job_config).to_dataframe()
    return dict(zip(df["member_id"], df["full_name"]))


def waiting_count(questions: pd.DataFrame) -> int:
    """
    Input: the frame from load_member_questions. Output: how many threads
    are waiting on a coach reply, so the Tickets tab can show it at a
    glance without a coach opening each thread.
    """
    if questions.empty:
        return 0
    return int((questions["status"] == "waiting").sum())


def tickets_tab_label(waiting: int) -> str:
    """
    Input: the count from waiting_count. Output: the Tickets tab's own
    label — plain when there is nothing new, a count when there is,
    so a coach can tell from the tab bar alone whether to look.
    """
    if waiting > 0:
        return f"🎫 Tickets ({waiting} new)"
    return "🎫 Tickets"


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
