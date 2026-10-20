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
from bq_base import client, log_event
from bq_base import _tickets_cols
from bq_reads import bulk_close_rows_sql


TEAM_FEEDBACK_TABLE = f"{config.PROJECT_ID}.{config.DATASET}.team_feedback"


def post_comment(content_id: str, author: str, body: str):
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
    """Save the portal login email for a coach so future logins are recognised."""
    e = login_email.replace("'", "\\'")
    sql = f"""
        UPDATE `{config.GRANT_COACHES_TABLE}`
        SET login_email = '{e}'
        WHERE member_id = {member_id}
    """
    client.query(sql).result()


def add_grant_coach(member_id: int, full_name: str, email: str, added_by: str):
    now = datetime.datetime.utcnow().isoformat()
    _name     = full_name.replace("'", "\\'")
    _email    = email.replace("'", "\\'")
    _added_by = added_by.replace("'", "\\'")
    sql = f"""
        INSERT INTO `{config.GRANT_COACHES_TABLE}` (member_id, full_name, email, added_at, added_by)
        VALUES ({member_id}, '{_name}', '{_email}', TIMESTAMP '{now}', '{_added_by}')
    """
    client.query(sql).result()


def remove_grant_coach(member_id: int):
    sql = f"""
        DELETE FROM `{config.GRANT_COACHES_TABLE}`
        WHERE member_id = {member_id}
    """
    client.query(sql).result()


def log_rsvp(content_id: str, event_id: int, member_id: str, rsvped_by: str) -> None:
    """Log an RSVP action to BQ."""
    row = [{
        "id":         str(uuid.uuid4()),
        "content_id": content_id,
        "event_id":   event_id,
        "member_id":  str(member_id),
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
    """Insert a pending follow-up into the followup_queue table."""
    now = datetime.datetime.utcnow()
    send_after = now + datetime.timedelta(days=int(days))
    row = [{
        "id":            str(uuid.uuid4()),
        "ticket_id":     ticket_id,
        "content_id":    content_id,
        "content_type":  content_type,
        "member_id":     str(member_id) if member_id else "",
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
    """Update a followup_queue row. kwargs: sent_at, skipped_at, skipped_reason."""
    sets = [f"status = '{status}'"]
    if "sent_at" in kwargs:
        sets.append(f"sent_at = TIMESTAMP '{kwargs['sent_at']}'")
    if "skipped_at" in kwargs:
        sets.append(f"skipped_at = TIMESTAMP '{kwargs['skipped_at']}'")
    if "skipped_reason" in kwargs:
        reason = (kwargs["skipped_reason"] or "").replace("'", "\\'")
        sets.append(f"skipped_reason = '{reason}'")
    sql = f"""
        UPDATE `{config.FOLLOWUP_QUEUE_TABLE}`
        SET {', '.join(sets)}
        WHERE id = '{followup_id}'
    """
    client.query(sql).result()


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
    Why: the coach's "close these" button. The rows come from
    bq_reads.bulk_close_rows_sql, the same selection preview_bulk_close counts
    (R9); tickets with a pending follow-up are left out (R3). The panel passes
    the gt_cols preview returned, so both build one identical lane expression
    even if the table gained a column between the two button presses.
    SQL analogy: one MERGE into ticket_metadata USING that view, setting
    status='closed' on match and inserting a metadata row otherwise.
    """
    now = datetime.datetime.utcnow().isoformat()
    closed_by_val = (closed_by or "").replace("'", "\\'")
    gt_cols = set(_tickets_cols() if gt_cols is None else gt_cols)

    sql = f"""
        MERGE `{config.META_TABLE}` T
        USING (
            SELECT r.content_id, r.assigned_to, r.domain
            FROM ({bulk_close_rows_sql(status_filter, assigned_to, before_date, lane=lane, gt_cols=gt_cols)}) r
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
            closed_by  = '{closed_by_val}'
        WHEN NOT MATCHED THEN INSERT
            (content_id, status, assigned_to, domain, updated_at, closed_at, closed_by)
        VALUES
            (S.content_id, 'closed', S.assigned_to, S.domain,
             TIMESTAMP '{now}', TIMESTAMP '{now}', '{closed_by_val}')
    """
    job = client.query(sql)
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
    now        = datetime.datetime.utcnow().isoformat()
    domain_val = domain or ""
    reason_val = (feedback_reason or "").replace("'", "\\'")
    closed_by_val = (closed_by or "").replace("'", "\\'")
    # Write closed_at timestamp when closing; clear it when reopening or changing status.
    # CAST(NULL AS ...) is required — bare NULL in a MERGE USING clause has no type in BigQuery.
    closed_at_sql = f"TIMESTAMP '{now}'" if status == "closed" else "CAST(NULL AS TIMESTAMP)"
    closed_by_sql = f"'{closed_by_val}'" if status == "closed" and closed_by_val else "CAST(NULL AS STRING)"
    sql = f"""
        MERGE `{config.META_TABLE}` T
        USING (
            SELECT
                '{content_id}'     AS content_id,
                '{status}'         AS status,
                '{assigned_to}'    AS assigned_to,
                '{domain_val}'     AS domain,
                '{reason_val}'     AS feedback_reason,
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
    client.query(sql).result()
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
    """
    now         = datetime.datetime.utcnow().isoformat()
    lane_val    = (lane or "").replace("'", "\\'")
    reason_val  = (feedback_reason or "").replace("'", "\\'")
    reason_sql  = f"'{reason_val}'" if reason_val else "CAST(NULL AS STRING)"
    sql = f"""
        MERGE `{config.META_TABLE}` T
        USING (
            SELECT
                '{content_id}'     AS content_id,
                '{lane_val}'       AS lane,
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
    client.query(sql).result()


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
    """Update only the assigned_to field on a ticket without touching any other metadata."""
    now = datetime.datetime.utcnow().isoformat()
    sql = f"""
        MERGE `{config.META_TABLE}` T
        USING (
            SELECT
                '{content_id}'    AS content_id,
                '{assigned_to}'   AS assigned_to,
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
    client.query(sql).result()
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

    Uses query parameters (not string interpolation) because bodies are
    multi-line — raw newlines are not allowed inside BQ string literals.
    """
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
    """Hide a standard reply everywhere (soft delete — row is kept)."""
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
    now = datetime.datetime.utcnow().isoformat()
    fid = str(uuid.uuid4())
    safe_title = title.replace("'", "\\'")
    safe_body  = body.replace("'", "\\'")
    sql = f"""
        INSERT INTO `{TEAM_FEEDBACK_TABLE}`
          (feedback_id, submitted_by, feedback_type, title, body, status, created_at)
        VALUES
          ('{fid}', '{submitted_by}', '{feedback_type}',
           '{safe_title}',
           '{safe_body}',
           'open', TIMESTAMP '{now}')
    """
    client.query(sql).result()


def reply_team_feedback(feedback_id: str, reply_text: str, replied_by: str, new_status: str):
    now = datetime.datetime.utcnow().isoformat()
    safe_reply = reply_text.replace("'", "\\'")
    sql = f"""
        UPDATE `{TEAM_FEEDBACK_TABLE}`
        SET
          reply_text = '{safe_reply}',
          replied_by = '{replied_by}',
          replied_at = TIMESTAMP '{now}',
          status     = '{new_status}'
        WHERE feedback_id = '{feedback_id}'
    """
    client.query(sql).result()
