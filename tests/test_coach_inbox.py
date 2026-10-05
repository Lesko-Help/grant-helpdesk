"""
Offline proof for coach_inbox.py — see docs/specs/modules/coach_inbox.md.

Slice A1 (docs/briefs/coach-inbox-list.md): the merge_into_tickets tracer.
Slice A2: load_member_questions, against a fake BigQuery client — never the
real one, so this file never needs live credentials or touches BigQuery.
"""

import pandas as pd

import coach_inbox


# ── load_member_questions fakes (A2) ────────────────────────────────────────

class _FakeQueryResult:
    """Stands in for a google.cloud.bigquery QueryJob: only .to_dataframe()
    is ever called on it by coach_inbox.load_member_questions."""

    def __init__(self, df):
        self._df = df

    def to_dataframe(self):
        return self._df


class _FakeBigQueryClient:
    """Stands in for google.cloud.bigquery.Client. load_member_questions
    sends a single query joining threads, messages and core_members (review
    finding 6: both datasets confirmed EU, so there is no region reason to
    split them), then — only once it has at least one thread — a second
    query against private_thread_workflow (R3/R5/R6). Dispatches on the SQL
    text so one fake covers both; workflow_df defaults to empty (no thread
    closed), matching every test written before the workflow read existed."""

    def __init__(self, threads_df, workflow_df=None):
        self._threads_df = threads_df
        self._workflow_df = (
            workflow_df if workflow_df is not None
            else pd.DataFrame(columns=["thread_id", "closed_at"])
        )
        self.queries = []

    def query(self, sql, job_config=None):
        self.queries.append(sql)
        if "private_thread_workflow" in sql:
            return _FakeQueryResult(self._workflow_df)
        return _FakeQueryResult(self._threads_df)


class _WorkflowRaisingClient:
    """Succeeds on the main threads+messages+core_members query but raises
    on the private_thread_workflow read — proves R6: a workflow-table
    outage alone must never hide a member's question, only leave every
    thread unmarked as closed."""

    def __init__(self, threads_df):
        self._threads_df = threads_df
        self.queries = []

    def query(self, sql, job_config=None):
        self.queries.append(sql)
        if "private_thread_workflow" in sql:
            raise RuntimeError("could not reach BigQuery")
        return _FakeQueryResult(self._threads_df)


def _msg(author_role, body, created_at):
    return {"author_role": author_role, "body": body, "created_at": created_at}


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


def _full_ticket_row(content_id, member_id, member_name, created_at, thread_id, urgency, ticket_status):
    return {
        "content_id": content_id,
        "member_id": member_id,
        "member_name": member_name,
        "created_at": created_at,
        "thread_id": thread_id,
        "urgency": urgency,
        "ticket_status": ticket_status,
    }


def _realistic_fixture_frames():
    # Shaped like the frame render_ticket_table actually consumes (finding 8):
    # tickets carry thread_id/urgency/ticket_status, and member 5 has two
    # separate private-chat threads — the case finding 1's bug collapsed.
    tickets = pd.DataFrame([
        _full_ticket_row("t1", 1, "Alice", "2026-09-20T10:00:00Z", "post_100", "normal", "open"),
        _full_ticket_row("t2", 2, "Bob",   "2026-09-23T10:00:00Z", None,        "urgent", "open"),
    ])
    questions = pd.DataFrame([
        _question_row("pc:th1", 5, "Eve", "2026-09-22T10:00:00Z", "2026-09-22T12:00:00Z", "waiting"),
        _question_row("pc:th2", 5, "Eve", "2026-09-21T10:00:00Z", "2026-09-21T15:00:00Z", "waiting"),
    ])
    return tickets, questions


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


def test_should_include_questions_only_when_every_filter_is_all():
    # R3: urgency, domain and space have no meaning for a private-chat
    # thread — a ticket-only field — so a coach narrowing any one of them
    # must not have questions falsely stay in the list.
    assert coach_inbox.should_include_questions("All", "All") is True
    assert coach_inbox.should_include_questions("All", "All", "All") is True
    assert coach_inbox.should_include_questions("Urgent", "All") is False
    assert coach_inbox.should_include_questions("All", "Housing") is False
    assert coach_inbox.should_include_questions("All", "All", "General") is False


def test_filter_questions_by_status_shows_only_closed_when_filter_is_closed():
    # R4: Status = closed -> only the closed member questions, nothing else.
    questions = pd.DataFrame([
        {"content_id": "pc:t1", "status": "waiting"},
        {"content_id": "pc:t2", "status": "answered"},
        {"content_id": "pc:t3", "status": "closed"},
    ])
    result = coach_inbox.filter_questions_by_status(questions, "closed")
    assert result["content_id"].tolist() == ["pc:t3"]


def test_filter_questions_by_status_hides_closed_under_every_other_status():
    # R4: every Status other than "closed", including "All", hides the
    # closed ones and keeps the rest.
    questions = pd.DataFrame([
        {"content_id": "pc:t1", "status": "waiting"},
        {"content_id": "pc:t2", "status": "answered"},
        {"content_id": "pc:t3", "status": "closed"},
    ])
    for filter_status in ("All", "open", "answered"):
        result = coach_inbox.filter_questions_by_status(questions, filter_status)
        assert result["content_id"].tolist() == ["pc:t1", "pc:t2"]


def test_filter_questions_by_status_on_empty_questions_returns_empty():
    empty = pd.DataFrame(columns=["content_id", "status"])
    assert coach_inbox.filter_questions_by_status(empty, "closed").empty


# ── member_question_action_opts (R5) — moved from app.py so it can be tested;
# app.py's own login gate makes it impossible to import under pytest at all.

def test_member_question_action_opts_offers_close_when_waiting():
    assert coach_inbox.member_question_action_opts("waiting") == ["— action —", "Answer", "Close"]


def test_member_question_action_opts_offers_close_when_answered():
    # R5: Close is offered on every open row, answered or not.
    assert coach_inbox.member_question_action_opts("answered") == ["— action —", "Answer", "Close"]


def test_member_question_action_opts_hides_close_when_already_closed():
    assert coach_inbox.member_question_action_opts("closed") == ["— action —", "Answer"]


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


# ── ticket_group_key (review finding 1 / finding 8) ─────────────────────────

def test_ticket_group_key_keeps_two_threads_from_one_member_apart():
    # Finding 1: after the merge, a member-question row has no thread_id of
    # its own — pd.concat fills it with NaN, and `NaN or ""` stays NaN (NaN
    # is truthy), so both of this member's threads used to key as "5|nan"
    # and collapse into one bogus render group. Each question row must key
    # on its own content_id so it never groups with any other row.
    tickets, questions = _realistic_fixture_frames()
    merged = coach_inbox.merge_into_tickets(tickets, questions)
    keys = merged.apply(coach_inbox.ticket_group_key, axis=1)
    assert keys.nunique() == len(merged)


def test_ticket_group_key_still_groups_a_real_tickets_thread():
    # Real MN tickets replying on the same forum thread must still share a
    # group key — this must not regress while fixing finding 1.
    tickets, questions = _realistic_fixture_frames()
    tickets = pd.concat([tickets, pd.DataFrame([
        _full_ticket_row("t3", 1, "Alice", "2026-09-24T10:00:00Z", "post_100", "critical", "open"),
    ])], ignore_index=True)
    merged = coach_inbox.merge_into_tickets(tickets, questions)
    keys = merged.apply(coach_inbox.ticket_group_key, axis=1)
    t1_key = keys[merged["content_id"] == "t1"].iloc[0]
    t3_key = keys[merged["content_id"] == "t3"].iloc[0]
    assert t1_key == t3_key


# ── member naming (review findings 5 and 6) ─────────────────────────────────
#
# _member_names no longer exists as its own function: finding 6 folded its
# core_members lookup into load_member_questions's single query (R1 — see
# below), since core_members and private_chat are confirmed both EU, so
# there is no region reason left to keep two queries. Its client_id filter
# and blank-name fallback (finding 5) still apply — now proven against the
# one query's SQL text and its output, rather than a standalone helper.

def test_load_member_questions_sends_exactly_one_query_joining_core_members():
    # R1: one parameterised query, not two joined in pandas.
    empty_threads = pd.DataFrame(
        columns=["thread_id", "member_id", "subject", "topic", "thread_created_at",
                 "messages", "full_name"]
    )
    fake = _FakeBigQueryClient(empty_threads)
    coach_inbox.load_member_questions(client=fake)
    assert len(fake.queries) == 1
    sql = fake.queries[0]
    assert "core_members" in sql
    # Every other core_members query in this repo filters by client_id —
    # without it, a matching member_id from another client could supply a
    # name that belongs to someone else entirely (review finding 5).
    assert "client_id = 'lesko_4022250'" in sql


def test_load_member_questions_array_agg_has_a_message_id_tie_break():
    # Review finding 6: two messages sharing a created_at made ARRAY_AGG's
    # ORDER BY nondeterministic, so status ("waiting"/"answered", read off
    # the last element) could flip between runs. message_id breaks the tie.
    empty_threads = pd.DataFrame(
        columns=["thread_id", "member_id", "subject", "topic", "thread_created_at",
                 "messages", "full_name"]
    )
    fake = _FakeBigQueryClient(empty_threads)
    coach_inbox.load_member_questions(client=fake)
    assert "ORDER BY m.created_at, m.message_id" in fake.queries[0]


def test_load_member_questions_dedupes_core_members_before_the_join():
    # Re-review minor 2: core_members joined into the messages GROUP BY
    # while still ungrouped itself would duplicate every message in a
    # thread once per matching core_members row, if that table ever carried
    # more than one row for the same (member_id, client_id) — corrupting
    # last_activity_at/status along with it. core_members must be collapsed
    # to at most one row per member_id, in its own GROUP BY, before it is
    # joined to the already-aggregated threads.
    empty_threads = pd.DataFrame(
        columns=["thread_id", "member_id", "subject", "topic", "thread_created_at",
                 "messages", "full_name"]
    )
    fake = _FakeBigQueryClient(empty_threads)
    coach_inbox.load_member_questions(client=fake)
    sql = fake.queries[0]
    assert "GROUP BY member_id" in sql
    core_members_pos = sql.index("core_members")
    group_by_member_pos = sql.index("GROUP BY member_id")
    join_pos = sql.index("LEFT JOIN")
    assert core_members_pos < group_by_member_pos < join_pos


def test_load_member_questions_blank_name_falls_back_to_member_id():
    # R2: a member with no first or last name on file (or no core_members
    # row at all) falls back to "Member <id>", not an empty string.
    threads_df = pd.DataFrame([
        {
            "thread_id": "th3", "member_id": 333, "subject": "s", "topic": "t",
            "thread_created_at": "2026-09-20T08:00:00Z",
            "messages": [_msg("member", "hi", "2026-09-20T08:00:00Z")],
            "full_name": "",
        },
    ])
    fake = _FakeBigQueryClient(threads_df)
    result = coach_inbox.load_member_questions(client=fake)
    assert result.iloc[0]["member_name"] == "Member 333"


# ── load_member_questions (A2) ──────────────────────────────────────────────

def test_load_member_questions_builds_rows_from_threads_and_messages():
    # R1/R2: one row per thread, tagged and named; R3: status from the
    # newest message's author_role (member -> waiting, coach -> answered).
    threads_df = pd.DataFrame([
        {
            "thread_id": "th1",
            "member_id": 111,
            "subject": "Rent help",
            "topic": "housing",
            "thread_created_at": "2026-09-20T08:00:00Z",
            "messages": [
                _msg("member", "Can you help with rent?", "2026-09-20T08:00:00Z"),
                _msg("coach", "Sure, let's talk", "2026-09-20T09:00:00Z"),
            ],
            "full_name": "Carol Smith",
        },
        {
            "thread_id": "th2",
            "member_id": 222,
            "subject": "Car repair",
            "topic": "cars",
            "thread_created_at": "2026-09-21T08:00:00Z",
            "messages": [
                _msg("member", "My car broke down", "2026-09-21T08:00:00Z"),
            ],
            "full_name": "",
        },
    ])
    fake = _FakeBigQueryClient(threads_df)

    result = coach_inbox.load_member_questions(client=fake)

    by_id = {row["content_id"]: row for _, row in result.iterrows()}
    assert set(by_id) == {"pc:th1", "pc:th2"}

    th1 = by_id["pc:th1"]
    assert th1["source"] == "member_question"
    assert th1["member_id"] == 111
    assert th1["member_name"] == "Carol Smith"  # found in core_members
    assert th1["topic"] == "housing"
    assert th1["subject"] == "Rent help"
    assert th1["created_at"] == "2026-09-20T08:00:00Z"
    assert th1["last_activity_at"] == "2026-09-20T09:00:00Z"
    assert [m["author_role"] for m in th1["messages"]] == ["member", "coach"]
    assert th1["status"] == "answered"

    th2 = by_id["pc:th2"]
    assert th2["member_name"] == "Member 222"  # not in core_members -> fallback
    assert th2["status"] == "waiting"


# ── closed status, derived from private_thread_workflow (R3, R5, R6) ───────

def _thread_row(thread_id, member_id, messages, full_name=""):
    return {
        "thread_id": thread_id,
        "member_id": member_id,
        "subject": "s",
        "topic": "t",
        "thread_created_at": messages[0]["created_at"],
        "messages": messages,
        "full_name": full_name,
    }


def test_load_member_questions_marks_a_thread_closed_from_the_workflow_table():
    # R3: a closed_at in private_thread_workflow, with no member message
    # newer than it, reads as status "closed".
    threads_df = pd.DataFrame([
        _thread_row("th1", 111, [
            _msg("member", "Which form do I use?", "2026-10-01T08:00:00Z"),
            _msg("coach", "Use form B", "2026-10-01T09:00:00Z"),
        ]),
    ])
    workflow_df = pd.DataFrame([{"thread_id": "th1", "closed_at": "2026-10-01T10:00:00Z"}])
    fake = _FakeBigQueryClient(threads_df, workflow_df=workflow_df)

    result = coach_inbox.load_member_questions(client=fake)

    assert result.iloc[0]["status"] == "closed"


def test_load_member_questions_reopens_as_waiting_after_a_newer_member_message():
    # R5: a member message after closed_at brings the thread back as
    # "waiting", with nothing written back to the workflow table.
    threads_df = pd.DataFrame([
        _thread_row("th1", 111, [
            _msg("member", "Which form do I use?", "2026-10-01T08:00:00Z"),
            _msg("coach", "Use form B", "2026-10-01T09:00:00Z"),
            _msg("member", "Actually, one more question", "2026-10-01T11:00:00Z"),
        ]),
    ])
    workflow_df = pd.DataFrame([{"thread_id": "th1", "closed_at": "2026-10-01T10:00:00Z"}])
    fake = _FakeBigQueryClient(threads_df, workflow_df=workflow_df)

    result = coach_inbox.load_member_questions(client=fake)

    assert result.iloc[0]["status"] == "waiting"


def test_load_member_questions_other_threads_unaffected_by_an_unrelated_closed_row():
    threads_df = pd.DataFrame([
        _thread_row("th1", 111, [_msg("member", "hi", "2026-10-01T08:00:00Z")]),
        _thread_row("th2", 222, [
            _msg("member", "hi", "2026-10-01T08:00:00Z"),
            _msg("coach", "hello", "2026-10-01T09:00:00Z"),
        ]),
    ])
    workflow_df = pd.DataFrame([{"thread_id": "th2", "closed_at": "2026-10-01T10:00:00Z"}])
    fake = _FakeBigQueryClient(threads_df, workflow_df=workflow_df)

    result = coach_inbox.load_member_questions(client=fake)
    by_id = {row["content_id"]: row["status"] for _, row in result.iterrows()}

    assert by_id == {"pc:th1": "waiting", "pc:th2": "closed"}


def test_load_member_questions_reopened_then_reanswered_shows_answered_not_waiting():
    # Bug found in review: a member reopens a closed thread and a coach
    # answers again — load R3's own rule is "the newest message decides",
    # and the newest message here is the coach's, so this must read
    # "answered", not get forced back to "waiting" just because some member
    # message exists somewhere after closed_at.
    threads_df = pd.DataFrame([
        _thread_row("th1", 111, [
            _msg("member", "Which form do I use?", "2026-10-01T08:00:00Z"),
            _msg("coach", "Use form B", "2026-10-01T09:00:00Z"),
            _msg("member", "Actually, one more question", "2026-10-01T10:05:00Z"),
            _msg("coach", "Sure, here you go", "2026-10-01T10:10:00Z"),
        ]),
    ])
    workflow_df = pd.DataFrame([{"thread_id": "th1", "closed_at": "2026-10-01T10:00:00Z"}])
    fake = _FakeBigQueryClient(threads_df, workflow_df=workflow_df)

    result = coach_inbox.load_member_questions(client=fake)

    assert result.iloc[0]["status"] == "answered"


def test_load_member_questions_reopen_check_uses_real_datetime_comparison():
    # The earlier closed/reopen tests above use ISO strings, which happen to
    # sort the same way real time does — proving only that string ordering
    # works, not that the comparison handles the real datetime/Timestamp
    # values BigQuery's to_dataframe() actually returns.
    threads_df = pd.DataFrame([
        _thread_row("th1", 111, [
            _msg("member", "Which form do I use?", pd.Timestamp("2026-10-01T08:00:00Z")),
            _msg("coach", "Use form B", pd.Timestamp("2026-10-01T09:00:00Z")),
            _msg("member", "One more thing", pd.Timestamp("2026-10-01T10:05:00Z")),
        ]),
    ])
    workflow_df = pd.DataFrame([{"thread_id": "th1", "closed_at": pd.Timestamp("2026-10-01T10:00:00Z")}])
    fake = _FakeBigQueryClient(threads_df, workflow_df=workflow_df)

    result = coach_inbox.load_member_questions(client=fake)

    assert result.iloc[0]["status"] == "waiting"


def test_load_member_questions_nat_closed_at_does_not_stick_closed_forever():
    # Bug found in review: `closed_at is None` misses pd.NaT, which is how a
    # NULL closed_at actually surfaces after .to_dataframe() — a row like
    # this used to get stuck "closed" forever, since any comparison against
    # NaT is always False and so could never satisfy the reopen check.
    # pd.isna() catches it instead, leaving the row's status as whatever the
    # first loop already derived from its real newest message.
    threads_df = pd.DataFrame([
        _thread_row("th1", 111, [_msg("member", "hi", "2026-10-01T08:00:00Z")]),
    ])
    workflow_df = pd.DataFrame([{"thread_id": "th1", "closed_at": pd.NaT}])
    fake = _FakeBigQueryClient(threads_df, workflow_df=workflow_df)

    result = coach_inbox.load_member_questions(client=fake)

    assert result.iloc[0]["status"] == "waiting"


def test_load_member_questions_workflow_read_failure_returns_all_threads_none_closed(capsys):
    # R6: only the workflow read raises -> every thread still comes back,
    # none shown closed, with its own distinct alert line (not "read").
    threads_df = pd.DataFrame([
        _thread_row("th1", 111, [
            _msg("member", "hi", "2026-10-01T08:00:00Z"),
            _msg("coach", "hello", "2026-10-01T09:00:00Z"),
        ]),
    ])
    fake = _WorkflowRaisingClient(threads_df)

    result = coach_inbox.load_member_questions(client=fake)

    assert len(result) == 1
    assert result.iloc[0]["status"] != "closed"
    assert coach_inbox.read_failed(result) is False  # the main read succeeded

    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1
    assert out[0] == (
        '{"severity": "ERROR", "message": '
        '"BTB_ALERT grant-helpdesk/coach-inbox SOURCE_FAILED: '
        'private_chat workflow read failed: RuntimeError"}'
    )


def test_load_member_questions_empty_tables_returns_empty_frame():
    # R4 (partial — the empty-tables half only; the error/alert half is A5):
    # no threads at all -> empty frame with the right columns, no crash.
    empty_threads = pd.DataFrame(
        columns=["thread_id", "member_id", "subject", "topic", "thread_created_at",
                 "messages", "full_name"]
    )
    fake = _FakeBigQueryClient(empty_threads)

    result = coach_inbox.load_member_questions(client=fake)

    assert result.empty
    assert list(result.columns) == [
        "content_id", "source", "member_id", "member_name", "topic",
        "subject", "created_at", "last_activity_at", "messages", "status",
    ]


# ── waiting_count / tickets_tab_label (A3) ──────────────────────────────────

def test_waiting_count_counts_only_waiting_rows():
    # R1: count of status == "waiting", ignoring answered rows.
    questions = pd.DataFrame([
        {"status": "waiting"}, {"status": "waiting"}, {"status": "waiting"},
        {"status": "answered"}, {"status": "answered"},
    ])
    assert coach_inbox.waiting_count(questions) == 3


def test_waiting_count_empty_frame_is_zero():
    assert coach_inbox.waiting_count(pd.DataFrame(columns=["status"])) == 0


def test_tickets_tab_label_shows_count_only_when_positive():
    # R2: "🎫 Tickets (N new)" when N > 0, plain "🎫 Tickets" otherwise.
    assert coach_inbox.tickets_tab_label(0) == "🎫 Tickets"
    assert coach_inbox.tickets_tab_label(3) == "🎫 Tickets (3 new)"


# ── report_source_failure / load_member_questions read failure (A5) ────────

class _RaisingBigQueryClient:
    """Stands in for a client whose query() fails outright — a bad
    credential, a missing dataset, a BigQuery outage — so
    load_member_questions's own error path can be proven without ever
    touching real BigQuery."""

    def query(self, sql, job_config=None):
        raise RuntimeError("could not reach BigQuery")


def test_report_source_failure_line_and_no_message_leak(capsys):
    # R1: exact BTB_ALERT line, naming the operation and the exception's own
    # type. R2: the exception's message never appears in it — it could be
    # quoting a member's own words back into a log a wider team reads.
    err = RuntimeError("member said: I need help paying rent")
    coach_inbox.report_source_failure("read", err)
    out = capsys.readouterr().out.strip()

    assert out == (
        '{"severity": "ERROR", "message": '
        '"BTB_ALERT grant-helpdesk/coach-inbox SOURCE_FAILED: '
        'private_chat read failed: RuntimeError"}'
    )
    assert "member said" not in out
    assert "rent" not in out


def test_load_member_questions_read_failure_returns_empty_frame_and_alerts(capsys):
    # R4 (error half): a client whose query() raises -> load_member_questions
    # never raises itself, returns an empty frame with the usual columns, and
    # logs exactly one BTB_ALERT SOURCE_FAILED line.
    fake = _RaisingBigQueryClient()

    result = coach_inbox.load_member_questions(client=fake)

    assert result.empty
    assert list(result.columns) == [
        "content_id", "source", "member_id", "member_name", "topic",
        "subject", "created_at", "last_activity_at", "messages", "status",
    ]

    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1
    assert out[0] == (
        '{"severity": "ERROR", "message": '
        '"BTB_ALERT grant-helpdesk/coach-inbox SOURCE_FAILED: '
        'private_chat read failed: RuntimeError"}'
    )


def test_read_failed_true_after_a_failure_and_false_after_a_success(capsys):
    # Finding 2: an empty frame from a failed read looks identical to an
    # empty frame from a genuinely-empty result, so app.py cannot show its
    # own st.error from the returned frame alone — it needs to ask
    # read_failed(frame) too.
    failed = coach_inbox.load_member_questions(client=_RaisingBigQueryClient())
    capsys.readouterr()  # drop the alert line, not this test's concern
    assert coach_inbox.read_failed(failed) is True

    empty_threads = pd.DataFrame(
        columns=["thread_id", "member_id", "subject", "topic", "thread_created_at",
                 "messages", "full_name"]
    )
    ok = coach_inbox.load_member_questions(client=_FakeBigQueryClient(empty_threads))
    assert coach_inbox.read_failed(ok) is False


def test_read_failed_is_carried_by_the_frame_not_a_shared_flag(capsys):
    # Re-review minor 1: a module-level flag, reset at the top of every
    # load_member_questions call, is wrong once app.py's @st.cache_data
    # wrapper means a cache HIT never re-runs this function — a later call's
    # outcome (by another session, or after cache.clear()) would silently
    # overwrite what an earlier call's own frame is still reporting. Proof:
    # a failed call's frame must still say so, even after a later, separate,
    # successful call has happened.
    failed_frame = coach_inbox.load_member_questions(client=_RaisingBigQueryClient())
    capsys.readouterr()

    empty_threads = pd.DataFrame(
        columns=["thread_id", "member_id", "subject", "topic", "thread_created_at",
                 "messages", "full_name"]
    )
    coach_inbox.load_member_questions(client=_FakeBigQueryClient(empty_threads))

    assert coach_inbox.read_failed(failed_frame) is True


# ── member_other_threads (coach-inbox-dialog-history) ───────────────────────
#
# Filters the already-loaded load_member_questions frame down to one
# member's other threads, for the Answer dialog's shared history panel — no
# BigQuery call of its own, so these fixtures are plain pandas, no fake
# client needed.

_QUESTIONS = pd.DataFrame([
    {"content_id": "pc:t1", "member_id": 42, "last_activity_at": "2026-09-20", "status": "waiting"},
    {"content_id": "pc:t2", "member_id": 42, "last_activity_at": "2026-09-25", "status": "answered"},
    {"content_id": "pc:t3", "member_id": 99, "last_activity_at": "2026-09-28", "status": "waiting"},
])


def test_member_other_threads_filters_to_one_member_and_excludes_the_open_thread():
    result = coach_inbox.member_other_threads(_QUESTIONS, 42, exclude_content_id="pc:t1")
    assert result["content_id"].tolist() == ["pc:t2"]


def test_member_other_threads_sorts_newest_activity_first():
    result = coach_inbox.member_other_threads(_QUESTIONS, 42, exclude_content_id="pc:nonexistent")
    assert result["content_id"].tolist() == ["pc:t2", "pc:t1"]


def test_member_other_threads_matches_across_int_and_string_member_id():
    # BigQuery's INT64 comes back through pandas as a Python int or a numpy
    # int64 depending on the column's null-ness — a caller passing either
    # must still match the other.
    result = coach_inbox.member_other_threads(_QUESTIONS, "42", exclude_content_id="pc:t1")
    assert result["content_id"].tolist() == ["pc:t2"]


def test_member_other_threads_on_empty_questions_returns_empty():
    result = coach_inbox.member_other_threads(pd.DataFrame(), 42, exclude_content_id="pc:t1")
    assert result.empty
