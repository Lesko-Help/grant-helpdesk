---
client: Lesko
repo: helpdesk
rails: grant-helpdesk Streamlit app (Cloud Run service), watch-disconnects (Cloud Run job)
module: <fill in — no module spec covers the Streamlit server settings yet>
spec: <fill in>
folder: .claude/worktrees/disconnect-resilience
---

# Brief: disconnect-resilience

Stages: product (gate 1) · architecture (gate 2) · design (gate 3) · slices (gate 4)

## Goal

Stop a coach losing her whole screen every time her browser's websocket drops,
and put a weekly measurement behind it so the next regression is noticed
without anybody reporting it.

## Done when

1. `.streamlit/config.toml` sets `server.disconnectedSessionTTL = 900`,
   `deploy.sh` passes `--session-affinity`, and `requirements.txt` pins
   `streamlit==1.65.0`. Guarded by `tests/test_disconnect_resilience.py`.
2. `jobs/watch_disconnects.py` turns Cloud Run request logs into a count of
   lost sessions per coach per day, and says so in one BTB_ALERT line when the
   count is above threshold. Guarded by `tests/test_watch_disconnects.py` over
   the pure core, with synthetic rows — no network.
3. The job, its weekly Scheduler trigger and its three alert policies deploy
   from re-runnable scripts in the repo.

Run the two new files directly — never bare `pytest tests/`, which runs
`tests/smoke_test.py` against live BigQuery and triggers a remote Dataform
invocation.

# Gate

## Product

Problem, measured 2026-10-16 over the Cloud Run request logs of 10-13..10-16:
263 websocket sessions, 222 of them from one client, and **128 of that client's
reconnect gaps were longer than Streamlit's 120-second disconnected-session
TTL** — 37, 44 and 43 full app resets on the three working days. A reset means
Streamlit has deleted the session: her filters, her open ticket dialog and any
half-typed reply are gone and the app comes back at the start. That is what
"the app crashes on me" means. It is not a resource problem: over the same
week the container peaked at 39.9% of 1 GiB and 13.7% of one CPU, with zero
ERROR lines and zero 5xx.

Mechanism, read from the version that is actually deployed (streamlit 1.65.0,
`DEFAULT_WEBSOCKET_PING_INTERVAL = 30`, `DEFAULT_WEBSOCKET_PING_TIMEOUT = 30`):
the server pings every 30s and closes the socket when a pong is 30s late. That
is why 140 of that client's sockets died on an exact multiple of 30 seconds —
73 at 60s, 29 at 150s, 20 at 180s. The drops themselves come from her network
path, not from us; every other client in the window has ~0. We cannot fix her
line. We can stop a drop costing her work.

User: the coach on the desk (reported by Martin for Rose, 2026-10-16). The
Cloud Run logs carry no identity, so the IP-to-person link is inferred from
the full-time daily pattern, not proven — worth one question to her.

Success: a drop shorter than 15 minutes costs her nothing but a "Connecting…"
flicker. Measured by the same script that measured the problem.

Not in scope: her network; the hourly hard close at Cloud Run's 3600s request
timeout (that is the documented maximum and, once the TTL is 900s, invisible);
`server.websocketPingInterval`, which exists in 1.65 for exactly this symptom
but forces the ping timeout to equal the interval, so it cannot buy a longer
grace period without also pinging less often. Left as a tunable if drops
persist.

## Architecture

Three settings and one job.

`server.disconnectedSessionTTL = 900` keeps the session object alive for 15
minutes after the socket dies, so the reconnect re-attaches to the session she
already had. Cost: a disconnected session holds its state in memory for 15
minutes instead of 2. At 40% of 1 GiB with a handful of coaches there is room,
and `watch_disconnects` reports the container's own memory alongside the resets
so the trade is watched rather than assumed.

`--session-affinity` is not optional once the TTL is long: Streamlit's own
1.65.0 config docs say "if you are using load balancing or replication in your
deployment, you must enable session stickiness in your proxy to guarantee
reconnection to the existing session". The service runs minScale 1 / maxScale 3
and was measured at 5 instances on 10-15, so without stickiness a reconnect can
land on an instance that never had the session and the longer TTL buys nothing.

`streamlit==1.65.0` pins what is live today: the image built 2026-10-06 resolved
an unpinned `streamlit` to 1.65.0 (1.66.0 landed 10-14). So the pin changes no
behaviour now, and stops the next rebuild silently changing the websocket and
session machinery this brief depends on.

`watch-disconnects` is a Cloud Run job on a weekly Scheduler trigger, the same
shape as `poll-dataform-failures` and `roster-freshness`. It reads the request
log, not a new signal, so there is nothing to keep in sync with the app.

Rejected: a log-based metric alone. A lost session is a *gap between two
consecutive* log entries for one client; a Cloud Logging filter cannot express
that, so a metric could only count reconnects, which rise and fall with how
long she is logged in.

## Design

`watch_disconnects.py` splits into a pure core and a thin IO shell so the
arithmetic is testable without credentials — the same split
`alert_payloads.py` uses.

- `websocket_sessions(entries)` — in: raw log entries; out: one tuple per
  websocket, (client, instance, start, seconds).
- `summarise(sessions, ttl_seconds)` — in: those tuples and the TTL the app is
  deployed with; out: per client, the sessions, the drops that died on the
  30-second ping grid, the reconnect gaps that outlived the TTL (the resets),
  and resets per day. This is the whole measurement.
- `verdict(summary, max_resets_per_day, report_always, ...)` — in: the summary
  and the thresholds; out: whether to raise a BTB_ALERT line and what it says.

Exit code: 0 whenever the measurement itself worked, even when the finding is
bad. This differs on purpose from `poll_dataform_failures.py`, which exits 1 on
a finding: the silence policy here watches `completed_execution_count` with
`result="succeeded"`, so exiting 1 every week while a coach's line is still
flaky would also fire the "went silent" alert and turn one problem into two
emails. The finding travels in the BTB_ALERT line; a non-zero exit is reserved
for the job failing.

`REPORT_ALWAYS_UNTIL` (an ISO date) makes the job raise its line whatever the
numbers say, until that date passes. It is set to the day after the first
scheduled run so Martin gets one guaranteed review email a week from landing,
then the job falls back to threshold-only on its own with nothing to remember
to switch off.

## Slices

1. The three settings, with guards in `tests/test_disconnect_resilience.py`.
   Red first: each guard fails on `origin/main`, where none of the three is set.
2. `jobs/watch_disconnects.py` pure core + `tests/test_watch_disconnects.py`.
   Red first: the module does not exist on `origin/main`, so the import fails.
3. Deploy wiring: `jobs/Dockerfile.watch_disconnects`,
   `jobs/deploy-watch-disconnects.sh` (job, Scheduler trigger, log-reader IAM),
   and the metric plus three policies in `jobs/deploy-alerts.sh`. Guards in
   `tests/test_disconnect_resilience.py` walk both scripts' source.

## May touch

`.streamlit/config.toml`, `deploy.sh`, `requirements.txt`,
`jobs/watch_disconnects.py`, `jobs/Dockerfile.watch_disconnects`,
`jobs/deploy-watch-disconnects.sh`, `jobs/deploy-alerts.sh`,
`tests/test_disconnect_resilience.py`, `tests/test_watch_disconnects.py`,
this brief. Nothing else — no app.py, no Dataform.

## Deploy implied

Both by the overseer from `main` after the merge, in this order:
1. `PATH=/opt/anaconda3/bin:$PATH ./deploy.sh` — ships the TTL, the pin and
   session affinity. Until this runs, nothing in slice 1 is live.
2. `jobs/deploy-watch-disconnects.sh` then `jobs/deploy-alerts.sh` — the job,
   its weekly trigger and its alerts.

## Context

Measurement command and numbers are in the Product gate above; the raw pull was
`gcloud logging read` over `run.googleapis.com%2Frequests` for the service,
7-day freshness, 2026-10-16.

Constants: project `bigtribebuilders`, region `europe-west1`, service
`grant-helpdesk`, channel is looked up by name ("Martin (email)") the way
`deploy-alerts.sh` already does it.

Global rule 5 ("no alert, no landing — break it on purpose once and show the
email arrived") is not met by this branch: the drill is the overseer's, after
deploy. `jobs/deploy-watch-disconnects.sh --drill` prints the one command that
forces a BTB_ALERT line from a real run.
