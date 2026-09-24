#!/usr/bin/env python3
"""
Cloud Run Job: poll_dataform_failures
Runs every hour. Checks all Dataform repositories for FAILED workflow invocations
since the last time this job ran, and writes one ERROR row per failure into
grant_helpdesk.app_logs — the same table the portal already uses for all errors.

Source field format: dataform.<repository-name>

app_logs is a BigQuery table nobody watches in real time, which is exactly
the kind of alert the global CLAUDE.md rule "Unattended code reports its own
failure" warns about — so any action named in ALERTED_ACTIONS (currently just
grant_ticket_labels, per the dedupe-ticket-tables brief) also gets a
raillog.alert() call and this job exits non-zero for the run that found it.
Every other action's failure still only reaches app_logs, same as before.
"""

import os
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timezone, timedelta

import requests
from google.auth import default
from google.auth.transport.requests import Request
from google.cloud import bigquery

import raillog

PROJECT     = os.environ.get("GOOGLE_CLOUD_PROJECT", "bigtribebuilders")
REGION      = os.environ.get("DATAFORM_REGION", "europe-west1")
LOGS_TABLE  = f"{PROJECT}.grant_helpdesk.app_logs"
LOOKBACK_H  = int(os.environ.get("LOOKBACK_HOURS", "2"))   # how far back to search

REPOSITORIES = [
    "grant-helpdesk",
    "community-manager-dashboard",
]

# Dataform actions that page someone when they fail, per the brief's
# "grant_ticket_labels's runnable has a BTB_ALERT alert" requirement. Add a
# name here to alert on it too — everything else still lands in app_logs as
# before, it just doesn't ring anyone's phone.
ALERTED_ACTIONS = {
    "grant_ticket_labels",
}

DATAFORM_BASE = f"https://dataform.googleapis.com/v1beta1/projects/{PROJECT}/locations/{REGION}/repositories"


def get_token() -> str:
    creds, _ = default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(Request())
    return creds.token


def last_logged_at(bq: bigquery.Client, repo: str) -> datetime:
    """Return the created_at of the most recent log row for this repo, or LOOKBACK_H ago."""
    source = f"dataform.{repo}"
    rows = list(bq.query(f"""
        SELECT MAX(created_at) AS last_at
        FROM `{LOGS_TABLE}`
        WHERE source = '{source}'
    """).result())
    if rows and rows[0]["last_at"]:
        return rows[0]["last_at"].replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_H)


def get_failed_invocations(token: str, repo: str, since: datetime) -> list[dict]:
    """Fetch FAILED workflow invocations for a repository created after `since`.

    Walks every page (`nextPageToken`) instead of stopping at the first 50:
    the Dataform API returns invocations in no time order, so a failure
    newer than `since` can land on any page, not just the first — reading
    one page only means the age of `since` decides nothing, the age of the
    invocations that happen to sort onto page 1 does. The per-invocation
    time filter itself is unchanged; only how many pages feed it changed.
    """
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{DATAFORM_BASE}/{repo}/workflowInvocations"
    failed = []
    page_token = None
    seen_tokens = set()
    while True:
        params = {"pageSize": 50}
        if page_token:
            params["pageToken"] = page_token
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        body = resp.json()

        for inv in body.get("workflowInvocations", []):
            if inv.get("state") != "FAILED":
                continue
            start_str = inv.get("invocationTiming", {}).get("startTime", "")
            if not start_str:
                continue
            start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            if start_dt <= since:
                continue
            failed.append({
                "inv_id":   inv["name"].split("/")[-1],
                "start_at": start_dt,
                "tags":     inv.get("invocationConfig", {}).get("includedTags", []),
            })

        page_token = body.get("nextPageToken")
        if not page_token:
            break
        if page_token in seen_tokens:
            # If the API ever repeats a nextPageToken, looping forever
            # would just run until Cloud Run's task timeout kills the job.
            # Raising sends it down the existing SOURCE_FAILED/exit-1 path
            # in main() instead (overseer review 2026-09-24, minor #3).
            raise RuntimeError(f"Dataform returned a repeated nextPageToken for {repo} — stopping")
        seen_tokens.add(page_token)
    return failed


def get_dataform_error(token: str, repo: str, inv_id: str) -> str:
    """Get the error reason from the Dataform invocation's failed actions."""
    url = (
        f"{DATAFORM_BASE}/{repo}/workflowInvocations/{inv_id}"
        f"?fields=invocationTiming,state"
    )
    # Try to fetch the first failed action's failureReason from the invocation detail.
    # Fall back gracefully — the inv_id in the log detail is enough for manual lookup.
    try:
        actions_url = f"{DATAFORM_BASE}/{repo}/workflowInvocations/{inv_id}"
        resp = requests.get(
            actions_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=15
        )
        if not resp.ok:
            return f"(Dataform API {resp.status_code})"
        # The invocation-level response doesn't embed action errors; that's fine.
        # Return a console link so the on-call engineer can click straight through.
        return (
            f"https://console.cloud.google.com/bigquery/dataform/locations/"
            f"{REGION}/repositories/{repo}/workflowInvocations/{inv_id}"
            f"?project={PROJECT}"
        )
    except Exception as e:
        return f"(could not fetch detail: {e})"


def get_failed_action_names(token: str, repo: str, inv_id: str) -> list[str]:
    """Return the target names of this invocation's actions that themselves FAILED.

    An invocation can report state=FAILED overall while only one action in it
    actually broke — this is how we tell whether THIS failure was
    grant_ticket_labels or something else in the same run. Like joining a
    child "actions" table on the parent invocation and filtering to the
    failed rows, except the join is a second API call, not a WHERE clause.

    Raises on any lookup failure instead of returning []. grant_ticket_labels
    only gets its BTB_ALERT because this function named it — a silent []
    here (the previous behaviour) would mean a real grant_ticket_labels
    failure never alerts anyone, which is exactly the "caught an error and
    exited 0" case the global CLAUDE.md rule forbids. The caller in main()
    lets this propagate up to the outer try/except, which turns it into a
    BTB_ALERT UNEXPECTED and a non-zero exit instead.
    """
    url = f"{DATAFORM_BASE}/{repo}/workflowInvocations/{inv_id}:query?pageSize=200"
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=15)
    resp.raise_for_status()
    actions = resp.json().get("workflowInvocationActions", [])
    return [
        a["target"]["name"]
        for a in actions
        if a.get("state") == "FAILED" and "target" in a
    ]


def log_failure(bq: bigquery.Client, repo: str, inv_id: str, start_at: datetime,
                tags: list, detail: str) -> None:
    tags_str = ", ".join(tags) if tags else "—"
    row = [{
        "log_id":     str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "level":      "ERROR",
        "source":     f"dataform.{repo}",
        "message":    f"Dataform invocation FAILED (tags: {tags_str})",
        "detail":     f"inv_id={inv_id} started={start_at.isoformat()} | {detail}",
    }]
    errors = bq.insert_rows_json(LOGS_TABLE, row)
    if errors:
        print(f"  [WARN] BQ insert error for log row: {errors}")


def summarize_alert_events(events: list[dict]) -> str:
    """Turn one action name's failures this run into a single alert message.

    Input: a list of `{"repo", "inv_id", "detail"}` dicts, one per failing
    invocation of that action. Output: one string naming the count and up
    to 5 of them by repo/invocation/detail, with the rest counted but not
    listed. Exists so a backlog of many failures for the same action pages
    someone once, with enough to act on, instead of flooding one email per
    row — the row-level detail still went to app_logs in full either way.
    """
    lines = [f"{e['repo']}/{e['inv_id']}: {e['detail']}" for e in events]
    shown = lines[:5]
    suffix = "" if len(lines) <= 5 else f" (+{len(lines) - 5} more)"
    return f"{len(events)} failure(s) — {'; '.join(shown)}{suffix}"


def main():
    bq    = bigquery.Client(project=PROJECT)
    token = get_token()

    total_logged     = 0
    alerted_events   = defaultdict(list)  # action name -> failures this run, for one alert per name
    any_fetch_failed = False  # a repo we couldn't even list invocations for, also for the exit code

    try:
        for repo in REPOSITORIES:
            print(f"\n--- {repo} ---")
            since = last_logged_at(bq, repo)
            print(f"Checking for failures since {since.isoformat()}")

            try:
                failed = get_failed_invocations(token, repo, since)
            except Exception as e:
                print(f"  [ERROR] Could not fetch invocations: {e}")
                # Was `continue` with only a print — the run then exited 0 and
                # nobody saw it. A repo we can't even list failures for is
                # itself something raillog.alert() exists to report.
                raillog.alert(
                    "poll_dataform_failures", "SOURCE_FAILED",
                    f"Could not fetch Dataform invocations for {repo}: {e}"
                )
                any_fetch_failed = True
                continue

            print(f"Found {len(failed)} new failure(s)")
            for inv in failed:
                detail = get_dataform_error(token, repo, inv["inv_id"])
                # Computed BEFORE log_failure: if this raises, this
                # invocation is never marked logged, so a raise on the
                # FIRST invocation of a repo's run does get re-checked next
                # run. But once any earlier invocation in this same run has
                # called log_failure, next run's watermark (last_logged_at)
                # has already moved to that row's created_at ("now"), not
                # this invocation's start_at — so a raise on a LATER
                # invocation does not get re-checked, it just needs a
                # manual look. Paging makes backlog runs larger, so this
                # matters more now than when the poller only ever saw page
                # 1 (known limit, overseer review 2026-09-24).
                failed_names = get_failed_action_names(token, repo, inv["inv_id"])

                log_failure(bq, repo, inv["inv_id"], inv["start_at"], inv["tags"], detail)
                print(f"  Logged: {inv['inv_id'][:20]}... | {detail[:80]}")
                total_logged += 1

                # Collected here, alerted once per name after the loop below —
                # a backlog run (e.g. the first run after a paging fix) can
                # have many failures for the same action, and Martin's
                # decision is one summary BTB_ALERT for that action, not one
                # per failure. Every failure still gets its own app_logs row
                # above regardless of this grouping.
                for name in ALERTED_ACTIONS.intersection(failed_names):
                    alerted_events[name].append({"repo": repo, "inv_id": inv["inv_id"], "detail": detail})
    finally:
        # In `finally`, not after the loop: if something above raises
        # (e.g. get_failed_action_names on a later invocation), the
        # alerts collected for invocations already logged this run must
        # still go out — those invocations already moved the watermark via
        # log_failure, so a dropped alert here means nobody is ever told
        # about them (blocker, overseer review 2026-09-24). The exception
        # itself is not caught here, so it still propagates and the run
        # still ends non-zero either way.
        for name, events in alerted_events.items():
            raillog.alert(name, "SOURCE_FAILED", summarize_alert_events(events))

    print(f"\nDone — {total_logged} failure(s) logged to app_logs.")
    if alerted_events:
        print(f"[ALERT] {len(alerted_events)} alerted action(s) with failures: {', '.join(alerted_events)}")
    if alerted_events or any_fetch_failed:
        sys.exit(1)  # failure looks like failure — see the global CLAUDE.md rule


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Anything that escapes main() (get_token, the BQ query,
        # get_failed_action_names, ...) still exits non-zero on its own —
        # this adds the BTB_ALERT line that a plain traceback doesn't carry,
        # then re-raises so the exit code and the traceback are unchanged.
        raillog.alert("poll_dataform_failures", "UNEXPECTED", repr(e))
        raise
