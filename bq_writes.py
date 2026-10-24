"""
BigQuery write functions for the Grant Helpdesk app.

All INSERT / MERGE / UPDATE / DELETE statements live here. Reads live in
bq_reads.py. Mighty Networks HTTP calls live in mn_api.py.
"""

import uuid
import datetime
import traceback

from google.cloud import bigquery

import config
from bq_base import client, log_event, _tickets_cols
from bq_reads import bulk_close_rows_sql


TEAM_FEEDBACK_TABLE = f"{config.PROJECT_ID}.{config.DATASET}.team_feedback"


def _text_or_none(value):
    """
    In: any value a caller hands a writer for a text column.
    Out: the value itself when it is a str, otherwise None (SQL NULL).
    Why: merge_into_tickets fills missing columns with float NaN; bool(nan) is
    True so `v or ""` lets it through, and a float bound as a STRING parameter
    is not legal JSON. None is NULL, so COALESCE(tm.assigned_to,
    gt.assigned_to) falls through to the derived value where "" would shadow it.
    SQL analogy: NULLIF(value, anything-that-is-not-text).
    """
    return value if isinstance(value, str) else None


def _timestamp_text(value):
    """
    In: a timestamp a caller gave as text or a datetime (or a float NaN).
    Out: str(value), or None when the value is a float (NaN has no time).
    Why: update_followup_status binds timestamps as STRING and used str(), which
    turns NaN into the text 'nan'; TIMESTAMP('nan') would fail the whole UPDATE.
    """
    return None if isinstance(value, float) else str(value)


def _integer_or_none(value):
    """
    In: any value a caller hands a writer for an INTEGER column.
    Out: the value, or None when it is a float NaN.
    Why: a bare NaN in the JSON row is a 400 from BigQuery; None is NULL.
    """
    return None if isinstance(value, float) and value != value else value


def _member_id_text(member_id):
    """
    In: a member id (text or number) or a float NaN.
    Out: str(member_id), or "" when it is empty or NaN.
    Why: str(nan) is the text 'nan', and bool(nan) is True so the old
    `if member_id` let it through. "" is what an empty id already became.
    """
    if isinstance(member_id, float) and member_id != member_id:
        return ""
    return str(member_id) if member_id else ""


def post_comment(content_id: str, author: str, body: str):
    """
    In: ids and text for one comment; any may be a float NaN.
    Out: one row inserted into the comments table; a non-text argument is NULL.
    Why: insert_rows_json sanitises nothing, so NaN is coerced before the row exists.
    SQL analogy: INSERT INTO comments VALUES (...) with NULLIF(x, non-text).
    """
    content_id, author, body = map(_text_or_none, (content_id, author, body))
    table = client.get_table(config.COMMENTS_TABLE)
    row = [{
        "comment_id": str(uuid.uuid4()),
        "content_id": content_id,
        "author":     author,
        "body":       body,
        "created_at": datetime.datetime.utcnow().isoformat(),
    }]
    errors = client.insert_rows_json(table, row)
    if errors:
        raise RuntimeError(f"Comment insert failed: {errors}")


def save_mn_api_key(email: str, api_key: str):
    """Upsert a Mighty Networks API key for a user."""
    sql = f"""
        MERGE `{config.TEAM_API_KEYS_TABLE}` T
        USING (SELECT '{email}' AS email, '{api_key}' AS mn_api_key) S
        ON T.email = S.email
        WHEN MATCHED THEN
            UPDATE SET mn_api_key = S.mn_api_key, updated_at = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED THEN
            INSERT (email, mn_api_key, updated_at)
            VALUES (S.email, S.mn_api_key, CURRENT_TIMESTAMP())
    """
    client.query(sql).result()


def link_coach_login_email(member_id: int, login_email: str):
    """
    In: the coach's member id (a number) and the email they log in with.
    Out: nothing; that coach's login_email column is set.
    Why: so future portal logins are recognised. Both values reach BigQuery as
    query parameters (INT64 and STRING), never in the SQL text.
    A value that is not text (a float NaN from the merged frame) is sent as NULL.
    SQL analogy: UPDATE grant_coaches SET login_email = ? WHERE member_id = ?
    """
    login_email = _text_or_none(login_email)
    sql = f"""
        UPDATE `{config.GRANT_COACHES_TABLE}`
        SET login_email = @login_email
        WHERE member_id = @member_id
    """
    params = [
        bigquery.ScalarQueryParameter("login_email", "STRING", login_email),
        bigquery.ScalarQueryParameter("member_id", "INT64", member_id),
    ]
    client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()


def add_grant_coach(member_id: int, full_name: str, email: str, added_by: str):
    """
    In: the new coach's member id (a number), name, email, and who added them.
    Out: nothing; one grant_coaches row is inserted, stamped with the time now.
    Why: lets an admin add a coach. Every value from a person is a query
    parameter (member_id INT64, the rest STRING); only the code-made timestamp
    is written into the SQL.
    A value that is not text (a float NaN from the merged frame) is sent as NULL.
    SQL analogy: INSERT INTO grant_coaches VALUES (?, ?, ?, now, ?)
    """
    full_name, email, added_by = map(_text_or_none, (full_name, email, added_by))
    now = datetime.datetime.utcnow().isoformat()
    sql = f"""
        INSERT INTO `{config.GRANT_COACHES_TABLE}` (member_id, full_name, email, added_at, added_by)
        VALUES (@member_id, @full_name, @email, TIMESTAMP '{now}', @added_by)
    """
    params = [
        bigquery.ScalarQueryParameter("member_id", "INT64", member_id),
        bigquery.ScalarQueryParameter("full_name", "STRING", full_name),
        bigquery.ScalarQueryParameter("email", "STRING", email),
        bigquery.ScalarQueryParameter("added_by", "STRING", added_by),
    ]
    client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()


def remove_grant_coach(member_id: int):
    sql = f"""
        DELETE FROM `{config.GRANT_COACHES_TABLE}`
        WHERE member_id = {member_id}
    """
    client.query(sql).result()


def log_rsvp(content_id: str, event_id: int, member_id: str, rsvped_by: str) -> None:
    """
    In: content id, event id, member id, who RSVPed; any may be a float NaN.
    Out: one row in rsvp_log; NaN text becomes NULL (rsvped_by: ""), NaN member_id "".
    Why: see post_comment. SQL analogy: INSERT INTO rsvp_log VALUES (...).
    """
    content_id = _text_or_none(content_id)
    event_id = _integer_or_none(event_id)
    rsvped_by = _text_or_none(rsvped_by)
    row = [{
        "id":         str(uuid.uuid4()),
        "content_id": content_id,
        "event_id":   event_id,
        "member_id":  _member_id_text(member_id),
        "rsvped_by":  rsvped_by or "",
        "rsvped_at":  datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }]
    errors = client.insert_rows_json(f"{config.PROJECT_ID}.grant_helpdesk.rsvp_log", row)
    if errors:
        raise RuntimeError(f"BQ log error: {errors}")


def queue_followup(
    ticket_id: str,
    content_id: str,
    content_type: str,
    member_id: str,
    member_name: str,
    message: str,
    days: int,
    scheduled_by: str,
) -> None:
    """
    In: the follow-up's ids, text, delay in days and who scheduled it; text
    arguments may be a float NaN (days must be a real number).
    Out: one pending row in followup_queue; NaN text becomes NULL
    (member_name: "", member_id: "").
    Why: see post_comment. SQL analogy: INSERT INTO followup_queue VALUES (...).
    """
    ticket_id, content_id, content_type, message, scheduled_by = map(
        _text_or_none, (ticket_id, content_id, content_type, message, scheduled_by))
    member_name = _text_or_none(member_name)
    now = datetime.datetime.utcnow()
    send_after = now + datetime.timedelta(days=int(days))
    row = [{
        "id":            str(uuid.uuid4()),
        "ticket_id":     ticket_id,
        "content_id":    content_id,
        "content_type":  content_type,
        "member_id":     _member_id_text(member_id),
        "member_name":   member_name or "",
        "message":       message,
        "send_after":    send_after.isoformat(),
        "status":        "pending",
        "scheduled_by":  scheduled_by,
        "created_at":    now.isoformat(),
    }]
    errors = client.insert_rows_json(config.FOLLOWUP_QUEUE_TABLE, row)
    if errors:
        raise RuntimeError(f"BQ insert errors: {errors}")


def update_followup_status(followup_id: str, status: str, **kwargs) -> None:
    """
    In: a followup_queue row id, its new status, and optionally sent_at,
    skipped_at (timestamps as text) and skipped_reason.
    Out: nothing; that row's status, and only the extra columns given, change.
    Why: the follow-up sender and the coach's "skip" button. Every value is a
    STRING query parameter; the timestamps are cast in the SQL with
    TIMESTAMP(@x), so the parameter itself stays a STRING.
    A value that is not text (a float NaN from the merged frame) is sent as NULL.
    SQL analogy: UPDATE followup_queue SET status = ?, [sent_at = ?, ...] WHERE id = ?
    """
    followup_id, status = _text_or_none(followup_id), _text_or_none(status)
    sets = ["status = @status"]
    params = [
        bigquery.ScalarQueryParameter("status", "STRING", status),
        bigquery.ScalarQueryParameter("followup_id", "STRING", followup_id),
    ]
    if "sent_at" in kwargs:
        sets.append("sent_at = TIMESTAMP(@sent_at)")
        params.append(bigquery.ScalarQueryParameter("sent_at", "STRING", _timestamp_text(kwargs["sent_at"])))
    if "skipped_at" in kwargs:
        sets.append("skipped_at = TIMESTAMP(@skipped_at)")
        params.append(bigquery.ScalarQueryParameter("skipped_at", "STRING", _timestamp_text(kwargs["skipped_at"])))
    if "skipped_reason" in kwargs:
        sets.append("skipped_reason = @skipped_reason")
        params.append(bigquery.ScalarQueryParameter(
            "skipped_reason", "STRING", _text_or_none(kwargs["skipped_reason"]) or ""))
    sql = f"""
        UPDATE `{config.FOLLOWUP_QUEUE_TABLE}`
        SET {', '.join(sets)}
        WHERE id = @followup_id
    """
    client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()


def execute_bulk_close(
    status_filter: str = "answered",
    assigned_to: str = "",
    before_date: str = "",
    closed_by: str = "",
    *,
    lane: str,
    gt_cols=None,
) -> int:
    """
    In: the three bulk-close filters, the closing coach's email, the one lane
    to sweep (R11, no default) and gt_cols, the grant_tickets columns the
    preview was built with (None = look them up now).
    Out: the number of tickets closed (rows the MERGE affected, R6).
    Every value that came from a person (the four filters and closed_by, the
    audit field) reaches BigQuery as a query parameter, never in the SQL text (R10).
    Why: the coach's "close these" button. The rows come from
    bq_reads.bulk_close_rows_sql, the same selection preview_bulk_close counts
    (R9); tickets with a pending follow-up are left out (R3). The panel passes
    the gt_cols preview returned, so both build one identical lane expression
    even if the table gained a column between the two button presses.
    SQL analogy: one MERGE into ticket_metadata USING that view, setting
    status='closed' on match and inserting a metadata row otherwise.
    """
    now = datetime.datetime.utcnow().isoformat()
    gt_cols = set(_tickets_cols() if gt_cols is None else gt_cols)
    selection_sql, params = bulk_close_rows_sql(
        status_filter, assigned_to, before_date, lane=lane, gt_cols=gt_cols)
    params = params + [bigquery.ScalarQueryParameter("closed_by", "STRING", closed_by or "")]

    sql = f"""
        MERGE `{config.META_TABLE}` T
        USING (
            SELECT r.content_id, r.assigned_to, r.domain
            FROM ({selection_sql}) r
            WHERE r.content_id NOT IN (
                SELECT DISTINCT ticket_id
                FROM `{config.FOLLOWUP_QUEUE_TABLE}`
                WHERE status = 'pending'
            )
        ) S
        ON T.content_id = S.content_id
        WHEN MATCHED THEN UPDATE SET
            status     = 'closed',
            updated_at = TIMESTAMP '{now}',
            closed_at  = TIMESTAMP '{now}',
            closed_by  = @closed_by
        WHEN NOT MATCHED THEN INSERT
            (content_id, status, assigned_to, domain, updated_at, closed_at, closed_by)
        VALUES
            (S.content_id, 'closed', S.assigned_to, S.domain,
             TIMESTAMP '{now}', TIMESTAMP '{now}', @closed_by)
    """
    job = client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params))
    job.result()
    return job.num_dml_affected_rows or 0


def update_ticket_meta(
    content_id: str,
    status: str,
    assigned_to: str,
    domain: str = None,
    feedback_reason: str = None,
    closed_by: str = None,
):
    """
    In: one ticket's id, its new status and assignee, and optionally the domain,
    a classifier feedback reason and (when closing) who closed it.
    Out: nothing; one row of ticket_metadata is updated or inserted, and the
    assignment refresh is poked when there is an assignee.
    Why: the coach's "set status / assign" action. Every value from a person
    (id, status, assignee, domain, reason, closer) reaches BigQuery as a named
    STRING query parameter, never in the SQL text, so a quote or a trailing
    backslash cannot change the statement. Only values the code makes itself
    (the timestamp, the typed NULLs) are written into the SQL. A value that is not text (a float NaN from the merged frame) is sent as NULL.
    SQL analogy: MERGE ticket_metadata USING one literal row ON content_id,
    update on match, insert otherwise.
    """
    content_id, status, assigned_to, domain, feedback_reason, closed_by = map(
        _text_or_none, (content_id, status, assigned_to, domain, feedback_reason, closed_by))
    now        = datetime.datetime.utcnow().isoformat()
    params = [
        bigquery.ScalarQueryParameter("content_id", "STRING", content_id),
        bigquery.ScalarQueryParameter("status", "STRING", status),
        bigquery.ScalarQueryParameter("assigned_to", "STRING", assigned_to),
        bigquery.ScalarQueryParameter("domain", "STRING", domain or ""),
        bigquery.ScalarQueryParameter("feedback_reason", "STRING", feedback_reason or ""),
    ]
    # Write closed_at timestamp when closing; clear it when reopening or changing status.
    # CAST(NULL AS ...) is required — bare NULL in a MERGE USING clause has no type in BigQuery.
    closed_at_sql = f"TIMESTAMP '{now}'" if status == "closed" else "CAST(NULL AS TIMESTAMP)"
    if status == "closed" and closed_by:
        params.append(bigquery.ScalarQueryParameter("closed_by", "STRING", closed_by))
        closed_by_sql = "@closed_by"
    else:
        closed_by_sql = "CAST(NULL AS STRING)"
    sql = f"""
        MERGE `{config.META_TABLE}` T
        USING (
            SELECT
                @content_id        AS content_id,
                @status            AS status,
                @assigned_to       AS assigned_to,
                @domain            AS domain,
                @feedback_reason   AS feedback_reason,
                TIMESTAMP '{now}'  AS updated_at,
                {closed_at_sql}    AS closed_at,
                {closed_by_sql}    AS closed_by
        ) S
        ON T.content_id = S.content_id
        WHEN MATCHED THEN UPDATE SET
            status          = S.status,
            assigned_to     = S.assigned_to,
            domain          = S.domain,
            -- Keep any reason already on the row when this call does not carry one.
            -- A reason is classifier feedback and lives as long as the lane does;
            -- closing a ticket must not quietly blank it.
            feedback_reason = COALESCE(NULLIF(S.feedback_reason, ''), T.feedback_reason),
            updated_at      = S.updated_at,
            closed_at       = S.closed_at,
            closed_by       = S.closed_by
        WHEN NOT MATCHED THEN INSERT
            (content_id, status, assigned_to, domain, feedback_reason, updated_at, closed_at, closed_by)
        VALUES
            (S.content_id, S.status, S.assigned_to, S.domain, NULLIF(S.feedback_reason, ''), S.updated_at, S.closed_at, S.closed_by)
    """
    client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()
    if assigned_to:
        trigger_assignment_refresh()


def set_ticket_lane(content_id: str, lane: str, feedback_reason: str = None):
    """
    Move one piece of content between the Tickets lane ('question') and the
    Conversations lane ('general').

    Deliberately touches lane, feedback_reason and updated_at ONLY. It is not a
    variant of update_ticket_meta: writing status here is exactly the bug the
    lane column was added to fix — a coach closing a conversation would overwrite
    the "this was never a question" verdict and the classifier would lose the
    lesson. Lane and lifecycle are now independent, and so are their writers.

    A row that does not exist yet is inserted with a NULL status, which
    grant_tickets reads as "no manual override" and resolves from the lane.

    In: the content id, the lane, and an optional feedback reason.
    Out: nothing; one ticket_metadata row is updated or inserted.
    Id, lane and reason reach BigQuery as named STRING query parameters, never
    in the SQL text. With no reason the typed NULL stays in the SQL (it is not
    a caller value) and no reason parameter is sent. A value that is not text (a float NaN from the merged frame) is sent as NULL.
    """
    content_id, lane, feedback_reason = map(_text_or_none, (content_id, lane, feedback_reason))
    now         = datetime.datetime.utcnow().isoformat()
    params = [
        bigquery.ScalarQueryParameter("content_id", "STRING", content_id),
        bigquery.ScalarQueryParameter("lane", "STRING", lane or ""),
    ]
    if feedback_reason:
        params.append(bigquery.ScalarQueryParameter("feedback_reason", "STRING", feedback_reason))
        reason_sql = "@feedback_reason"
    else:
        reason_sql = "CAST(NULL AS STRING)"
    sql = f"""
        MERGE `{config.META_TABLE}` T
        USING (
            SELECT
                @content_id        AS content_id,
                @lane              AS lane,
                {reason_sql}       AS feedback_reason,
                TIMESTAMP '{now}'  AS updated_at
        ) S
        ON T.content_id = S.content_id
        WHEN MATCHED THEN UPDATE SET
            lane            = S.lane,
            feedback_reason = COALESCE(S.feedback_reason, T.feedback_reason),
            updated_at      = S.updated_at
        WHEN NOT MATCHED THEN INSERT
            (content_id, lane, feedback_reason, updated_at)
        VALUES
            (S.content_id, S.lane, S.feedback_reason, S.updated_at)
    """
    client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()


def trigger_assignment_refresh():
    """
    Fire a Dataform workflow invocation to rebuild grant_member_assignments
    and grant_tickets after an assignment changes. Fire-and-forget — Dataform
    runs the rebuild asynchronously. Errors are swallowed so the save flow is
    never broken.
    """
    try:
        from google.cloud import dataform_v1beta1

        df_client = dataform_v1beta1.DataformClient()
        repo = (
            f"projects/{config.PROJECT_ID}"
            f"/locations/{config.DATAFORM_REGION}"
            f"/repositories/{config.DATAFORM_REPOSITORY}"
        )

        cr = df_client.create_compilation_result(
            parent=repo,
            compilation_result=dataform_v1beta1.CompilationResult(
                git_commitish="main",
                code_compilation_config=dataform_v1beta1.CodeCompilationConfig(
                    default_database=config.PROJECT_ID,
                    default_schema=config.DATASET,
                    default_location="EU",
                ),
            ),
        )

        invocation = dataform_v1beta1.WorkflowInvocation(
            compilation_result=cr.name,
            invocation_config=dataform_v1beta1.InvocationConfig(
                included_targets=[
                    dataform_v1beta1.Target(
                        database=config.PROJECT_ID,
                        schema=config.DATASET,
                        name="grant_member_assignments",
                    ),
                    dataform_v1beta1.Target(
                        database=config.PROJECT_ID,
                        schema=config.DATASET,
                        name="grant_tickets",
                    ),
                ],
                # Don't re-run upstream sources — ticket_metadata was just
                # written by the app and grant_content is already materialized.
                transitive_dependencies_included=False,
                transitive_dependents_included=False,
            ),
        )
        df_client.create_workflow_invocation(
            parent=repo, workflow_invocation=invocation
        )
    except Exception as e:
        log_event(
            level="ERROR",
            source="trigger_assignment_refresh",
            message=str(e),
            detail=traceback.format_exc(),
        )


def set_ticket_assignee(content_id: str, assigned_to: str):
    """
    In: a ticket's content_id and the coach name to assign it to ("" unassigns).
    Out: nothing; that ticket's assigned_to and updated_at are set in the
    metadata table (row created if missing), then the assignment refresh runs.
    Why: lets a coach hand a ticket over without touching any other metadata.
    Both values are query parameters (STRING), never pasted into the SQL, so a
    name like O'Brien cannot end the SQL string early. Only the code-made
    timestamp is written into the SQL. "" stays "" (unassigned); a value that is
    not text (a float NaN from the merged frame) is sent as NULL.
    SQL analogy: INSERT ... ON DUPLICATE KEY UPDATE assigned_to = ? (an upsert).
    """
    assigned_to = _text_or_none(assigned_to)
    now = datetime.datetime.utcnow().isoformat()
    sql = f"""
        MERGE `{config.META_TABLE}` T
        USING (
            SELECT
                @content_id       AS content_id,
                @assigned_to      AS assigned_to,
                TIMESTAMP '{now}' AS updated_at
        ) S
        ON T.content_id = S.content_id
        WHEN MATCHED THEN UPDATE SET
            assigned_to = S.assigned_to,
            updated_at  = S.updated_at
        WHEN NOT MATCHED THEN INSERT
            (content_id, assigned_to, updated_at)
        VALUES
            (S.content_id, S.assigned_to, S.updated_at)
    """
    params = [
        bigquery.ScalarQueryParameter("content_id", "STRING", content_id),
        bigquery.ScalarQueryParameter("assigned_to", "STRING", assigned_to),
    ]
    client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()
    trigger_assignment_refresh()


def set_member_assignment_override(member_id: int, assigned_to: str, updated_by: str):
    now = datetime.datetime.utcnow().isoformat()
    sql = f"""
        MERGE `{config.MEMBER_ASSIGNMENTS_TABLE}` T
        USING (
            SELECT
                {member_id}        AS member_id,
                '{assigned_to}'    AS assigned_to,
                TIMESTAMP '{now}'  AS updated_at,
                '{updated_by}'     AS updated_by
        ) S
        ON T.member_id = S.member_id
        WHEN MATCHED THEN UPDATE SET
            assigned_to = S.assigned_to,
            updated_at  = S.updated_at,
            updated_by  = S.updated_by
        WHEN NOT MATCHED THEN INSERT
            (member_id, assigned_to, updated_at, updated_by)
        VALUES
            (S.member_id, S.assigned_to, S.updated_at, S.updated_by)
    """
    client.query(sql).result()
    trigger_assignment_refresh()


def save_standard_reply(reply_id, title: str, body: str, saved_by: str) -> str:
    """Insert (reply_id=None) or update a standard reply. Returns the reply_id.

    In: the reply id (None = new), title, body and who saved it.
    Out: the reply's id (a new uuid when inserting).
    A value that is not text, a float NaN included, is sent as NULL; a NaN
    reply_id therefore inserts a new reply, like None.

    Uses query parameters (not string interpolation) because bodies are
    multi-line — raw newlines are not allowed inside BQ string literals.
    """
    reply_id, title, body, saved_by = map(_text_or_none, (reply_id, title, body, saved_by))
    params = [
        bigquery.ScalarQueryParameter("title", "STRING", title),
        bigquery.ScalarQueryParameter("body", "STRING", body),
        bigquery.ScalarQueryParameter("user", "STRING", saved_by),
    ]
    if reply_id is None:
        reply_id = str(uuid.uuid4())
        sql = f"""
            INSERT INTO `{config.STANDARD_REPLIES_TABLE}`
              (reply_id, title, body, is_active, created_by, created_at)
            VALUES (@reply_id, @title, @body, TRUE, @user, CURRENT_TIMESTAMP())
        """
    else:
        sql = f"""
            UPDATE `{config.STANDARD_REPLIES_TABLE}`
            SET title = @title, body = @body,
                updated_by = @user, updated_at = CURRENT_TIMESTAMP()
            WHERE reply_id = @reply_id
        """
    params.append(bigquery.ScalarQueryParameter("reply_id", "STRING", reply_id))
    job_config = bigquery.QueryJobConfig(query_parameters=params)
    client.query(sql, job_config=job_config).result()
    return reply_id


def archive_standard_reply(reply_id: str) -> None:
    """
    In: a standard reply's id.
    Out: nothing; that row's is_active is set to FALSE and updated_at to now.
    Why: hides the reply everywhere but keeps the row (soft delete). A non-text
    id (float NaN) is sent as NULL and matches no row.
    SQL analogy: UPDATE standard_replies SET is_active = FALSE WHERE reply_id = ?
    """
    reply_id = _text_or_none(reply_id)
    sql = f"""
        UPDATE `{config.STANDARD_REPLIES_TABLE}`
        SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP()
        WHERE reply_id = @reply_id
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("reply_id", "STRING", reply_id),
    ])
    client.query(sql, job_config=job_config).result()


def submit_team_feedback(submitted_by: str, feedback_type: str, title: str, body: str):
    """
    In: who sent the feedback, its type, a title and a body.
    Out: nothing; one team_feedback row is inserted with status 'open' and a
    new id, stamped with the time now.
    Why: the coaches' feedback form. Every value from a person (and the new
    id) is a STRING query parameter, never in the SQL text; only the constant
    'open' and the code-made timestamp are written into the SQL. A value that is not text (a float NaN from the merged frame) is sent as NULL.
    SQL analogy: INSERT INTO team_feedback VALUES (?, ?, ?, ?, ?, 'open', now)
    """
    submitted_by, feedback_type, title, body = map(
        _text_or_none, (submitted_by, feedback_type, title, body))
    now = datetime.datetime.utcnow().isoformat()
    sql = f"""
        INSERT INTO `{TEAM_FEEDBACK_TABLE}`
          (feedback_id, submitted_by, feedback_type, title, body, status, created_at)
        VALUES
          (@feedback_id, @submitted_by, @feedback_type, @title, @body,
           'open', TIMESTAMP '{now}')
    """
    params = [
        bigquery.ScalarQueryParameter("feedback_id", "STRING", str(uuid.uuid4())),
        bigquery.ScalarQueryParameter("submitted_by", "STRING", submitted_by),
        bigquery.ScalarQueryParameter("feedback_type", "STRING", feedback_type),
        bigquery.ScalarQueryParameter("title", "STRING", title),
        bigquery.ScalarQueryParameter("body", "STRING", body),
    ]
    client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()


def reply_team_feedback(feedback_id: str, reply_text: str, replied_by: str, new_status: str):
    """
    In: the feedback row id, the reply text, who replied and the new status.
    Out: nothing; that row gets the reply, the replier, the time now and the status.
    Why: an admin answers a piece of team feedback. All four values are STRING
    query parameters (the new status is bound as `status`, the column it
    fills); only the code-made timestamp is written into the SQL. A value that is not text (a float NaN from the merged frame) is sent as NULL.
    SQL analogy: UPDATE team_feedback SET reply_text = ?, ... WHERE feedback_id = ?
    """
    feedback_id, reply_text, replied_by, new_status = map(
        _text_or_none, (feedback_id, reply_text, replied_by, new_status))
    now = datetime.datetime.utcnow().isoformat()
    sql = f"""
        UPDATE `{TEAM_FEEDBACK_TABLE}`
        SET
          reply_text = @reply_text,
          replied_by = @replied_by,
          replied_at = TIMESTAMP '{now}',
          status     = @status
        WHERE feedback_id = @feedback_id
    """
    params = [
        bigquery.ScalarQueryParameter("reply_text", "STRING", reply_text),
        bigquery.ScalarQueryParameter("replied_by", "STRING", replied_by),
        bigquery.ScalarQueryParameter("status", "STRING", new_status),
        bigquery.ScalarQueryParameter("feedback_id", "STRING", feedback_id),
    ]
    client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()
