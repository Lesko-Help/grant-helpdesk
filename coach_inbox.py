"""
coach_inbox — members' private questions (from the questions zone) inside
the Tickets tab.

Spec: docs/specs/modules/coach_inbox.md. This file is built slice by slice —
see docs/briefs/coach-inbox-list.md (list) and its later siblings (reply,
workflow). Only the pieces named in the current slice exist below; a
function this module will need later is not stubbed in ahead of time.
"""

import enum
import uuid

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

    The returned frame's `.attrs["read_failed"]` carries whether this call's
    own read failed (read_failed() reads it back) — a module-level flag was
    tried first and dropped (re-review minor 1): app.py's cached wrapper
    means a cache HIT never re-runs this function, so a flag set by someone
    else's cache-missed call, or a dev hot-reload resetting the module,
    could describe the wrong call by the time a caller checks it. Carrying
    the signal on the object itself keeps it correct no matter which call
    produced the cached frame a caller is holding.
    """
    if client is None:
        from bq_base import client as _default_client
        client = _default_client

    dataset = config.PRIVATE_CHAT_DATASET
    try:
        # R1: one query, not two joined in pandas. private_chat's dataset and
        # core_members's dataset live in different GCP projects but the same
        # region (both confirmed EU via `bq show` — see brief, review finding
        # 6), so a cross-project JOIN reaches both in one round trip; the
        # `client_id` filter on core_members keeps a same-numbered member from
        # another client out (review finding 5). `names` collapses
        # core_members to at most one row per member_id BEFORE the join to
        # `threads` (re-review minor 2): joining the raw, ungrouped
        # core_members table straight into the messages GROUP BY would
        # duplicate every message in a thread once per matching core_members
        # row if that table ever carried more than one row for the same
        # (member_id, client_id), corrupting `last_activity_at`/`status`
        # along with it.
        threads_sql = f"""
            WITH threads AS (
                SELECT
                    t.thread_id,
                    t.member_id,
                    t.subject,
                    t.topic,
                    t.created_at AS thread_created_at,
                    ARRAY_AGG(
                        STRUCT(m.author_role AS author_role, m.body AS body, m.created_at AS created_at)
                        ORDER BY m.created_at, m.message_id
                    ) AS messages
                FROM `{dataset}.private_threads` t
                JOIN `{dataset}.private_messages` m ON m.thread_id = t.thread_id
                GROUP BY t.thread_id, t.member_id, t.subject, t.topic, t.created_at
            ),
            names AS (
                SELECT
                    member_id,
                    ANY_VALUE(
                        TRIM(CONCAT(COALESCE(first_name, ''), ' ', COALESCE(last_name, '')))
                    ) AS full_name
                FROM `{config.PROJECT_ID}.dataform.core_members`
                WHERE client_id = 'lesko_4022250'
                GROUP BY member_id
            )
            SELECT threads.*, names.full_name
            FROM threads
            LEFT JOIN names ON names.member_id = threads.member_id
        """
        threads = client.query(threads_sql).to_dataframe()
        if threads.empty:
            empty = pd.DataFrame(columns=_QUESTION_COLUMNS)
            empty.attrs["read_failed"] = False
            return empty

        records = []
        thread_ids = []
        for row in threads.itertuples():
            messages = list(row.messages)
            last_message = messages[-1]
            full_name = (row.full_name or "").strip()
            thread_ids.append(row.thread_id)
            records.append({
                "content_id": f"pc:{row.thread_id}",
                "source": "member_question",
                "member_id": row.member_id,
                "member_name": full_name if full_name else f"Member {row.member_id}",
                "topic": row.topic,
                "subject": row.subject,
                "created_at": row.thread_created_at,
                "last_activity_at": last_message["created_at"],
                "messages": messages,
                "status": "waiting" if last_message["author_role"] == "member" else "answered",
            })

        closed_at_by_thread = _read_workflow_closed_at(client)
        for rec, thread_id in zip(records, thread_ids):
            closed_at = closed_at_by_thread.get(thread_id)
            if closed_at is None:
                continue
            newest_member_at = max(
                (m["created_at"] for m in rec["messages"] if m["author_role"] == "member"),
                default=None,
            )
            # R5: a member message after closed_at reopens the thread as
            # waiting, nothing written; otherwise it stays closed (R3),
            # overriding whatever waiting/answered the loop above set.
            rec["status"] = "waiting" if newest_member_at and newest_member_at > closed_at else "closed"

        result = pd.DataFrame.from_records(records, columns=_QUESTION_COLUMNS)
        result.attrs["read_failed"] = False
        return result
    except Exception as err:
        report_source_failure("read", err)
        failed = pd.DataFrame(columns=_QUESTION_COLUMNS)
        failed.attrs["read_failed"] = True
        return failed


def _read_workflow_closed_at(client: "bigquery.Client") -> dict:
    """
    Input: the BigQuery client load_member_questions is already using.
    Output: a dict of thread_id -> closed_at for every row marked closed in
    private_thread_workflow (config.PRIVATE_THREAD_WORKFLOW_TABLE).

    R6: when this read fails — the table does not exist yet (migration 018
    not yet run), a bad credential, an outage — it reports the failure as
    "workflow read" (distinct from load_member_questions's own "read" alert,
    so the BTB_ALERT line says which half of the data was lost) and returns
    an empty dict, so the caller marks no thread closed rather than losing
    the whole list. This is caught here, not by the caller's own try/except,
    so a workflow outage can never be mistaken for the main read failing.
    """
    try:
        sql = f"""
            SELECT thread_id, closed_at
            FROM `{config.PRIVATE_THREAD_WORKFLOW_TABLE}`
            WHERE status = 'closed'
        """
        workflow = client.query(sql).to_dataframe()
        return dict(zip(workflow["thread_id"], workflow["closed_at"]))
    except Exception as err:
        report_source_failure("workflow read", err)
        return {}


def read_failed(questions: pd.DataFrame) -> bool:
    """
    Input: the frame a load_member_questions call returned. Output: whether
    that call's own read failed (already reported via report_source_failure)
    rather than genuinely finding zero questions — both come back as an
    identical-looking empty frame, so `.attrs["read_failed"]`, set on the
    frame itself by load_member_questions, is the only way a caller can tell
    the two apart and decide whether to show its own st.error.
    """
    return bool(questions.attrs.get("read_failed", False))


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


class ReplyResult(enum.Enum):
    """
    What one add_coach_reply call actually did. A bare bool cannot tell a
    coach's mistake (blank body), a stale page (thread gone), and a real
    outage apart — and only the last of those is worth telling a coach to
    retry unchanged, so app.py needs the other two named separately.
    """
    OK = "ok"                        # one row landed in private_messages
    REFUSED = "refused"              # no query sent: bad body or no author
    UNKNOWN_THREAD = "unknown_thread"  # query ran, zero rows: thread_id unknown
    WRITE_FAILED = "write_failed"    # query raised; reported via report_source_failure


def add_coach_reply(
    thread_id: str,
    author_member_id: "int | None",
    body: str,
    client: "bigquery.Client | None" = None,
) -> ReplyResult:
    """
    Writes one coach reply into a member's private-question thread.

    Input: thread_id (which thread to reply into), author_member_id (the
    replying coach's own row in grant_coaches — the admin has one too, so
    app.py resolves this the same way for both; None is refused rather than
    written as a NULL author), body (the reply text), and an optional
    BigQuery client (tests always pass a fake, same as load_member_questions
    — the real app calls it with no argument).

    Output: a ReplyResult — OK once one row landed in private_messages;
    REFUSED when author_member_id is None or the body failed its own check
    (stripped to 1-4000 chars), in which case no query ever ran;
    UNKNOWN_THREAD when the query ran but touched zero rows, which only
    happens when thread_id names no row in private_threads; WRITE_FAILED
    when the query raised, in which case the failure is reported the same
    way a read failure is. app.py shows a different message for each,
    since only WRITE_FAILED is worth telling the coach to retry unchanged.

    Why INSERT...SELECT rather than a plain INSERT: the SELECT's own
    "FROM private_threads WHERE thread_id = @thread_id" is what makes an
    unknown thread fail closed (zero rows written) instead of inserting an
    orphan message row — this repo has no foreign key to lean on instead.
    author_role is written as the literal 'coach', never a parameter — a
    member's own first message is the only 'member' row, written by the
    zone, never by this function.

    Any coach may reply in any thread: this never checks who thread_id is
    assigned to, only that it exists. A write failure never puts the body
    into the BTB_ALERT line, or anywhere else — same rule as a read failure.
    """
    if author_member_id is None:
        return ReplyResult.REFUSED

    stripped = (body or "").strip()
    if not (1 <= len(stripped) <= 4000):
        return ReplyResult.REFUSED

    if client is None:
        from bq_base import client as _default_client
        client = _default_client

    dataset = config.PRIVATE_CHAT_DATASET
    sql = f"""
        INSERT INTO `{dataset}.private_messages`
            (message_id, thread_id, author_role, author_member_id, body, created_at)
        SELECT @message_id, thread_id, 'coach', @author_member_id, @body, CURRENT_TIMESTAMP()
        FROM `{dataset}.private_threads`
        WHERE thread_id = @thread_id
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("message_id", "STRING", str(uuid.uuid4())),
        bigquery.ScalarQueryParameter("author_member_id", "INT64", author_member_id),
        bigquery.ScalarQueryParameter("body", "STRING", stripped),
        bigquery.ScalarQueryParameter("thread_id", "STRING", thread_id),
    ])
    try:
        job = client.query(sql, job_config=job_config)
        job.result()
    except Exception as err:
        report_source_failure("write", err)
        return ReplyResult.WRITE_FAILED
    return ReplyResult.OK if job.num_dml_affected_rows else ReplyResult.UNKNOWN_THREAD


class WorkflowResult(enum.Enum):
    """
    What one set_thread_workflow call actually did — mirrors ReplyResult,
    so app.py can tell a coach's own mistake (an empty updated_by, a status
    this function does not yet accept) apart from a real BigQuery outage,
    instead of collapsing both into one bool.
    """
    OK = "ok"                      # row landed in private_thread_workflow
    REFUSED = "refused"            # no query sent: bad status or empty id/updated_by
    WRITE_FAILED = "write_failed"  # query raised; reported via report_source_failure


def set_thread_workflow(
    thread_id: str,
    *,
    status: str,
    updated_by: str,
    client: "bigquery.Client | None" = None,
) -> WorkflowResult:
    """
    Closes a member-question thread by writing one row into
    private_thread_workflow, the helpdesk-owned table that carries
    close/assign/lane state so the insert-only private_chat zone tables
    never need a status column of their own.

    Input: thread_id (which thread); status (only the literal "closed" is
    accepted — assign/lane are a later task, so nothing else is handled
    yet); updated_by (the acting coach's own email, recorded on the row —
    any coach may close any thread, no reason asked); an optional BigQuery
    client (tests pass a fake, same as add_coach_reply).

    Output: a WorkflowResult — OK once the MERGE lands; REFUSED when status
    is not exactly "closed" or thread_id/updated_by is empty, in which case
    no query is ever sent; WRITE_FAILED when the query raises, reported the
    same way a reply write failure is.

    Why MERGE, not INSERT or UPDATE: this table is helpdesk-owned, unlike
    the insert-only private_chat zone, so a second close of the same
    thread must update its one existing row rather than add another — the
    MERGE's matched/not-matched branches do both in one statement.
    assignee and lane never appear in either branch (R2): NULL on a new
    row, untouched on an existing one, since this task builds close only.
    The statement never names private_threads or private_messages, so the
    insert-only code rule (tests/test_private_chat_insert_only.py) keeps
    holding — this table lives in a different dataset entirely.
    """
    if status != "closed" or not thread_id or not updated_by:
        return WorkflowResult.REFUSED

    if client is None:
        from bq_base import client as _default_client
        client = _default_client

    sql = f"""
        MERGE `{config.PRIVATE_THREAD_WORKFLOW_TABLE}` AS target
        USING (SELECT @thread_id AS thread_id) AS source
        ON target.thread_id = source.thread_id
        WHEN MATCHED THEN
            UPDATE SET status = 'closed',
                       closed_at = CURRENT_TIMESTAMP(),
                       updated_at = CURRENT_TIMESTAMP(),
                       updated_by = @updated_by
        WHEN NOT MATCHED THEN
            INSERT (thread_id, status, closed_at, updated_at, updated_by)
            VALUES (@thread_id, 'closed', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP(), @updated_by)
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("thread_id", "STRING", thread_id),
        bigquery.ScalarQueryParameter("updated_by", "STRING", updated_by),
    ])
    try:
        job = client.query(sql, job_config=job_config)
        job.result()
    except Exception as err:
        report_source_failure("workflow write", err)
        return WorkflowResult.WRITE_FAILED
    return WorkflowResult.OK


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


def ticket_group_key(row) -> str:
    """
    Input: one row from the merged Tickets-tab frame (a real ticket or a
    member question). Output: a string key so render_ticket_table can group
    several ticket rows that reply on the same forum thread under one line.

    A member-question row never shares a group with anything else — each
    private-chat thread is already its own row in load_member_questions's
    output — so it always keys on its own content_id. A real ticket keys on
    member_id + thread_id when it has one, else falls back to its own
    content_id too. thread_id can arrive as NaN (a float) once this row has
    passed through merge_into_tickets's pd.concat, which fills a column a
    row's own frame never had — this checks pd.isna rather than `tid or ""`,
    since NaN is truthy and would silently defeat that check (this was
    review finding 1: two threads from one member both keyed as "id|nan"
    and collapsed into one bogus, crashing render group).
    """
    if row.get("source") == "member_question":
        return str(row["content_id"])
    tid = row.get("thread_id")
    if pd.isna(tid) or tid == "":
        return str(row["content_id"])
    return f"{row['member_id']}|{tid}"


def should_include_questions(filter_urgency: str, filter_domain: str, filter_space: str = "All") -> bool:
    """
    Input: the sidebar's urgency, domain and space filter values — space
    defaults to "All" since app.py has no space filter yet. Output: whether
    merge_into_tickets should be handed any member questions at all.

    R3: none of urgency, domain or space narrows a private-chat thread —
    they are ticket-only fields — so once a coach picks anything other than
    "All" for one of them, a question row could only ever be a false
    positive in that filtered list. Deciding this up front, before the
    merge, keeps the "no meaning for a thread" rule in one place instead of
    guessing afterwards which merged rows to drop.
    """
    return filter_urgency == "All" and filter_domain == "All" and filter_space == "All"


def filter_questions_by_status(questions: pd.DataFrame, filter_status: str) -> pd.DataFrame:
    """
    Input: the frame from load_member_questions, and the sidebar's Status
    filter value ("All", "open", "answered", "closed", ...). Output: which
    of those questions merge_into_tickets should even see.

    R4: a closed member question follows the sidebar Status filter the way
    a closed ticket does — shown only when Status is exactly "closed", and
    then only the closed ones; under every other Status, including "All",
    only the non-closed ones show. Runs before merge_into_tickets, the same
    way should_include_questions decides up front whether to pass any
    questions in at all for the urgency/domain/space filters.
    """
    if questions.empty:
        return questions
    if filter_status == "closed":
        return questions[questions["status"] == "closed"]
    return questions[questions["status"] != "closed"]


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


def member_other_threads(questions: pd.DataFrame, member_id, exclude_content_id: str) -> pd.DataFrame:
    """
    Input: the frame from load_member_questions (every member's private
    threads); the member_id whose other threads the Answer dialog wants;
    the content_id of the thread already open, so it doesn't list itself.
    Output: that member's remaining threads, newest activity first — the
    Answer dialog's Member-history panel merges this with the ticket
    history bq_client.get_member_history already returns, the same way
    show_ticket_dialog's own panel does for tickets.

    No new BigQuery read: questions is the frame app.py's load_member_questions
    already fetched (cached) for the Tickets tab itself, so opening the
    Answer dialog costs nothing extra here — it only filters a frame
    already in memory.

    member_id arrives as whatever type the caller's row carries it as
    (BigQuery's INT64 comes back through pandas as a Python int or numpy
    int64, depending on the column's null-ness) — compared as a string on
    both sides so a numpy int64 caller value and a Python int column value
    (or vice versa) still match instead of silently filtering to nothing.
    """
    if questions.empty:
        return questions

    others = questions[
        (questions["member_id"].astype(str) == str(member_id))
        & (questions["content_id"] != exclude_content_id)
    ]
    return others.sort_values("last_activity_at", ascending=False).reset_index(drop=True)
