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
    """Fetch FAILED workflow invocations for a repository created after `since`."""
    url = f"{DATAFORM_BASE}/{repo}/workflowInvocations?pageSize=50"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    invocations = resp.json().get("workflowInvocations", [])

    failed = []
    for inv in invocations:
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
    Best-effort: an empty list here just means we couldn't narrow it down, not
    that nothing failed.
    """
    url = f"{DATAFORM_BASE}/{repo}/workflowInvocations/{inv_id}:query?pageSize=200"
    try:
        resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=15)
        if not resp.ok:
            return []
        actions = resp.json().get("workflowInvocationActions", [])
        return [
            a["target"]["name"]
            for a in actions
            if a.get("state") == "FAILED" and "target" in a
        ]
    except Exception:
        return []


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


def main():
    bq    = bigquery.Client(project=PROJECT)
    token = get_token()

    total_logged  = 0
    alerted_names = []  # ALERTED_ACTIONS members seen failing this run, for the exit code

    for repo in REPOSITORIES:
        print(f"\n--- {repo} ---")
        since = last_logged_at(bq, repo)
        print(f"Checking for failures since {since.isoformat()}")

        try:
            failed = get_failed_invocations(token, repo, since)
        except Exception as e:
            print(f"  [ERROR] Could not fetch invocations: {e}")
            continue

        print(f"Found {len(failed)} new failure(s)")
        for inv in failed:
            detail = get_dataform_error(token, repo, inv["inv_id"])
            log_failure(bq, repo, inv["inv_id"], inv["start_at"], inv["tags"], detail)
            print(f"  Logged: {inv['inv_id'][:20]}... | {detail[:80]}")
            total_logged += 1

            failed_names = get_failed_action_names(token, repo, inv["inv_id"])
            for name in ALERTED_ACTIONS.intersection(failed_names):
                raillog.alert(
                    name, "SOURCE_FAILED",
                    f"Dataform action failed in {repo}, invocation {inv['inv_id']}: {detail}"
                )
                alerted_names.append(name)

    print(f"\nDone — {total_logged} failure(s) logged to app_logs.")
    if alerted_names:
        print(f"[ALERT] {len(alerted_names)} alerted action failure(s): {', '.join(alerted_names)}")
        sys.exit(1)  # failure looks like failure — see the global CLAUDE.md rule


if __name__ == "__main__":
    main()
