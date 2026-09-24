"""
Offline proof for jobs/alert_payloads.py's new metric-threshold BTB_ALERT
policy — the payload jobs/deploy-alerts.sh sends to Cloud Monitoring for
poll-dataform-failures' 24h-renotifying alert (alert-renotify-metric brief).

Nothing here calls gcloud or the network: it checks the JSON shape the
Monitoring API actually accepts, catching the two traps already hit once in
this org's other repos (see jobs/alert_payloads.py's own docstrings) — a
conditionThreshold filter missing resource.type, and a
notificationRateLimit on a policy kind that rejects it.
"""

import json
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(REPO_ROOT, "jobs"))

from alert_payloads import (  # noqa: E402
    log_match_policy, metric_log_filter, same_policy, threshold_policy)

CHANNEL = "projects/bigtribebuilders/notificationChannels/4324299381952164741"
METRIC_NAME = "poll_dataform_failures_btb_alert_count"


def test_metric_log_filter_scopes_to_job_and_btb_alert():
    filt = metric_log_filter("poll-dataform-failures")
    assert 'resource.labels.job_name="poll-dataform-failures"' in filt
    assert 'textPayload:"BTB_ALERT"' in filt
    assert 'jsonPayload.message:"BTB_ALERT"' in filt


def test_log_match_policy_filter_matches_metric_log_filter():
    # The log-match policy and the counter metric must watch the exact same
    # lines, or the renotifying policy could fire on events the original
    # policy never paged on (or vice versa).
    policy = log_match_policy("TITLE", "poll-dataform-failures", "bigtribebuilders", CHANNEL)
    cond = policy["conditions"][0]["conditionMatchedLog"]
    assert cond["filter"] == metric_log_filter("poll-dataform-failures")


def test_log_match_policy_has_no_notification_channel_strategy():
    # Round-3 review blocker #1: notificationChannelStrategy landed on this
    # policy's alertStrategy in an earlier review round. Monitoring rejects
    # it outright on a conditionMatchedLog (log-based) policy, so
    # apply_policy's PATCH would fail and, under set -euo pipefail, the
    # script would never reach the metric or threshold policy below it.
    # This is the regression guard should-fix #3 asked for — it would have
    # caught blocker #1 before it ever reached a live run.
    policy = log_match_policy("TITLE", "poll-dataform-failures", "bigtribebuilders", CHANNEL)
    strategy = policy["alertStrategy"]
    assert "notificationChannelStrategy" not in strategy
    assert strategy["notificationRateLimit"] == {"period": "1800s"}
    assert strategy["autoClose"] == "604800s"


def test_threshold_policy_condition_names_resource_type():
    policy = threshold_policy(
        "TITLE", "poll-dataform-failures", "bigtribebuilders", CHANNEL, METRIC_NAME)
    cond = policy["conditions"][0]["conditionThreshold"]
    assert 'resource.type="cloud_run_job"' in cond["filter"]
    assert f'metric.type="logging.googleapis.com/user/{METRIC_NAME}"' in cond["filter"]


def test_threshold_policy_stays_open_for_a_full_day():
    # Round-3 review blocker #2: a 60s alignmentPeriod on a DELTA/ALIGN_SUM
    # counter reports a genuine 0 (not missing data) as soon as BTB_ALERT
    # lines stop, auto-resolving the incident within about a minute — long
    # before a 24h renotify could ever fire. A 24h alignmentPeriod keeps the
    # rolling sum >0 for a full day after even one line.
    policy = threshold_policy(
        "TITLE", "poll-dataform-failures", "bigtribebuilders", CHANNEL, METRIC_NAME)
    cond = policy["conditions"][0]["conditionThreshold"]
    assert cond["aggregations"][0]["alignmentPeriod"] == "86400s"
    assert cond["aggregations"][0]["perSeriesAligner"] == "ALIGN_SUM"


def test_threshold_policy_renotifies_every_24h_and_has_no_rate_limit():
    policy = threshold_policy(
        "TITLE", "poll-dataform-failures", "bigtribebuilders", CHANNEL, METRIC_NAME)
    strategy = policy["alertStrategy"]
    assert "notificationRateLimit" not in strategy
    assert strategy["notificationChannelStrategy"] == [{
        "notificationChannelNames": [CHANNEL],
        "renotifyInterval": "82800s",
    }]


def test_threshold_policy_evaluation_missing_data_absent_or_has_nonzero_duration():
    # Cloud Monitoring rejects evaluationMissingData paired with duration
    # "0s": "Conditions setting evaluation_missing_data must have a
    # non-zero duration" (confirmed live 2026-09-24, deploy-alerts.sh run
    # from main 406e2b7 against bigtribebuilders — see
    # docs/briefs/alert-threshold-fix.md, Context). The API docs say
    # EVALUATION_MISSING_DATA_UNSPECIFIED (the field's absence) is
    # equivalent to NO_OP, so dropping the field keeps the same behavior
    # without violating that constraint. This asserts the invariant, not
    # just today's fix, so a future duration change can't quietly break it.
    policy = threshold_policy(
        "TITLE", "poll-dataform-failures", "bigtribebuilders", CHANNEL, METRIC_NAME)
    cond = policy["conditions"][0]["conditionThreshold"]
    if "evaluationMissingData" in cond:
        assert cond["duration"] != "0s"


def test_threshold_policy_renotify_interval_is_shorter_than_alignment_period():
    # Round-4 review blocker #9: alignmentPeriod and renotifyInterval were
    # both 86400s. For a one-off BTB_ALERT line at time T, the 24h rolling
    # sum clears at about T+24h, but the incident only opens at
    # T+ingestion-lag, so the re-notify was due at T+lag+24h — AFTER the
    # window had already cleared. The second email would never arrive for a
    # one-off event. renotifyInterval must stay strictly under
    # alignmentPeriod so the re-notify always fires while the sum is still
    # >0 — this asserts the invariant, not just today's chosen values.
    policy = threshold_policy(
        "TITLE", "poll-dataform-failures", "bigtribebuilders", CHANNEL, METRIC_NAME)
    cond = policy["conditions"][0]["conditionThreshold"]
    strategy = policy["alertStrategy"]["notificationChannelStrategy"][0]
    alignment_period = int(cond["aggregations"][0]["alignmentPeriod"].rstrip("s"))
    renotify_interval = int(strategy["renotifyInterval"].rstrip("s"))
    assert renotify_interval < alignment_period


def test_threshold_policy_subject_keeps_btb_alert_prefix():
    policy = threshold_policy(
        "BTB-ALERT bigtribebuilders — poll-dataform-failures reported a BTB_ALERT (renotifies every 24h)",
        "poll-dataform-failures", "bigtribebuilders", CHANNEL, METRIC_NAME)
    assert policy["documentation"]["subject"].startswith("BTB-ALERT bigtribebuilders")


def test_threshold_policy_is_valid_json():
    policy = threshold_policy(
        "TITLE", "poll-dataform-failures", "bigtribebuilders", CHANNEL, METRIC_NAME)
    json.dumps(policy)  # must not raise


def test_cli_matches_direct_call():
    # Same round-trip jobs/deploy-alerts.sh does: capture stdout, parse JSON.
    result = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "jobs", "alert_payloads.py"),
         "threshold-policy", "TITLE", "poll-dataform-failures", "bigtribebuilders",
         CHANNEL, METRIC_NAME],
        capture_output=True, text=True, check=True)
    via_cli = json.loads(result.stdout)
    via_call = threshold_policy(
        "TITLE", "poll-dataform-failures", "bigtribebuilders", CHANNEL, METRIC_NAME)
    assert via_cli == via_call


def test_cli_metric_filter_matches_direct_call():
    result = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "jobs", "alert_payloads.py"),
         "metric-filter", "poll-dataform-failures"],
        capture_output=True, text=True, check=True)
    assert result.stdout.strip() == metric_log_filter("poll-dataform-failures")


def test_same_policy_ignores_api_omitted_defaults():
    # Round-3 review should-fix #4: the Monitoring API omits fields still
    # holding their zero/default value on read, so a policy that was created
    # from this exact payload can come back from GET without thresholdValue
    # or duration at all. Without normalizing those back in, apply_policy
    # would call this "drifted" and re-PATCH on every clean re-run.
    want = threshold_policy(
        "TITLE", "poll-dataform-failures", "bigtribebuilders", CHANNEL, METRIC_NAME)
    existing = json.loads(json.dumps(want))  # deep copy
    existing["conditions"][0]["name"] = "projects/bigtribebuilders/alertPolicies/123/conditions/456"
    del existing["conditions"][0]["conditionThreshold"]["thresholdValue"]
    del existing["conditions"][0]["conditionThreshold"]["duration"]
    assert same_policy(existing, want) is True


def test_same_policy_still_detects_real_drift():
    want = threshold_policy(
        "TITLE", "poll-dataform-failures", "bigtribebuilders", CHANNEL, METRIC_NAME)
    existing = json.loads(json.dumps(want))
    existing["conditions"][0]["conditionThreshold"]["filter"] = "metric.type=\"something-else\""
    assert same_policy(existing, want) is False
