"""Offline proof for jobs/watch_disconnects.py — the arithmetic that turns a
request log into "how often did a coach lose her screen".

Nothing here reaches Google: every row is synthetic, built by the helpers
below in the exact shape Cloud Logging hands back. The one function that does
talk to the API (fetch_entries) is not exercised; what is pinned instead is
the filter string it would send, because a filter that quietly selects the
wrong log is the single failure this job could not notice about itself.

Run with: /opt/anaconda3/bin/python3 -m pytest tests/test_watch_disconnects.py
Never bare `pytest tests/` — tests/smoke_test.py writes to live BigQuery.
"""

import datetime as dt
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(REPO_ROOT, "jobs"))

import watch_disconnects as watcher  # noqa: E402

START = dt.datetime(2026, 10, 14, 9, 0, tzinfo=dt.timezone.utc)


def row(offset_seconds, lived_seconds, client="10.0.0.1", instance="inst-a",
        path="_stcore/stream", latency_as_text=True):
    """In: when the socket opened (seconds after START), how long it lived,
    and who owned it. Out: one log entry shaped like Cloud Logging's.
    Why: every test below is a sentence about gaps between sockets, and this
    keeps that sentence readable instead of burying it in payload shape."""
    latency = f"{lived_seconds:.6f}s" if latency_as_text else lived_seconds
    return {
        "timestamp": (START + dt.timedelta(seconds=offset_seconds)).isoformat(),
        "httpRequest": {
            "requestUrl": f"https://grant-helpdesk.example.run.app/{path}",
            "latency": latency,
            "remoteIp": client,
        },
        "labels": {"instanceId": instance},
    }


def sessions_from(rows):
    """In: log entries. Out: the parsed sessions. Why: a one-word shorthand
    used by nearly every test here."""
    return watcher.websocket_sessions(rows)


# ── reading the log ──────────────────────────────────────────────────────

def test_only_websocket_requests_count():
    """Health checks and static files share the log and must not be mistaken
    for a coach's session."""
    rows = [
        row(0, 60),
        row(10, 0.004, path="_stcore/health"),
        row(20, 0.019, path="static/js/index.js"),
    ]
    assert len(sessions_from(rows)) == 1


def test_latency_reads_as_text_or_as_a_number():
    """The REST payload spells a duration '60.006s'; the Python client hands
    back a number. Both are fed to this job, so both must parse."""
    as_text = sessions_from([row(0, 60, latency_as_text=True)])[0]
    as_number = sessions_from([row(0, 60, latency_as_text=False)])[0]
    assert as_text.seconds == as_number.seconds == 60


def test_nanosecond_timestamps_are_not_dropped():
    """Cloud Logging writes nanoseconds; datetime.fromisoformat takes
    microseconds. The extra digits must be trimmed, not cost us the row."""
    entry = {
        "timestamp": "2026-10-14T09:00:00.481320123Z",
        "httpRequest": {"requestUrl": "https://x/_stcore/stream",
                        "latency": "60s", "remoteIp": "10.0.0.1"},
        "labels": {},
    }
    assert len(sessions_from([entry])) == 1


# ── the one number that matters: a lost session ──────────────────────────

def test_a_gap_longer_than_the_ttl_is_a_lost_session():
    """Socket dies at 09:01:00, the browser comes back 20 minutes later. With
    a 900s TTL the session was already deleted: she lost her screen."""
    rows = [row(0, 60), row(60 + 1200, 60)]
    summary = watcher.summarise(sessions_from(rows), ttl_seconds=900)
    assert summary["total_resets"] == 1


def test_a_gap_inside_the_ttl_costs_her_nothing():
    """Same drop, back in 10 minutes, 900s TTL — the session is still there,
    so this is a flicker and not a reset."""
    rows = [row(0, 60), row(60 + 600, 60)]
    summary = watcher.summarise(sessions_from(rows), ttl_seconds=900)
    assert summary["total_resets"] == 0


def test_the_ttl_is_the_whole_difference():
    """The invariant this branch rests on. The identical day — eight drops,
    each 5 minutes away from the desk — is eight lost sessions on Streamlit's
    120s default and none on the 900s this repo now deploys. If this ever
    goes red, raising the TTL stopped being the fix.
    """
    rows = []
    when = 0
    for _ in range(9):
        rows.append(row(when, 60))
        when += 60 + 300  # socket lives a minute, she is away five
    sessions = sessions_from(rows)
    assert watcher.summarise(sessions, ttl_seconds=120)["total_resets"] == 8
    assert watcher.summarise(sessions, ttl_seconds=900)["total_resets"] == 0


def test_two_tabs_open_at_once_are_not_a_lost_session():
    """Overlapping sockets give a negative gap. A coach with the ticket list
    in one tab and a thread in another has lost nothing."""
    rows = [row(0, 600), row(30, 600)]
    summary = watcher.summarise(sessions_from(rows), ttl_seconds=900)
    assert summary["total_resets"] == 0


def test_each_coach_is_counted_on_her_own():
    """Two clients' sockets interleave in one log. A gap is only a gap
    between two sockets of the *same* client — otherwise a busy desk would
    hide every reset."""
    rows = [
        row(0, 60, client="10.0.0.1"),
        row(30, 60, client="10.0.0.2"),
        row(60 + 1200, 60, client="10.0.0.1"),
        row(90 + 1200, 60, client="10.0.0.2"),
    ]
    summary = watcher.summarise(sessions_from(rows), ttl_seconds=900)
    assert summary["clients"]["10.0.0.1"]["resets"] == 1
    assert summary["clients"]["10.0.0.2"]["resets"] == 1
    assert summary["total_resets"] == 2


def test_resets_per_day_divides_by_days_actually_seen():
    """A coach who was only at her desk one day of the window must not have
    her rate diluted by six days she never logged in."""
    rows = [row(0, 60), row(60 + 1200, 60), row(120 + 2400, 60)]
    summary = watcher.summarise(sessions_from(rows), ttl_seconds=900)
    assert summary["clients"]["10.0.0.1"]["days_seen"] == 1
    assert summary["clients"]["10.0.0.1"]["resets_per_day"] == 2.0


# ── telling a flaky line from a closed tab ───────────────────────────────

def test_a_socket_dying_on_the_30s_ping_clock_is_counted_apart():
    """Streamlit closes a socket 30s after a missing pong, so a life that is
    an exact multiple of 30s means the network went quiet under it. A coach
    closing her laptop lid at an arbitrary moment does not."""
    rows = [row(0, 60), row(300, 150), row(600, 137.4)]
    summary = watcher.summarise(sessions_from(rows), ttl_seconds=900)
    assert summary["clients"]["10.0.0.1"]["ping_clock_drops"] == 2


# ── when Martin hears about it ───────────────────────────────────────────

def _summary_with_rate(rate):
    """In: a resets-per-day rate. Out: a summary carrying it. Why: verdict()
    reads only a few fields, and building them directly keeps the threshold
    tests about the threshold."""
    return {
        "ttl_seconds": 900,
        "clients": {"10.0.0.1": {}},
        "total_sessions": 100,
        "total_resets": int(rate * 7),
        "worst_client": "10.0.0.1",
        "worst_resets_per_day": rate,
    }


def test_over_the_agreed_rate_raises_an_alert():
    should_alert, message = watcher.verdict(_summary_with_rate(12.0),
                                            max_resets_per_day=5.0)
    assert should_alert
    assert "losing sessions faster than" in message


def test_at_the_agreed_rate_it_stays_quiet():
    """Strictly greater, not greater-or-equal: the threshold is the rate we
    agreed to live with, so meeting it is not news."""
    should_alert, _ = watcher.verdict(_summary_with_rate(5.0),
                                      max_resets_per_day=5.0)
    assert not should_alert


def test_the_review_window_reports_even_when_all_is_well():
    """The guaranteed review mail: Martin asked to hear once, a week after
    landing, whether the fix held — not only if it did not."""
    should_alert, message = watcher.verdict(_summary_with_rate(0.0),
                                            max_resets_per_day=5.0,
                                            report_always=True)
    assert should_alert
    assert "weekly review" in message


def test_the_review_window_closes_by_itself():
    """REPORT_ALWAYS_UNTIL is a date, not a flag, so nobody has to remember
    to switch the weekly mail off again."""
    until = "2026-10-24"
    assert watcher.reporting_always(dt.date(2026, 10, 23), until)
    assert not watcher.reporting_always(dt.date(2026, 10, 24), until)
    assert not watcher.reporting_always(dt.date(2026, 11, 1), until)


def test_an_unreadable_review_date_reports_rather_than_goes_quiet():
    """A typo in the env var must not be the reason a rail goes silent."""
    assert watcher.reporting_always(dt.date(2026, 10, 23), "next thursday")
    assert not watcher.reporting_always(dt.date(2026, 10, 23), "")


# ── the one thing the job cannot notice about itself ─────────────────────

def test_the_log_filter_selects_this_service_s_websockets_only():
    """A filter that drifts returns rows that parse fine and mean nothing, so
    it is pinned here rather than trusted."""
    now = dt.datetime(2026, 10, 16, 12, 0, tzinfo=dt.timezone.utc)
    built = watcher.log_filter("bigtribebuilders", "grant-helpdesk", 7, now=now)
    assert 'logName="projects/bigtribebuilders/logs/run.googleapis.com%2Frequests"' in built
    assert 'resource.labels.service_name="grant-helpdesk"' in built
    assert 'httpRequest.requestUrl:"_stcore/stream"' in built
    assert 'timestamp>="2026-10-09T12:00:00Z"' in built
