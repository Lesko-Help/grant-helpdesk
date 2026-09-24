"""
Offline proof for jobs/poll_dataform_failures.py's poller-paging fix:
walking every workflowInvocations page instead of stopping at page 1, and
collapsing a run's alerted failures for one action into a single BTB_ALERT
instead of one per failure (docs/briefs/poller-paging.md).

Nothing here reaches live Dataform or BigQuery — requests.get, the
BigQuery client, and raillog.alert are all faked. This file never imports
bq_writes, so it does not hit the 2026-08-19 live-Dataform trap that
bq_writes.trigger_assignment_refresh causes in other test files.

Run with: /opt/anaconda3/bin/pytest tests/test_poll_dataform_failures.py
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(REPO_ROOT, "jobs"))

import poll_dataform_failures as poller  # noqa: E402


class FakeResponse:
    """Stands in for requests.Response: only the bits the poller reads."""

    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.ok = status_code < 400

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class FakeBigQuery:
    """Stands in for google.cloud.bigquery.Client: records inserted rows, never queries."""

    def __init__(self, *args, **kwargs):
        self.inserted_rows = []

    def insert_rows_json(self, table, rows):
        self.inserted_rows.extend(rows)
        return []  # no insert errors


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def invocation(inv_id: str, state: str, start_dt: datetime) -> dict:
    return {
        "name": f"projects/p/locations/r/repositories/repo/workflowInvocations/{inv_id}",
        "state": state,
        "invocationTiming": {"startTime": iso(start_dt)},
        "invocationConfig": {"includedTags": []},
    }


SINCE = datetime(2026, 5, 20, 10, 40, tzinfo=timezone.utc)  # the real watermark per the overseer's memory


# ── get_failed_invocations: pagination ──────────────────────────────────────

def test_get_failed_invocations_follows_pagination(monkeypatch):
    # Three pages, unordered in time. FAILED invocations sit on all three —
    # today's page-1-only code (pageSize=50, no nextPageToken loop) would
    # only ever see page 1's failure, so this is red before the fix.
    page1 = {
        "workflowInvocations": [
            invocation("before-watermark", "FAILED", SINCE - timedelta(hours=1)),  # excluded: <= since
            invocation("page1-ok", "SUCCEEDED", SINCE + timedelta(hours=1)),
        ],
        "nextPageToken": "tok-2",
    }
    page2 = {
        "workflowInvocations": [
            invocation("page2-failure", "FAILED", SINCE + timedelta(days=60)),  # newer, sorts onto page 2
        ],
        "nextPageToken": "tok-3",
    }
    page3 = {
        "workflowInvocations": [
            invocation("page3-failure", "FAILED", SINCE + timedelta(days=30)),  # older than page2's, still on page 3
        ],
        # no nextPageToken: last page
    }

    calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        # params, not a hand-glued query string — a token containing "+",
        # "/" or "&" is passed through requests' own encoding this way
        # (overseer review 2026-09-24, minor #2).
        calls.append(params.get("pageToken"))
        if params.get("pageToken") == "tok-3":
            return FakeResponse(page3)
        if params.get("pageToken") == "tok-2":
            return FakeResponse(page2)
        assert "pageToken" not in params
        return FakeResponse(page1)

    monkeypatch.setattr(poller.requests, "get", fake_get)

    failed = poller.get_failed_invocations("tok", "repo", SINCE)

    assert {f["inv_id"] for f in failed} == {"page2-failure", "page3-failure"}
    assert len(calls) == 3, "must fetch all three pages, not just the first"


def test_get_failed_invocations_stops_when_a_page_has_no_next_token(monkeypatch):
    single_page = {
        "workflowInvocations": [invocation("only-one", "FAILED", SINCE + timedelta(hours=1))],
        # no nextPageToken
    }
    calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append(params)
        return FakeResponse(single_page)

    monkeypatch.setattr(poller.requests, "get", fake_get)

    failed = poller.get_failed_invocations("tok", "repo", SINCE)

    assert [f["inv_id"] for f in failed] == ["only-one"]
    assert len(calls) == 1


def test_get_failed_invocations_raises_on_a_repeated_page_token(monkeypatch):
    # Overseer review 2026-09-24, minor #3: nothing stopped a runaway loop
    # if the API ever repeated a nextPageToken. Raising sends it down the
    # existing SOURCE_FAILED/exit-1 path instead of looping until Cloud
    # Run's task timeout kills the job.
    looping_page = {"workflowInvocations": [], "nextPageToken": "tok-1"}

    def fake_get(url, headers=None, params=None, timeout=None):
        return FakeResponse(looping_page)

    monkeypatch.setattr(poller.requests, "get", fake_get)

    with pytest.raises(RuntimeError):
        poller.get_failed_invocations("tok", "repo", SINCE)


# ── main(): one summary alert per action, not one per failure ──────────────

def test_main_sends_one_summary_alert_not_one_per_failure(monkeypatch):
    # The shape of the first fixed run: a backlog of grant_ticket_labels
    # failures piled up since the watermark, all found once paging works.
    backlog_page = {
        "workflowInvocations": [
            invocation("backlog-1", "FAILED", SINCE + timedelta(days=10)),
            invocation("backlog-2", "FAILED", SINCE + timedelta(days=20)),
            invocation("backlog-3", "FAILED", SINCE + timedelta(days=30)),
        ],
    }
    action_names_response = {
        "workflowInvocationActions": [
            {"state": "FAILED", "target": {"name": "grant_ticket_labels"}},
        ]
    }

    def fake_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/workflowInvocations"):
            return FakeResponse(backlog_page)
        if url.endswith(":query?pageSize=200"):
            return FakeResponse(action_names_response)
        return FakeResponse({}, 200)  # get_dataform_error's detail fetch

    alert_calls = []

    monkeypatch.setattr(poller, "REPOSITORIES", ["grant-helpdesk"])
    monkeypatch.setattr(poller.requests, "get", fake_get)
    monkeypatch.setattr(poller, "get_token", lambda: "tok")
    monkeypatch.setattr(poller, "last_logged_at", lambda bq, repo: SINCE)
    monkeypatch.setattr(poller.bigquery, "Client", FakeBigQuery)
    monkeypatch.setattr(poller.raillog, "alert", lambda *a: alert_calls.append(a))

    with pytest.raises(SystemExit) as exc:
        poller.main()

    assert exc.value.code == 1
    assert len(alert_calls) == 1, "one summary alert for the whole backlog, not one per failure"
    runnable, code, message = alert_calls[0]
    assert runnable == "grant_ticket_labels"
    assert code == "SOURCE_FAILED"
    assert "3 failure(s)" in message
    for inv_id in ("backlog-1", "backlog-2", "backlog-3"):
        assert inv_id in message


def test_main_still_logs_every_backlog_failure_to_app_logs(monkeypatch):
    # Grouping the alert must not drop the per-failure app_logs rows —
    # those are what the portal's error view actually reads.
    backlog_page = {
        "workflowInvocations": [
            invocation("row-1", "FAILED", SINCE + timedelta(days=10)),
            invocation("row-2", "FAILED", SINCE + timedelta(days=20)),
        ],
    }
    action_names_response = {"workflowInvocationActions": []}  # not an alerted action

    def fake_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/workflowInvocations"):
            return FakeResponse(backlog_page)
        if url.endswith(":query?pageSize=200"):
            return FakeResponse(action_names_response)
        return FakeResponse({}, 200)

    inserted = []
    fake_bq_instances = []

    class TrackedFakeBigQuery(FakeBigQuery):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            fake_bq_instances.append(self)

    monkeypatch.setattr(poller, "REPOSITORIES", ["grant-helpdesk"])
    monkeypatch.setattr(poller.requests, "get", fake_get)
    monkeypatch.setattr(poller, "get_token", lambda: "tok")
    monkeypatch.setattr(poller, "last_logged_at", lambda bq, repo: SINCE)
    monkeypatch.setattr(poller.bigquery, "Client", TrackedFakeBigQuery)
    monkeypatch.setattr(poller.raillog, "alert", lambda *a: None)

    poller.main()  # no alerted actions here, so no sys.exit(1)

    assert len(fake_bq_instances[0].inserted_rows) == 2


def test_main_sends_grouped_alert_even_when_a_later_invocation_raises(monkeypatch):
    # Overseer review 2026-09-24, blocker #1: alerts were held in
    # alerted_events until after the whole repo loop finished, so an
    # exception partway through the loop (e.g. get_failed_action_names
    # failing on a later invocation) dropped every alert collected so far —
    # even though the earlier invocations were already logged to app_logs,
    # which moves next run's watermark past them. "first" alerts here;
    # "second" makes get_failed_action_names raise. The grouped alert for
    # "first" must still go out, and the exception must still propagate
    # (so the run still exits non-zero and __main__'s UNEXPECTED handler
    # still fires) — main() must not swallow it.
    backlog_page = {
        "workflowInvocations": [
            invocation("first", "FAILED", SINCE + timedelta(days=10)),
            invocation("second", "FAILED", SINCE + timedelta(days=20)),
        ],
    }

    def fake_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/workflowInvocations"):
            return FakeResponse(backlog_page)
        return FakeResponse({}, 200)  # get_dataform_error's detail fetch

    def fake_get_failed_action_names(token, repo, inv_id):
        if inv_id == "first":
            return ["grant_ticket_labels"]
        raise RuntimeError("dataform hiccup")

    alert_calls = []

    monkeypatch.setattr(poller, "REPOSITORIES", ["grant-helpdesk"])
    monkeypatch.setattr(poller.requests, "get", fake_get)
    monkeypatch.setattr(poller, "get_token", lambda: "tok")
    monkeypatch.setattr(poller, "last_logged_at", lambda bq, repo: SINCE)
    monkeypatch.setattr(poller, "get_failed_action_names", fake_get_failed_action_names)
    monkeypatch.setattr(poller.bigquery, "Client", FakeBigQuery)
    monkeypatch.setattr(poller.raillog, "alert", lambda *a: alert_calls.append(a))

    with pytest.raises(RuntimeError):
        poller.main()

    assert len(alert_calls) == 1, "the earlier grouped alert must still be sent even though a later invocation raised"
    runnable, code, message = alert_calls[0]
    assert runnable == "grant_ticket_labels"
    assert code == "SOURCE_FAILED"
    assert "first" in message


# ── existing behaviour must not regress: a fetch failure still alerts and exits non-zero ──

def test_fetch_failure_still_alerts_and_exits_nonzero(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        raise RuntimeError("network down")

    alert_calls = []

    monkeypatch.setattr(poller, "REPOSITORIES", ["grant-helpdesk"])
    monkeypatch.setattr(poller.requests, "get", fake_get)
    monkeypatch.setattr(poller, "get_token", lambda: "tok")
    monkeypatch.setattr(poller, "last_logged_at", lambda bq, repo: SINCE)
    monkeypatch.setattr(poller.bigquery, "Client", FakeBigQuery)
    monkeypatch.setattr(poller.raillog, "alert", lambda *a: alert_calls.append(a))

    with pytest.raises(SystemExit) as exc:
        poller.main()

    assert exc.value.code == 1
    assert any(code == "SOURCE_FAILED" for _, code, _ in alert_calls)
