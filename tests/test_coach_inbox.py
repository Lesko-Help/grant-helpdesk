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
    sends two queries (threads+messages, then core_members names) — this
    routes each to its canned frame by sniffing the SQL text, since a fake
    has no real tables to query against."""

    def __init__(self, threads_df, names_df):
        self._threads_df = threads_df
        self._names_df = names_df
        self.queries = []

    def query(self, sql, job_config=None):
        self.queries.append(sql)
        if "core_members" in sql:
            return _FakeQueryResult(self._names_df)
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
        },
    ])
    names_df = pd.DataFrame([{"member_id": 111, "full_name": "Carol Smith"}])
    fake = _FakeBigQueryClient(threads_df, names_df)

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


def test_load_member_questions_empty_tables_returns_empty_frame():
    # R4 (partial — the empty-tables half only; the error/alert half is A5):
    # no threads at all -> empty frame with the right columns, no crash.
    empty_threads = pd.DataFrame(
        columns=["thread_id", "member_id", "subject", "topic", "thread_created_at", "messages"]
    )
    empty_names = pd.DataFrame(columns=["member_id", "full_name"])
    fake = _FakeBigQueryClient(empty_threads, empty_names)

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
    # read_failed() too.
    coach_inbox.load_member_questions(client=_RaisingBigQueryClient())
    capsys.readouterr()  # drop the alert line, not this test's concern
    assert coach_inbox.read_failed() is True

    empty_threads = pd.DataFrame(
        columns=["thread_id", "member_id", "subject", "topic", "thread_created_at", "messages"]
    )
    empty_names = pd.DataFrame(columns=["member_id", "full_name"])
    coach_inbox.load_member_questions(client=_FakeBigQueryClient(empty_threads, empty_names))
    assert coach_inbox.read_failed() is False
