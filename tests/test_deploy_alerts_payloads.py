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
import re
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(REPO_ROOT, "jobs"))

from alert_payloads import (  # noqa: E402
    absence_policy, log_match_policy, metric_log_filter, same_policy,
    service_log_match_policy, service_metric_log_filter,
    service_threshold_policy, threshold_policy)

CHANNEL = "projects/bigtribebuilders/notificationChannels/4324299381952164741"
METRIC_NAME = "poll_dataform_failures_btb_alert_count"
SERVICE = "grant-helpdesk"
SERVICE_METRIC_NAME = "grant_helpdesk_btb_alert_count"


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


# ── absence_policy(): pages when poll-dataform-failures goes silent ─────────
# poller-heartbeat brief (docs/briefs/poller-heartbeat.md). Unlike the two
# policies above, this one does not watch for a BTB_ALERT line — it watches
# for the job's own built-in Cloud Run execution-count metric going quiet,
# so it catches the job (or its Scheduler trigger) not running at all, which
# a log-based policy can never see because no line is ever written.

def test_absence_policy_watches_succeeded_runs_of_the_job():
    policy = absence_policy("TITLE", "poll-dataform-failures", "bigtribebuilders", CHANNEL)
    filt = policy["conditions"][0]["conditionAbsent"]["filter"]
    assert 'resource.type="cloud_run_job"' in filt
    assert 'metric.type="run.googleapis.com/job/completed_execution_count"' in filt
    assert 'resource.labels.job_name="poll-dataform-failures"' in filt
    assert 'metric.labels.result="succeeded"' in filt


def test_absence_policy_window_is_schedule_plus_margin():
    # 5400s = 1.5x the hourly schedule, so one missed or failed run pages
    # about 33 min after it was due (60 min schedule + 30 min margin for
    # the job's own timeout, the scheduler deadline and ingest lag) — see
    # docs/briefs/poller-heartbeat.md, Architecture, "Margin". The expected
    # value is written here, not read from the builder, so a future change
    # to SILENCE_WINDOW_SECONDS has to change this test on purpose.
    policy = absence_policy("TITLE", "poll-dataform-failures", "bigtribebuilders", CHANNEL)
    duration = policy["conditions"][0]["conditionAbsent"]["duration"]
    assert duration == "5400s"
    seconds = int(duration.rstrip("s"))
    assert 3600 < seconds < 7200


def test_absence_policy_is_condition_absent_not_threshold():
    policy = absence_policy("TITLE", "poll-dataform-failures", "bigtribebuilders", CHANNEL)
    cond = policy["conditions"][0]
    assert "conditionAbsent" in cond
    assert "conditionThreshold" not in cond
    assert "conditionMatchedLog" not in cond


def test_absence_policy_has_no_evaluation_missing_data():
    # That field is for threshold conditions — a conditionAbsent policy has
    # no such field at all (the 0s-duration trap from
    # docs/briefs/alert-threshold-fix.md does not apply here, but nothing
    # should copy the field over out of habit).
    policy = absence_policy("TITLE", "poll-dataform-failures", "bigtribebuilders", CHANNEL)
    assert "evaluationMissingData" not in policy["conditions"][0]["conditionAbsent"]


def test_absence_policy_renotifies_every_24h_and_has_no_rate_limit():
    policy = absence_policy("TITLE", "poll-dataform-failures", "bigtribebuilders", CHANNEL)
    strategy = policy["alertStrategy"]
    assert "notificationRateLimit" not in strategy
    assert strategy["notificationChannelStrategy"] == [{
        "notificationChannelNames": [CHANNEL],
        "renotifyInterval": "86400s",
    }]
    assert policy["notificationChannels"] == [CHANNEL]


def test_absence_policy_subject_keeps_btb_alert_prefix():
    # Slice 3 review fix (7): the old version of this test typed the title
    # itself, then checked its own input's prefix — it could never go red.
    # This reads the title jobs/deploy-alerts.sh actually builds, so a
    # broken prefix there fails here too.
    script_path = os.path.join(REPO_ROOT, "jobs", "deploy-alerts.sh")
    with open(script_path) as f:
        source = f.read()
    project = re.search(r'PROJECT="\$\{PROJECT:-([^}]+)\}"', source).group(1)
    job = re.search(r'JOB="\$\{JOB:-([^}]+)\}"', source).group(1)
    template = re.search(r'TITLE_SILENCE="([^"]+)"', source).group(1)
    real_title = template.replace("${PROJECT}", project).replace("${JOB}", job)

    policy = absence_policy(real_title, job, project, CHANNEL)
    assert real_title.startswith("BTB-ALERT bigtribebuilders")
    assert policy["documentation"]["subject"] == real_title
    assert policy["displayName"] == real_title


def test_cli_absence_policy_matches_direct_call():
    result = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "jobs", "alert_payloads.py"),
         "absence-policy", "TITLE", "poll-dataform-failures", "bigtribebuilders", CHANNEL],
        capture_output=True, text=True, check=True)
    via_cli = json.loads(result.stdout)
    via_call = absence_policy("TITLE", "poll-dataform-failures", "bigtribebuilders", CHANNEL)
    assert via_cli == via_call


def test_absence_policy_documentation_is_a_runbook():
    # Slice 3: the placeholder content from slice 1 gets replaced with a real
    # runbook — what Martin needs at 3am, not just what the condition is.
    policy = absence_policy("TITLE", "poll-dataform-failures", "bigtribebuilders", CHANNEL)
    content = policy["documentation"]["content"]
    assert "gcloud run jobs executions list" in content
    assert "poll-dataform-failures-hourly" in content
    assert "blind poller" in content


def test_same_policy_absence_round_trip():
    want = absence_policy("TITLE", "poll-dataform-failures", "bigtribebuilders", CHANNEL)

    existing = json.loads(json.dumps(want))
    existing["conditions"][0]["name"] = (
        "projects/bigtribebuilders/alertPolicies/123/conditions/456")
    assert same_policy(existing, want) is True

    drifted = json.loads(json.dumps(want))
    drifted["conditions"][0]["conditionAbsent"]["duration"] = "9000s"
    assert same_policy(drifted, want) is False


# ── service-scoped policies: the grant-helpdesk app itself ──────────────────
# coach-inbox-alert brief, slice B2. The app is a Cloud Run *service*
# (resource.type="cloud_run_revision", resource.labels.service_name), not a
# job — everything above this point watches poll-dataform-failures, a job.
# Both kinds of BTB_ALERT line share one Cloud Logging project, so the
# service filter also requires the "BTB_ALERT grant-helpdesk/" text prefix
# (overseer memory trap 4, 2026-09-25) — resource.type alone already tells
# jobs and services apart, but not one service's own BTB_ALERT lines from
# another service's, if one is ever deployed in the same project.

def test_service_metric_log_filter_scopes_to_service_and_repo_prefix():
    filt = service_metric_log_filter(SERVICE)
    assert 'resource.type="cloud_run_revision"' in filt
    assert f'resource.labels.service_name="{SERVICE}"' in filt
    assert 'textPayload:"BTB_ALERT grant-helpdesk/"' in filt
    assert 'jsonPayload.message:"BTB_ALERT grant-helpdesk/"' in filt
    assert '"severity"' not in filt  # trap 4: severity never lands where this filter can see it


def test_service_log_match_policy_filter_matches_service_metric_log_filter():
    policy = service_log_match_policy("TITLE", SERVICE, "bigtribebuilders", CHANNEL)
    cond = policy["conditions"][0]["conditionMatchedLog"]
    assert cond["filter"] == service_metric_log_filter(SERVICE)


def test_service_log_match_policy_has_no_notification_channel_strategy():
    # Same trap as the job policy (round-3 review blocker #1 / overseer trap
    # 1): Monitoring rejects notificationChannelStrategy on a
    # conditionMatchedLog (log-based) policy.
    policy = service_log_match_policy("TITLE", SERVICE, "bigtribebuilders", CHANNEL)
    strategy = policy["alertStrategy"]
    assert "notificationChannelStrategy" not in strategy
    assert strategy["notificationRateLimit"] == {"period": "1800s"}
    assert strategy["autoClose"] == "604800s"


def test_service_threshold_policy_condition_names_resource_type():
    # Overseer trap 2: a conditionThreshold on a log-based metric must
    # restrict resource.type itself, even though the metric's own filter
    # already scopes to cloud_run_revision — Monitoring rejects CREATE
    # without it.
    policy = service_threshold_policy(
        "TITLE", SERVICE, "bigtribebuilders", CHANNEL, SERVICE_METRIC_NAME)
    cond = policy["conditions"][0]["conditionThreshold"]
    assert 'resource.type="cloud_run_revision"' in cond["filter"]
    assert f'metric.type="logging.googleapis.com/user/{SERVICE_METRIC_NAME}"' in cond["filter"]


def test_service_threshold_policy_stays_open_for_a_full_day():
    policy = service_threshold_policy(
        "TITLE", SERVICE, "bigtribebuilders", CHANNEL, SERVICE_METRIC_NAME)
    cond = policy["conditions"][0]["conditionThreshold"]
    assert cond["aggregations"][0]["alignmentPeriod"] == "86400s"
    assert cond["aggregations"][0]["perSeriesAligner"] == "ALIGN_SUM"


def test_service_threshold_policy_renotifies_every_24h_and_has_no_rate_limit():
    policy = service_threshold_policy(
        "TITLE", SERVICE, "bigtribebuilders", CHANNEL, SERVICE_METRIC_NAME)
    strategy = policy["alertStrategy"]
    assert "notificationRateLimit" not in strategy
    assert strategy["notificationChannelStrategy"] == [{
        "notificationChannelNames": [CHANNEL],
        "renotifyInterval": "82800s",
    }]


def test_service_threshold_policy_evaluation_missing_data_absent_or_has_nonzero_duration():
    # Overseer trap 3: evaluationMissingData paired with duration "0s" is
    # rejected outright — same constraint as the job policy.
    policy = service_threshold_policy(
        "TITLE", SERVICE, "bigtribebuilders", CHANNEL, SERVICE_METRIC_NAME)
    cond = policy["conditions"][0]["conditionThreshold"]
    if "evaluationMissingData" in cond:
        assert cond["duration"] != "0s"


def test_service_threshold_policy_renotify_interval_is_shorter_than_alignment_period():
    policy = service_threshold_policy(
        "TITLE", SERVICE, "bigtribebuilders", CHANNEL, SERVICE_METRIC_NAME)
    cond = policy["conditions"][0]["conditionThreshold"]
    strategy = policy["alertStrategy"]["notificationChannelStrategy"][0]
    alignment_period = int(cond["aggregations"][0]["alignmentPeriod"].rstrip("s"))
    renotify_interval = int(strategy["renotifyInterval"].rstrip("s"))
    assert renotify_interval < alignment_period


def test_service_threshold_policy_subject_keeps_btb_alert_prefix():
    # Overseer trap 5: the subject lives in documentation.subject and starts
    # "BTB-ALERT bigtribebuilders".
    policy = service_threshold_policy(
        "BTB-ALERT bigtribebuilders — grant-helpdesk reported a BTB_ALERT (renotifies every 24h)",
        SERVICE, "bigtribebuilders", CHANNEL, SERVICE_METRIC_NAME)
    assert policy["documentation"]["subject"].startswith("BTB-ALERT bigtribebuilders")


def test_service_threshold_policy_is_valid_json():
    policy = service_threshold_policy(
        "TITLE", SERVICE, "bigtribebuilders", CHANNEL, SERVICE_METRIC_NAME)
    json.dumps(policy)  # must not raise


def test_service_log_match_policy_is_valid_json():
    policy = service_log_match_policy("TITLE", SERVICE, "bigtribebuilders", CHANNEL)
    json.dumps(policy)  # must not raise


def test_cli_service_metric_filter_matches_direct_call():
    result = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "jobs", "alert_payloads.py"),
         "service-metric-filter", SERVICE],
        capture_output=True, text=True, check=True)
    assert result.stdout.strip() == service_metric_log_filter(SERVICE)


def test_cli_service_log_match_policy_matches_direct_call():
    result = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "jobs", "alert_payloads.py"),
         "service-log-match-policy", "TITLE", SERVICE, "bigtribebuilders", CHANNEL],
        capture_output=True, text=True, check=True)
    via_cli = json.loads(result.stdout)
    via_call = service_log_match_policy("TITLE", SERVICE, "bigtribebuilders", CHANNEL)
    assert via_cli == via_call


def test_cli_service_threshold_policy_matches_direct_call():
    result = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "jobs", "alert_payloads.py"),
         "service-threshold-policy", "TITLE", SERVICE, "bigtribebuilders", CHANNEL,
         SERVICE_METRIC_NAME],
        capture_output=True, text=True, check=True)
    via_cli = json.loads(result.stdout)
    via_call = service_threshold_policy(
        "TITLE", SERVICE, "bigtribebuilders", CHANNEL, SERVICE_METRIC_NAME)
    assert via_cli == via_call


def test_same_policy_service_threshold_round_trip():
    # same_policy() is shared with the job policies — this proves it also
    # reconciles the service policy's own API-omitted-defaults shape.
    want = service_threshold_policy(
        "TITLE", SERVICE, "bigtribebuilders", CHANNEL, SERVICE_METRIC_NAME)
    existing = json.loads(json.dumps(want))
    existing["conditions"][0]["name"] = "projects/bigtribebuilders/alertPolicies/789/conditions/012"
    del existing["conditions"][0]["conditionThreshold"]["thresholdValue"]
    del existing["conditions"][0]["conditionThreshold"]["duration"]
    assert same_policy(existing, want) is True

    drifted = json.loads(json.dumps(want))
    drifted["conditions"][0]["conditionThreshold"]["filter"] = 'metric.type="something-else"'
    assert same_policy(drifted, want) is False


def test_service_metric_name_matches_deploy_alerts_naming():
    # jobs/deploy-alerts.sh derives METRIC_NAME as "${SERVICE//-/_}_btb_alert_count"
    # for the job block — the service block must use the same substitution so
    # a coach reading one policy's metric name can guess the other's.
    assert SERVICE_METRIC_NAME == SERVICE.replace("-", "_") + "_btb_alert_count"
