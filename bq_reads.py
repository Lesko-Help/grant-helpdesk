"""
BigQuery read functions for the Grant Helpdesk app.

All SELECT-only queries live here. Writes (INSERT/MERGE/UPDATE/DELETE) live in
bq_writes.py. Mighty Networks HTTP calls live in mn_api.py.
"""

import pandas as pd
from google.cloud import bigquery

import config
from bq_base import (
    client,
    log_event,
    _tickets_cols,
    _query_with_schema_retry,
)

# Open = NOT terminal. The Open KPI (get_open_stats) and the default Open ticket
# list (get_tickets) both use this same predicate so the two never diverge.
_TERMINAL_IN = "(" + ", ".join(f"'{s}'" for s in config.TERMINAL_STATUSES) + ")"


def _live_status_cte() -> str:
    """
    Returns the reopen_clause string for building the live-join CTE status CASE.
    Used by both get_open_stats() and get_daily_stats() so their KPI numbers
    always match the ticket list (which also uses a live join).
    """
    _gt_cols = _tickets_cols()
    return (
        "WHEN tm.status = 'closed' AND gt.last_member_activity_at IS NOT NULL "
        "AND tm.closed_at IS NOT NULL AND gt.last_member_activity_at > tm.closed_at THEN 'open'"
    ) if "last_member_activity_at" in _gt_cols else ""


def _urgency_clock_expr(gt_cols=None) -> str:
    """
    Returns the SQL expression for urgency_since: the one timestamp a
    ticket's waiting time is counted from (R5-R8 in bq_reads.md). When the
    ticket was closed and the member's last activity came later than the
    close, the clock is that activity — the comment that reopened it (R5).
    Otherwise the clock is created_at, as it has always been (R6).

    Deliberately does not test tm.status, unlike _live_status_cte()'s reopen
    clause (R7): a coach marking a reopened ticket "answered" must not snap
    the clock (and so the badge) back to created_at.

    Guarded the same way as _live_status_cte(): when grant_tickets has no
    last_member_activity_at column yet (an old Dataform compilation), this
    returns plain gt.created_at everywhere, matching today's behaviour.
    """
    gt_cols = _tickets_cols() if gt_cols is None else gt_cols
    if "last_member_activity_at" not in gt_cols:
        return "gt.created_at"
    return (
        "CASE WHEN tm.closed_at IS NOT NULL AND gt.last_member_activity_at IS NOT NULL "
        "AND gt.last_member_activity_at > tm.closed_at "
        "THEN gt.last_member_activity_at ELSE gt.created_at END"
    )


def _live_lane_expr(gt_cols=None) -> str:
    """
    The lane a row is in RIGHT NOW, reading ticket_metadata live rather than
    waiting for the nightly Dataform rebuild. This is what makes "Not a question"
    move a row out of Tickets and into Conversations on the very next rerun.

    Same precedence as grant_tickets.sqlx: a coach's override beats the table.
    The `gt.lane` fallback is guarded because the column only exists once the
    Dataform change has run — before that every row reads as a question, which
    is exactly today's behaviour.
    """
    gt_cols = _tickets_cols() if gt_cols is None else gt_cols
    _base   = "gt.lane" if "lane" in gt_cols else f"'{config.LANE_QUESTION}'"
    return (
        "CASE WHEN tm.lane IS NOT NULL AND tm.lane != '' THEN tm.lane "
        f"ELSE {_base} END"
    )


def get_unreviewed_rejects(days: int = 1) -> pd.DataFrame:
    """Posts/articles/comments the classifier rejected and the team hasn't reviewed yet."""
    sql = f"""
        SELECT *
        FROM `{config.TICKETS_TABLE}`
        WHERE lane = '{config.LANE_GENERAL}'
          AND manual_status IS NULL
          AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {int(days)} DAY)
        QUALIFY ROW_NUMBER() OVER (PARTITION BY content_id ORDER BY created_at DESC) = 1
        ORDER BY created_at DESC
    """
    return client.query(sql).to_dataframe()


def get_team_members() -> list[str]:
    sql = f"""
        SELECT full_name
        FROM `{config.GRANT_COACHES_TABLE}`
        ORDER BY full_name
    """
    rows = client.query(sql).to_dataframe()
    return rows["full_name"].tolist()


def get_tickets(
    status=None,
    date_from=None,
    date_to=None,
    assignee=None,
    member_id=None,
    urgency=None,

    domain=None,
    lane=config.LANE_QUESTION,
) -> pd.DataFrame:
    """
    One lane at a time. lane='question' feeds the Tickets tab, lane='general'
    feeds Conversations; pass lane=None only if you genuinely want both.
    """
    filters = ["body IS NOT NULL AND TRIM(body) != ''"]

    if lane:
        filters.append(f"lane = '{lane}'")

    if status and status != "All":
        if status == "open":
            # "Open" = every live (non-terminal) ticket, matching the Open KPI in
            # get_open_stats. Other statuses stay exact-match.
            filters.append(f"ticket_status NOT IN {_TERMINAL_IN}")
        else:
            filters.append(f"ticket_status = '{status}'")
    else:
        # Default view = live work. Closed is hidden, and so is archived (the
        # pre-go-live general backlog). Cancelled stays visible, exactly as it
        # was before the lane split — the lane predicate above is now what
        # removes the rejected content, not a status exclusion.
        filters.append("ticket_status NOT IN ('closed', 'archived')")
    if assignee and assignee != "All":
        filters.append(f"assigned_to = '{assignee}'")
    if member_id:
        filters.append(f"CAST(member_id AS STRING) = '{member_id}'")

    if domain and domain != "All":
        filters.append(f"domain = '{domain}'")
    if date_from:
        filters.append(f"DATE(created_at) >= '{date_from}'")
    if date_to:
        filters.append(f"DATE(created_at) <= '{date_to}'")

    # Urgency maps to age conditions on urgency_since (R12) — a column
    # selected inside the `live` CTE below, not created_at: this filter and
    # the badge CASE both run outside that CTE, where tm (and so the R5/R6
    # clock) is no longer visible, and BigQuery cannot filter on a SELECT
    # alias from the same query level.
    urgency_conditions = {
        "Normal":   "TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), urgency_since, HOUR) < 24",
        "Urgent":   "TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), urgency_since, HOUR) BETWEEN 24 AND 47",
        "Critical": "TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), urgency_since, HOUR) >= 48",
    }
    if urgency and urgency != "All" and urgency in urgency_conditions:
        filters.append(urgency_conditions[urgency])

    where = ("WHERE " + " AND ".join(filters)) if filters else ""

    def _build():
        # Build EXCEPT and CASE clauses based on what columns actually exist in
        # the table. Run inside _query_with_schema_retry so a mid-Dataform-
        # rebuild schema mismatch refreshes _tickets_cols() and tries again.
        _gt_cols = _tickets_cols()
        _always_except = ["assigned_to", "manual_status", "domain", "ticket_status"]
        _optional_except = ["difficulty", "team_comment_replied", "lane"]
        _except_cols = ", ".join(_always_except + [c for c in _optional_except if c in _gt_cols])
        _reopen_clause = (
            "WHEN tm.status = 'closed' AND gt.last_member_activity_at IS NOT NULL "
            "AND tm.closed_at IS NOT NULL AND gt.last_member_activity_at > tm.closed_at THEN 'open'"
        ) if "last_member_activity_at" in _gt_cols else ""
        _lane_expr = _live_lane_expr(_gt_cols)
        _urgency_expr = _urgency_clock_expr(_gt_cols)
        return f"""
            WITH live AS (
                SELECT
                    gt.* EXCEPT({_except_cols}),
                    COALESCE(tm.assigned_to, gt.assigned_to)               AS assigned_to,
                    tm.status                                               AS manual_status,
                    COALESCE(tm.domain, gt.domain)                          AS domain,
                    {_lane_expr}                                            AS lane,
                    CASE
                        {_reopen_clause}
                        WHEN tm.status IS NOT NULL AND tm.status != ''      THEN tm.status
                        ELSE gt.ticket_status
                    END                                                     AS ticket_status,
                    {_urgency_expr}                                         AS urgency_since
                FROM `{config.TICKETS_TABLE}` gt
                LEFT JOIN (
                    SELECT * FROM `{config.META_TABLE}`
                    QUALIFY ROW_NUMBER() OVER (PARTITION BY content_id ORDER BY updated_at DESC) = 1
                ) tm ON gt.content_id = tm.content_id
                QUALIFY ROW_NUMBER() OVER (PARTITION BY gt.content_id ORDER BY gt.created_at DESC) = 1
            )
            SELECT
                *,
                LEFT(body, 600) AS body_preview,
                CASE
                    WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), urgency_since, HOUR) < 24 THEN 'normal'
                    WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), urgency_since, HOUR) < 48 THEN 'urgent'
                    ELSE 'critical'
                END AS urgency
            FROM live
            {where}
            ORDER BY created_at DESC
        """
    df = _query_with_schema_retry(_build)
    if "domain" not in df.columns:
        df["domain"] = None
    return df


def get_ticket_detail(content_id: str) -> dict:
    def _build():
        _gt_cols = _tickets_cols()
        _always_except = ["assigned_to", "manual_status", "domain", "ticket_status"]
        _optional_except = ["difficulty", "team_comment_replied", "lane"]
        _except_cols = ", ".join(_always_except + [c for c in _optional_except if c in _gt_cols])
        _reopen_clause = (
            "WHEN tm.status = 'closed' AND gt.last_member_activity_at IS NOT NULL "
            "AND tm.closed_at IS NOT NULL AND gt.last_member_activity_at > tm.closed_at THEN 'open'"
        ) if "last_member_activity_at" in _gt_cols else ""
        _lane_expr = _live_lane_expr(_gt_cols)
        _urgency_expr = _urgency_clock_expr(_gt_cols)
        return f"""
            SELECT
                gt.* EXCEPT({_except_cols}),
                COALESCE(tm.assigned_to, gt.assigned_to)               AS assigned_to,
                tm.status                                               AS manual_status,
                COALESCE(tm.domain, gt.domain)                          AS domain,
                {_lane_expr}                                            AS lane,
                CASE
                    {_reopen_clause}
                    WHEN tm.status IS NOT NULL AND tm.status != ''      THEN tm.status
                    ELSE gt.ticket_status
                END                                                     AS ticket_status,
                CASE
                    WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), {_urgency_expr}, HOUR) < 24 THEN 'normal'
                    WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), {_urgency_expr}, HOUR) < 48 THEN 'urgent'
                    ELSE 'critical'
                END AS urgency
            FROM `{config.TICKETS_TABLE}` gt
            LEFT JOIN (
                SELECT * FROM `{config.META_TABLE}`
                QUALIFY ROW_NUMBER() OVER (PARTITION BY content_id ORDER BY updated_at DESC) = 1
            ) tm ON gt.content_id = tm.content_id
            WHERE gt.content_id = '{content_id}'
            LIMIT 1
        """
    df = _query_with_schema_retry(_build)
    if df.empty:
        return {}
    return df.iloc[0].to_dict()


def get_member_thread_tickets(thread_id: str, member_id) -> pd.DataFrame:
    """All tickets from one member in one thread (all statuses), used by the group dialog."""
    def _build():
        _gt_cols = _tickets_cols()
        _always_except = ["assigned_to", "manual_status", "domain", "ticket_status"]
        _optional_except = ["difficulty", "team_comment_replied", "lane"]
        _except_cols = ", ".join(_always_except + [c for c in _optional_except if c in _gt_cols])
        _reopen_clause = (
            "WHEN tm.status = 'closed' AND gt.last_member_activity_at IS NOT NULL "
            "AND tm.closed_at IS NOT NULL AND gt.last_member_activity_at > tm.closed_at THEN 'open'"
        ) if "last_member_activity_at" in _gt_cols else ""
        _lane_expr = _live_lane_expr(_gt_cols)
        _urgency_expr = _urgency_clock_expr(_gt_cols)
        return f"""
            WITH live AS (
                SELECT
                    gt.* EXCEPT({_except_cols}),
                    COALESCE(tm.assigned_to, gt.assigned_to)               AS assigned_to,
                    tm.status                                               AS manual_status,
                    COALESCE(tm.domain, gt.domain)                         AS domain,
                    {_lane_expr}                                           AS lane,
                    CASE
                        {_reopen_clause}
                        WHEN tm.status IS NOT NULL AND tm.status != ''     THEN tm.status
                        ELSE gt.ticket_status
                    END                                                    AS ticket_status,
                    CASE
                        WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), {_urgency_expr}, HOUR) < 24 THEN 'normal'
                        WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), {_urgency_expr}, HOUR) < 48 THEN 'urgent'
                        ELSE 'critical'
                    END AS urgency
                FROM `{config.TICKETS_TABLE}` gt
                LEFT JOIN (
                    SELECT * FROM `{config.META_TABLE}`
                    QUALIFY ROW_NUMBER() OVER (PARTITION BY content_id ORDER BY updated_at DESC) = 1
                ) tm ON gt.content_id = tm.content_id
                WHERE gt.thread_id = '{thread_id}'
                  AND CAST(gt.member_id AS STRING) = '{member_id}'
                QUALIFY ROW_NUMBER() OVER (PARTITION BY gt.content_id ORDER BY gt.created_at DESC) = 1
            )
            SELECT *, LEFT(body, 300) AS body_preview
            FROM live
            ORDER BY created_at ASC
        """
    df = _query_with_schema_retry(_build)
    if "domain" not in df.columns:
        df["domain"] = None
    return df


def get_comments(content_id: str) -> pd.DataFrame:
    sql = f"""
        SELECT comment_id, author, body, created_at
        FROM `{config.COMMENTS_VIEW}`
        WHERE content_id = '{content_id}'
        ORDER BY created_at ASC
    """
    return client.query(sql).to_dataframe()


def get_space_names() -> dict:
    """Return {space_id: space_name} from the space_names lookup table.

    Populated monthly by jobs/sync_spaces.py. Callers wrap this in a cached
    loader (app.load_space_names) so it's queried at most once per TTL. Returns
    {} if the table is empty/missing so labelling degrades gracefully.
    """
    try:
        df = client.query(
            f"SELECT space_id, space_name FROM `{config.SPACE_NAMES_TABLE}`"
        ).to_dataframe()
    except Exception:
        return {}
    return {int(r.space_id): r.space_name for r in df.itertuples()}


def get_mn_api_key(email: str) -> str | None:
    """Return the stored Mighty Networks API key for a user, or None."""
    sql = f"""
        SELECT mn_api_key
        FROM `{config.TEAM_API_KEYS_TABLE}`
        WHERE email = '{email}'
        ORDER BY updated_at DESC
        LIMIT 1
    """
    df = client.query(sql).to_dataframe()
    if df.empty:
        return None
    return df.iloc[0]["mn_api_key"]


def search_members(query: str, limit: int = 20) -> pd.DataFrame:
    """Search community members by name or email.
    Pass query='' to load all active members (used for in-memory search cache)."""
    q = (query or "").strip()
    params = [bigquery.ScalarQueryParameter("limit", "INT64", int(limit))]
    where_search = ""
    if q:
        where_search = """AND (
              LOWER(CONCAT(COALESCE(m.first_name,''), ' ', COALESCE(m.last_name,''))) LIKE @pattern
              OR LOWER(m.email_address) LIKE @pattern
          )"""
        params.append(
            bigquery.ScalarQueryParameter("pattern", "STRING", f"%{q.lower()}%")
        )
    sql = f"""
        SELECT
            m.member_id,
            TRIM(CONCAT(COALESCE(m.first_name,''), ' ', COALESCE(m.last_name,''))) AS full_name,
            m.email_address,
            m.network_role,
            m.join_date
        FROM `{config.PROJECT_ID}.dataform.core_members` m
        WHERE m.client_id = 'lesko_4022250'
          AND LOWER(m.member_status) = 'active'
          {where_search}
        ORDER BY m.last_name, m.first_name
        LIMIT @limit
    """
    job_config = bigquery.QueryJobConfig(query_parameters=params)
    return client.query(sql, job_config=job_config).to_dataframe()


def get_grant_coaches() -> pd.DataFrame:
    sql = f"""
        SELECT gc.member_id, gc.full_name, gc.email, gc.login_email, gc.added_at, gc.added_by
        FROM `{config.GRANT_COACHES_TABLE}` gc
        ORDER BY gc.added_at DESC
    """
    return client.query(sql).to_dataframe()


def get_coach_by_login_email(login_email: str):
    """Return the coach row for a given login email (checks both login_email and MN email)."""
    e = login_email.replace("'", "\\'")
    sql = f"""
        SELECT member_id, full_name, email, login_email
        FROM `{config.GRANT_COACHES_TABLE}`
        WHERE login_email = '{e}' OR email = '{e}'
        LIMIT 1
    """
    df = client.query(sql).to_dataframe()
    return df.iloc[0].to_dict() if not df.empty else None


def get_unlinked_coaches() -> pd.DataFrame:
    """Coaches that haven't linked a portal login yet (login_email is NULL)."""
    sql = f"""
        SELECT member_id, full_name, email
        FROM `{config.GRANT_COACHES_TABLE}`
        WHERE login_email IS NULL OR login_email = ''
        ORDER BY full_name
    """
    return client.query(sql).to_dataframe()


def get_upcoming_events() -> list[dict]:
    """Return upcoming RSVP-enabled events from BQ, ordered by start time."""
    sql = f"""
        SELECT event_id, title, starts_at, ends_at, time_zone,
               event_type, zoom_link, permalink
        FROM `{config.PROJECT_ID}.grant_helpdesk.upcoming_events`
        WHERE starts_at > CURRENT_TIMESTAMP()
        ORDER BY starts_at ASC
    """
    df = client.query(sql).to_dataframe()
    return df.to_dict("records")


def get_followup_statuses(content_ids: list) -> dict:
    """Return {ticket_id: {status, send_after, sent_at}} for any tickets with a follow-up queued."""
    if not content_ids:
        return {}
    ids_str = ", ".join(f"'{c}'" for c in content_ids)
    sql = f"""
        SELECT ticket_id, status, send_after, sent_at
        FROM `{config.FOLLOWUP_QUEUE_TABLE}`
        WHERE ticket_id IN ({ids_str})
        QUALIFY ROW_NUMBER() OVER (PARTITION BY ticket_id ORDER BY created_at DESC) = 1
    """
    try:
        df = client.query(sql).to_dataframe()
        return {str(r["ticket_id"]): r.to_dict() for _, r in df.iterrows()}
    except Exception as e:
        log_event("ERROR", "bq_client.get_followup_statuses", str(e))
        return {}


def preview_bulk_close(
    status_filter: str = "answered",
    assigned_to: str = "",
    before_date: str = "",
) -> dict:
    """
    Returns {"will_close": N, "skipped_followup": M} for the given filters.
    Excludes already-closed/cancelled tickets and those with pending follow-ups.
    """
    conditions = ["t.effective_status NOT IN ('closed', 'cancelled')"]
    if status_filter:
        safe_status = status_filter.replace("'", "")
        conditions.append(f"t.effective_status = '{safe_status}'")
    if assigned_to:
        safe_assigned = assigned_to.replace("'", "\\'")
        conditions.append(f"t.effective_assigned_to = '{safe_assigned}'")
    if before_date:
        safe_date = before_date.replace("'", "")
        conditions.append(f"DATE(t.created_at) < '{safe_date}'")

    where = "WHERE " + " AND ".join(conditions)

    sql = f"""
        WITH base AS (
            SELECT
                gt.content_id,
                gt.created_at,
                CASE
                    WHEN tm.status IS NOT NULL AND tm.status != '' THEN tm.status
                    ELSE gt.ticket_status
                END AS effective_status,
                COALESCE(tm.assigned_to, gt.assigned_to) AS effective_assigned_to
            FROM `{config.TICKETS_TABLE}` gt
            LEFT JOIN (
                SELECT * FROM `{config.META_TABLE}`
                QUALIFY ROW_NUMBER() OVER (PARTITION BY content_id ORDER BY updated_at DESC) = 1
            ) tm ON gt.content_id = tm.content_id
            QUALIFY ROW_NUMBER() OVER (PARTITION BY gt.content_id ORDER BY gt.created_at DESC) = 1
        ),
        filtered AS (
            SELECT t.content_id
            FROM base t
            {where}
        )
        SELECT
            COUNT(*) AS total,
            COUNTIF(fq.ticket_id IS NOT NULL) AS skipped_followup
        FROM filtered f
        LEFT JOIN (
            SELECT DISTINCT ticket_id
            FROM `{config.FOLLOWUP_QUEUE_TABLE}`
            WHERE status = 'pending'
        ) fq ON f.content_id = fq.ticket_id
    """
    row = list(client.query(sql).result())[0]
    total        = int(row["total"])
    skipped      = int(row["skipped_followup"])
    return {"will_close": total - skipped, "skipped_followup": skipped}


def get_open_stats() -> dict:
    def _build():
        _reopen_clause = _live_status_cte()
        _lane_expr     = _live_lane_expr()
        _urgency_expr  = _urgency_clock_expr()
        return f"""
            WITH live AS (
                SELECT
                    gt.created_at,
                    {_lane_expr} AS lane,
                    CASE
                        {_reopen_clause}
                        WHEN tm.status IS NOT NULL AND tm.status != ''      THEN tm.status
                        ELSE gt.ticket_status
                    END AS ticket_status,
                    {_urgency_expr} AS urgency_since
                FROM `{config.TICKETS_TABLE}` gt
                LEFT JOIN (
                    SELECT * FROM `{config.META_TABLE}`
                    QUALIFY ROW_NUMBER() OVER (PARTITION BY content_id ORDER BY updated_at DESC) = 1
                ) tm ON gt.content_id = tm.content_id
                -- Only count tickets a coach can act on: empty-body posts/comments
                -- have no question text and are hidden from the ticket list, so they
                -- must not inflate the KPI either (keep in sync with get_tickets).
                WHERE gt.body IS NOT NULL AND TRIM(gt.body) != ''
                QUALIFY ROW_NUMBER() OVER (PARTITION BY gt.content_id ORDER BY gt.created_at DESC) = 1
            )
            SELECT
                COUNTIF(ticket_status NOT IN {_TERMINAL_IN})                                       AS open,
                COUNTIF(ticket_status NOT IN {_TERMINAL_IN}
                    AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), urgency_since, HOUR) < 24)                      AS normal,
                COUNTIF(ticket_status NOT IN {_TERMINAL_IN}
                    AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), urgency_since, HOUR) BETWEEN 24 AND 47)         AS urgent,
                COUNTIF(ticket_status NOT IN {_TERMINAL_IN}
                    AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), urgency_since, HOUR) >= 48)                     AS critical
            FROM live
            -- The KPI cards are about grant questions. Conversations have their
            -- own tab and deliberately do not count towards these four numbers.
            WHERE lane = '{config.LANE_QUESTION}'
        """
    row = _query_with_schema_retry(_build).iloc[0]
    return row.to_dict()


def get_daily_stats() -> dict:
    def _build():
        _reopen_clause = _live_status_cte()
        _lane_expr     = _live_lane_expr()
        return f"""
            WITH live AS (
                SELECT
                    gt.created_at,
                    gt.first_engagement_at,
                    COALESCE(tm.updated_at, gt.ticket_updated_at) AS ticket_updated_at,
                    {_lane_expr} AS lane,
                    CASE
                        {_reopen_clause}
                        WHEN tm.status IS NOT NULL AND tm.status != ''      THEN tm.status
                        ELSE gt.ticket_status
                    END AS ticket_status
                FROM `{config.TICKETS_TABLE}` gt
                LEFT JOIN (
                    SELECT * FROM `{config.META_TABLE}`
                    QUALIFY ROW_NUMBER() OVER (PARTITION BY content_id ORDER BY updated_at DESC) = 1
                ) tm ON gt.content_id = tm.content_id
                QUALIFY ROW_NUMBER() OVER (PARTITION BY gt.content_id ORDER BY gt.created_at DESC) = 1
            )
            SELECT
                COUNTIF(DATE(created_at) = CURRENT_DATE())                                              AS in_today,
                COUNTIF(ticket_status IN ('answered', 'closed')
                    AND DATE(COALESCE(first_engagement_at, ticket_updated_at)) = CURRENT_DATE())        AS answered_today,
                ROUND(
                    COUNTIF(
                        ticket_status IN ('answered', 'closed')
                        AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
                    ) / 30.0, 1
                )                                                                                       AS daily_avg
            FROM live
            -- Question lane only, so these three match the four cards above.
            WHERE lane = '{config.LANE_QUESTION}'
        """
    row = _query_with_schema_retry(_build).iloc[0]
    result = row.to_dict()
    result["goal"] = config.DAILY_GOAL
    return result


def get_thread(thread_id: str) -> pd.DataFrame:
    """
    Fetch every item in a thread — root post + all comments — ordered by time.
    thread_id is always 'post_NNN'. Returns author_type ('team'/'member') and
    depth so the UI can render the conversation correctly.
    """
    if thread_id.startswith("comment_"):
        # thread_id not yet backfilled — look up the parent post from core_comments
        comment_id = thread_id.replace("comment_", "")
        lookup = client.query(f"""
            SELECT CAST(targetable_id AS STRING) AS post_id
            FROM `bigtribebuilders.dataform.core_comments`
            WHERE comment_id = {comment_id} AND client_id = 'lesko_4022250'
            LIMIT 1
        """).to_dataframe()
        if lookup.empty:
            return pd.DataFrame()
        post_id = lookup.iloc[0]["post_id"]
    else:
        post_id = thread_id.replace("post_", "")
    sql = f"""
        WITH root_post AS (
            SELECT
                CONCAT('post_', CAST(p.post_id AS STRING))   AS content_id,
                'post'                                         AS content_type,
                0                                              AS depth,
                CAST(NULL AS INT64)                            AS reply_to_id,
                p.creator_id                                   AS author_id,
                TRIM(CONCAT(
                    COALESCE(m.first_name, ''), ' ',
                    COALESCE(m.last_name,  '')
                ))                                             AS author_name,
                CASE
                    WHEN m.network_role IN ('host', 'moderator') THEN 'team'
                    ELSE 'member'
                END                                            AS author_type,
                TRIM(REGEXP_REPLACE(
                    REGEXP_REPLACE(COALESCE(p.description, ''), r'<[^>]+>', ' '),
                    r'\\s+', ' '
                ))                                             AS body,
                p.permalink,
                p.created_at
            FROM `bigtribebuilders.dataform.core_posts` p
            LEFT JOIN `bigtribebuilders.dataform.core_members` m
                ON  p.creator_id = m.member_id
                AND m.client_id  = 'lesko_4022250'
            WHERE p.client_id = 'lesko_4022250'
              AND p.post_id   = CAST('{post_id}' AS INT64)
        ),

        all_comments AS (
            SELECT
                CONCAT('comment_', CAST(c.comment_id AS STRING)) AS content_id,
                'comment'                                          AS content_type,
                c.depth,
                c.reply_to_id,
                c.author_id,
                TRIM(CONCAT(
                    COALESCE(m.first_name, ''), ' ',
                    COALESCE(m.last_name,  '')
                ))                                                 AS author_name,
                CASE
                    WHEN m.network_role IN ('host', 'moderator') THEN 'team'
                    ELSE 'member'
                END                                                AS author_type,
                TRIM(REGEXP_REPLACE(
                    REGEXP_REPLACE(COALESCE(c.comment_text, ''), r'<[^>]+>', ' '),
                    r'\\s+', ' '
                ))                                                 AS body,
                c.permalink,
                c.created_at
            FROM `bigtribebuilders.dataform.core_comments` c
            LEFT JOIN `bigtribebuilders.dataform.core_members` m
                ON  c.author_id = m.member_id
                AND m.client_id = 'lesko_4022250'
            WHERE c.client_id      = 'lesko_4022250'
              AND c.targetable_id  = CAST('{post_id}' AS INT64)
              AND c.comment_status = 'active'
        )

        SELECT * FROM root_post
        UNION ALL
        SELECT * FROM all_comments
        ORDER BY created_at ASC, depth ASC
    """
    return client.query(sql).to_dataframe()


def get_member_history(member_id: int, exclude_content_id: str = None) -> pd.DataFrame:
    exclude = f"AND gt.content_id != '{exclude_content_id}'" if exclude_content_id else ""
    _gt_cols = _tickets_cols()
    _team_replied_sql = "OR gt.team_comment_replied" if "team_comment_replied" in _gt_cols else ""
    sql = f"""
        SELECT
            gt.content_id,
            gt.content_type,
            gt.thread_id,
            gt.permalink,
            LEFT(gt.body, 300) AS body_preview,
            gt.created_at,
            CASE
                WHEN gt.team_commented OR gt.team_reacted {_team_replied_sql} THEN 'answered'
                WHEN tm.status IS NOT NULL AND tm.status != ''      THEN tm.status
                ELSE 'open'
            END AS ticket_status,
            -- shown beside the status so a coach can see at a glance that a past
            -- item was a conversation, not a question they failed to answer
            {_live_lane_expr(_gt_cols)}                             AS lane
        FROM `{config.TICKETS_TABLE}` gt
        LEFT JOIN (
            SELECT * FROM `{config.META_TABLE}`
            QUALIFY ROW_NUMBER() OVER (PARTITION BY content_id ORDER BY updated_at DESC) = 1
        ) tm ON gt.content_id = tm.content_id
        WHERE gt.member_id = {member_id}
          {exclude}
        QUALIFY ROW_NUMBER() OVER (PARTITION BY gt.content_id ORDER BY gt.created_at DESC) = 1
        ORDER BY gt.created_at DESC
        LIMIT 20
    """
    return client.query(sql).to_dataframe()


def get_report_data(report_type: str, date_from: str, date_to: str) -> pd.DataFrame:
    if report_type == "volume":
        sql = f"""
            SELECT
                DATE(created_at)                             AS date,
                COUNT(*)                                     AS tickets_in,
                COUNTIF(ticket_status = 'closed')            AS tickets_closed
            FROM `{config.TICKETS_TABLE}`
            WHERE DATE(created_at) BETWEEN '{date_from}' AND '{date_to}'
            GROUP BY date
            ORDER BY date
        """
    elif report_type == "response_time":
        sql = f"""
            SELECT
                TIMESTAMP_DIFF(first_engagement_at, created_at, MINUTE) AS minutes_to_response
            FROM `{config.TICKETS_TABLE}`
            WHERE first_engagement_at IS NOT NULL
              AND DATE(created_at) BETWEEN '{date_from}' AND '{date_to}'
        """
    elif report_type == "team_productivity":
        sql = f"""
            SELECT
                assigned_to,
                COUNT(*) AS tickets_closed
            FROM `{config.TICKETS_TABLE}`
            WHERE ticket_status = 'closed'
              AND DATE(ticket_updated_at) BETWEEN '{date_from}' AND '{date_to}'
              AND assigned_to IS NOT NULL AND assigned_to != ''
            GROUP BY assigned_to
            ORDER BY tickets_closed DESC
        """
    elif report_type == "domain_breakdown":
        sql = f"""
            SELECT
                COALESCE(domain, 'unset') AS domain,
                COUNT(*)                  AS tickets
            FROM `{config.TICKETS_TABLE}`
            WHERE DATE(created_at) BETWEEN '{date_from}' AND '{date_to}'
            GROUP BY domain
            ORDER BY tickets DESC
        """
    else:
        return pd.DataFrame()

    return client.query(sql).to_dataframe()


def get_prompt_history() -> pd.DataFrame:
    """
    Returns all prompt versions with their classifier stats and feedback counts.
    Each row covers the period from that version's created_at until the next
    version's created_at (or NOW for the current version).
    """
    sql = f"""
        WITH
          versions AS (
            SELECT
              version,
              prompt_text,
              change_reason,
              created_by,
              created_at,
              LEAD(created_at) OVER (ORDER BY version) AS superseded_at
            FROM `{config.PROMPT_CONFIG_TABLE}`
          ),
          classifier_stats AS (
            SELECT
              v.version,
              COUNT(*)                        AS total_classified,
              COUNTIF(qc.is_question = TRUE)  AS classified_as_question
            FROM versions v
            LEFT JOIN `{config.CLASSIFIER_TABLE}` qc
              ON  qc.classified_at >= v.created_at
              AND (v.superseded_at IS NULL OR qc.classified_at < v.superseded_at)
            GROUP BY v.version
          ),
          feedback_stats AS (
            SELECT
              v.version,
              COUNTIF(f.feedback_type = 'not_a_question')     AS false_positives,
              COUNTIF(f.feedback_type = 'confirmed_question')  AS confirmed_questions
            FROM versions v
            LEFT JOIN `{config.FEEDBACK_VIEW}` f
              ON  f.flagged_at >= v.created_at
              AND (v.superseded_at IS NULL OR f.flagged_at < v.superseded_at)
            GROUP BY v.version
          )
        SELECT
          v.version,
          v.prompt_text,
          v.change_reason,
          v.created_at,
          v.superseded_at,
          (v.superseded_at IS NULL)                      AS is_current,
          COALESCE(cs.total_classified,    0)            AS total_classified,
          COALESCE(cs.classified_as_question, 0)         AS classified_as_question,
          COALESCE(fs.false_positives,     0)            AS false_positives,
          COALESCE(fs.confirmed_questions, 0)            AS confirmed_questions
        FROM versions v
        LEFT JOIN classifier_stats cs ON cs.version = v.version
        LEFT JOIN feedback_stats   fs ON fs.version = v.version
        ORDER BY v.version DESC
    """
    return client.query(sql).to_dataframe()


def get_classification_feedback(date_from: str, date_to: str) -> pd.DataFrame:
    sql = f"""
        SELECT *
        FROM `{config.FEEDBACK_VIEW}`
        WHERE DATE(flagged_at) BETWEEN '{date_from}' AND '{date_to}'
        ORDER BY flagged_at DESC
    """
    return client.query(sql).to_dataframe()


def get_standard_replies() -> pd.DataFrame:
    """Active standard replies (answer templates), ordered by title."""
    sql = f"""
        SELECT reply_id, title, body, created_by, created_at, updated_by, updated_at
        FROM `{config.STANDARD_REPLIES_TABLE}`
        WHERE is_active
        ORDER BY LOWER(title)
    """
    return client.query(sql).to_dataframe()


def get_team_feedback() -> pd.DataFrame:
    # Note: TEAM_FEEDBACK_TABLE is defined in bq_writes for write-side use; we
    # rebuild the same fully-qualified table name here to keep reads independent.
    table = f"{config.PROJECT_ID}.{config.DATASET}.team_feedback"
    sql = f"""
        SELECT *
        FROM `{table}`
        ORDER BY created_at DESC
    """
    return client.query(sql).to_dataframe()


def get_app_logs(limit: int = 100, level: str = None) -> pd.DataFrame:
    """Return recent rows from app_logs, optionally filtered by level (ERROR, WARNING, INFO)."""
    level_filter = f"AND level = '{level}'" if level else ""
    sql = f"""
        SELECT created_at, level, source, message, detail
        FROM `{config.LOGS_TABLE}`
        WHERE 1=1 {level_filter}
        ORDER BY created_at DESC
        LIMIT {int(limit)}
    """
    return client.query(sql).to_dataframe()
