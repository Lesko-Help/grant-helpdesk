#!/usr/bin/env python3
"""Payload builders for jobs/deploy-alerts.sh's new metric-based BTB_ALERT policy.

Pulled out of the bash heredoc so tests/test_deploy_alerts_payloads.py can
check the JSON shape without gcloud credentials or a network call — same
split lesko-provisioning/scripts/dataform_lane_alert_payloads.py uses for its
own alert payloads.

deploy-alerts.sh never builds this JSON itself; it always calls this file's
CLI form (below) and captures stdout, the same round-trip curl -d "$(...)"
already does elsewhere in that script. One code path, both from bash and
from the test.

Run directly to print one payload to stdout:
  python3 jobs/alert_payloads.py metric-filter poll-dataform-failures
  python3 jobs/alert_payloads.py threshold-policy TITLE poll-dataform-failures \
      bigtribebuilders CHANNEL METRIC_NAME
"""

import json
import sys


def metric_log_filter(job):
    """Input: a Cloud Run job name. Output: the Cloud Logging filter string
    that selects its BTB_ALERT lines. Why: gcloud logging metrics create
    needs this exact string, and the existing log-match policy already
    proved it selects the right lines — reusing it keeps the new metric
    counting the same events the old policy pages on.
    """
    return (
        f'resource.type="cloud_run_job" AND resource.labels.job_name="{job}" '
        'AND (textPayload:"BTB_ALERT" OR jsonPayload.message:"BTB_ALERT")'
    )


def log_match_policy(title, job, project, channel):
    """Input: display title, job name, GCP project, and a notification
    channel's resource name. Output: the AlertPolicy dict for the original
    conditionMatchedLog (log-based) policy that pages the instant a
    BTB_ALERT line appears, ready to json.dumps into the Monitoring API's
    create/patch body. Why: this used to be built inline in
    deploy-alerts.sh's heredoc, where a stray
    alertStrategy.notificationChannelStrategy went unnoticed for a whole
    review round (round-3 review blocker #1) because nothing checked the
    payload's shape offline. Pulling it in here next to threshold_policy()
    means both policies' shapes are covered by the same tests, and a
    regression like blocker #1 fails a test instead of only failing live
    under set -euo pipefail.
    """
    content = (
        f"{job} called raillog.alert() (jobs/raillog.py). Codes: AUTH_FAILED, "
        "SOURCE_FAILED, SOURCE_EMPTY, ASSERTION_FAILED, QUOTA, STALE, "
        "UNEXPECTED — the code is in the message itself.\n\n"
        "As of 2026-09-23 the only action wired into ALERTED_ACTIONS is "
        "grant_ticket_labels (jobs/poll_dataform_failures.py) — this alert "
        "means that Dataform action failed, not any other action in "
        "grant-helpdesk or community-manager-dashboard.\n\n"
        "Read the full line in Cloud Logging:\n"
        f"  gcloud logging read 'resource.type=\"cloud_run_job\" AND "
        f'resource.labels.job_name="{job}" AND (textPayload:"BTB_ALERT" '
        f"OR jsonPayload.message:\"BTB_ALERT\")' --project {project} --limit 5\n\n"
        "The message names the Dataform invocation id and a console link — "
        "open it to see which grant_ticket_labels row(s) failed."
    )
    return {
        "displayName": title,
        "documentation": {
            "subject": title,
            "content": content,
            "mimeType": "text/markdown",
        },
        "conditions": [{
            "displayName": "a BTB_ALERT line appeared in the job logs",
            "conditionMatchedLog": {
                "filter": metric_log_filter(job),
            },
        }],
        "combiner": "OR",
        "enabled": True,
        "alertStrategy": {
            # notificationChannelStrategy does NOT belong here — Monitoring
            # rejects it outright on a conditionMatchedLog (log-based)
            # policy ("notificationChannelStrategy is not allowed for
            # log-based alerts", confirmed live 2026-09-24, see
            # docs/briefs/alert-renotify-metric.md). A prior review round
            # put it here anyway, which broke deploy-alerts.sh under
            # set -euo pipefail before it ever reached the metric/threshold
            # code (round-3 review blocker #1). The 24h renotify lives on
            # the separate conditionThreshold policy from threshold_policy()
            # instead, which is the only kind Monitoring allows that field
            # on. test_log_match_policy_has_no_notification_channel_strategy
            # below guards against this coming back.
            "notificationRateLimit": {"period": "1800s"},
            "autoClose": "604800s",
        },
        "notificationChannels": [channel],
    }


def threshold_policy(title, job, project, channel, metric_name):
    """Input: display title, job name, GCP project, a notification channel's
    resource name, and the log metric's name. Output: the AlertPolicy dict
    for a conditionThreshold policy on that metric, ready to json.dumps into
    the Monitoring API's create/patch body. Why: a conditionThreshold
    (metric) policy is the only kind Monitoring lets carry
    alertStrategy.notificationChannelStrategy — a conditionMatchedLog
    (log-match) policy rejects that field outright (confirmed live against
    this project 2026-09-24, see docs/briefs/alert-renotify-metric.md,
    Context). This is the one thing that gets grant-helpdesk the 24h
    re-notify global CLAUDE.md rule 3 requires.
    """
    content = (
        f"{job} logged one or more BTB_ALERT lines in the last 24 hours "
        f"(metric logging.googleapis.com/user/{metric_name}). This is the "
        "renotifying twin of the older log-match policy on the same job — "
        "see docs/briefs/alert-renotify-metric.md for why both exist until "
        "this one is proven to fire.\n\n"
        "Read the full line in Cloud Logging:\n"
        f"  gcloud logging read 'resource.type=\"cloud_run_job\" AND "
        f'resource.labels.job_name="{job}" AND (textPayload:"BTB_ALERT" '
        f"OR jsonPayload.message:\"BTB_ALERT\")' --project {project} --limit 5"
    )
    return {
        "displayName": title,
        "documentation": {
            "subject": title,
            "content": content,
            "mimeType": "text/markdown",
        },
        "conditions": [{
            "displayName": "the BTB_ALERT metric rose above 0",
            "conditionThreshold": {
                # resource.type is NOT optional here even though the metric's
                # own log-filter already scopes to cloud_run_job — Monitoring
                # rejects a conditionThreshold filter with no resource.type
                # restriction of its own (trap already hit and documented in
                # lesko-provisioning/deploy-alerts.sh's rail_alert_by_code
                # policy).
                "filter": (
                    f'metric.type="logging.googleapis.com/user/{metric_name}" '
                    'AND resource.type="cloud_run_job"'
                ),
                "comparison": "COMPARISON_GT",
                "thresholdValue": 0,
                "duration": "0s",
                # alignmentPeriod 86400s (24h), not 60s: this metric is a
                # DELTA counter under ALIGN_SUM, so once BTB_ALERT lines stop
                # a 60s window reports a genuine 0 — not missing data, a real
                # zero — and the incident auto-resolves within about a
                # minute of the last log line, before the 24h renotify ever
                # gets a chance to fire (round-3 review, blocker #2). A 24h
                # rolling sum stays >0 for a full day after even one line,
                # which is what "renotifies every 24h" actually needs. GCP's
                # documented max alignment period is about 25h minus the
                # metric's own ingestion delay, so 86400s (24h) fits safely
                # under it (Cloud Monitoring aggregation docs, fetched
                # 2026-09-24).
                "evaluationMissingData": "EVALUATION_MISSING_DATA_NO_OP",
                "aggregations": [{
                    "alignmentPeriod": "86400s",
                    "perSeriesAligner": "ALIGN_SUM",
                    "crossSeriesReducer": "REDUCE_SUM",
                }],
            },
        }],
        "combiner": "OR",
        "enabled": True,
        "alertStrategy": {
            # No notificationRateLimit here: Monitoring accepts that field
            # ONLY on log-based (conditionMatchedLog) policies and rejects
            # the whole create/patch otherwise — the mirror-image trap of
            # the one that blocked notificationChannelStrategy on the
            # log-match policy above. Same avoidance documented next to
            # lesko-provisioning/deploy-alerts.sh's own conditionThreshold
            # policy.
            "autoClose": "604800s",
            "notificationChannelStrategy": [{
                "notificationChannelNames": [channel],
                "renotifyInterval": "86400s",
            }],
        },
        "notificationChannels": [channel],
    }


def _main(argv):
    """Input: argv (sys.argv). Output: process exit code. Why: gives
    deploy-alerts.sh a stable CLI so both it and the offline test call the
    exact same payload-building code — see module docstring.
    """
    if len(argv) < 2:
        sys.stderr.write(
            "usage: alert_payloads.py metric-filter JOB\n"
            "       alert_payloads.py log-match-policy TITLE JOB PROJECT CHANNEL\n"
            "       alert_payloads.py threshold-policy TITLE JOB PROJECT CHANNEL METRIC_NAME\n"
        )
        return 1
    kind = argv[1]
    if kind == "metric-filter" and len(argv) == 3:
        print(metric_log_filter(argv[2]))
    elif kind == "log-match-policy" and len(argv) == 6:
        title, job, project, channel = argv[2:6]
        print(json.dumps(log_match_policy(title, job, project, channel)))
    elif kind == "threshold-policy" and len(argv) == 7:
        title, job, project, channel, metric_name = argv[2:7]
        print(json.dumps(threshold_policy(title, job, project, channel, metric_name)))
    else:
        sys.stderr.write(f"bad arguments for kind {kind!r}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
