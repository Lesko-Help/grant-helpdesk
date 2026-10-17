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
   lost sessions per coach per day, and says so in one BTB_ALERT
   SESSION_LOST line when the count is above threshold. Guarded by
   `tests/test_watch_disconnects.py` over the pure core, with synthetic rows —
   no network. SESSION_LOST is this repo's own code, added to both raillog
   copies, which the suite now holds identical.
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

`server.disconnectedSessionTTL = 1800` keeps the session object alive for half
an hour after the socket dies, so the reconnect re-attaches to the session she
already had. 1800 and not the 900 this brief first proposed: her reconnect gaps
cluster at 15-17 minutes (90th percentile 17), so 15 minutes sits on the cliff.
Over the same three real days the lost sessions go 128 at the 120s default ->
76 at 900s -> 9 at 1800s -> 1 at 3600s. 1800 is the knee; past it we would hold
a coach's memory for someone who has gone home. Cost: a disconnected session
holds its state for half an hour instead of two minutes. At a 39.9% peak of
1 GiB with a handful of coaches there is room, and the service's existing
BTB_ALERT policies cover the container if that stops being true.

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
   `jobs/deploy-watch-disconnects.sh` (job + weekly Friday trigger; no IAM
   grant needed, the job's account already holds roles/editor, checked
   2026-10-16), and the metric plus two policies in `jobs/deploy-alerts.sh`.
   Guards in `tests/test_disconnect_resilience.py` walk both scripts' source,
   and hold the job's TTL equal to the app's. This slice also adds the `ast`
   flush guard global rule 2 asks for over both raillog copies — the suite
   had none, for either copy.

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

## Proved

Slice 1, red first: all three guards failed on a tree without the settings
(`disconnectedSessionTTL is unset`, `deploy.sh does not pass
--session-affinity`, `found 'streamlit'`), green after.

Slice 2, four mutations, each reverted: hard-coding the old 120s in
`summarise` reddened `test_the_ttl_is_the_whole_difference`; making every
socket a ping-clock drop reddened the grid test; `>` to `>=` on the threshold
reddened `test_at_the_agreed_rate_it_stays_quiet`; dropping the service pin
from the log filter reddened the filter test.

Slice 2, cross-check against reality: fed the 1000 real log rows this branch
was written from, `summarise` reproduces the independent ad-hoc analysis —
263 websockets, 222 for the one heavy client, 128 lost sessions at the 120s
TTL. The first ping-grid tolerance (0.05 of a tick, 1.5s wide) counted 167
grid drops against the ad-hoc 140; tightened to 0.1 *seconds* it counts 143,
and the looseness is now its own guard.

Slice 3, six mutations, each reverted: dropping `flush=True`, drifting the
job's TTL from the app's, dropping raillog.py from the image's COPY, removing
SESSION_LOST from one raillog copy only, shrinking the silence window to 90
minutes, and putting the app's TTL back to 120s each reddened exactly one
guard and nothing else.

End to end, live and read-only, 2026-10-16: `fetch_entries` over the real
project returned 285 entries and the full pipeline rendered its report, so
the filter, the client call and the arithmetic work together, not only the
arithmetic. At the 1800s TTL that report is 12 lost sessions across 14
clients, worst 2.5/day — under the 5/day threshold, so the weekly mail would
stay quiet. The same window at the 120s still deployed is about 130.

Not proved, and the overseer's to do after deploy: that the alert mail
actually arrives (global rule 5). `jobs/deploy-watch-disconnects.sh --drill`
prints the one command.

## Agentic review

### Verdict
Verdict: pass, with the limit named below. Reviewed 2026-10-17 over
`git diff origin/main...HEAD`. Two findings were real and are fixed; both were
in the parts no test could reach, which is where a review earns its keep.

Known limit of this verdict: the same session wrote the code and reviewed it,
because Martin asked for the whole chain in one go. A self-review catches a
wrong flag and a wrong sentence (it did, twice) and is weak on wrong ideas. The
one idea worth a second pair of eyes: exiting 0 on a bad finding, argued under
Design.

### Findings
1. The `--drill` command would have failed before reaching the code.
   `gcloud run jobs execute --args` REPLACES the container's args, and
   `Dockerfile.watch_disconnects` sets its command through `CMD` with no
   `ENTRYPOINT`, so the override would have tried to exec
   `--max-resets-per-day` as a program. The drill is the one thing rule 5
   asks for, and it would have failed in a way that looks like the job being
   broken rather than the drill being wrong.
2. The silence email read "No successful run of watch-disconnects in the last
   11520 minutes (its hourly schedule plus a margin)". `absence_policy` divided
   its window by 60 unconditionally and claimed an hourly schedule, both fine
   for the poller it was written for and wrong for a weekly job. The email IS
   the product of this rail, so an unreadable one is a defect, not a cosmetic.
3. `fetch_entries` sets no upper bound on how many entries it will walk. At
   today's volume a 7-day window is a few hundred rows, so this is a cost
   question and not a correctness one. Left alone deliberately: a cap would
   silently truncate the window and quietly understate lost sessions, which is
   worse than a slow run. If volume grows, narrow the window, not the cap.
4. `test_the_watcher_measures_against_the_ttl_the_app_deploys` reads the TTL
   out of the deploy script with a regex. It pins the two numbers equal, which
   is the invariant that matters, but it would not notice someone passing
   `TTL_SECONDS` into the job from somewhere else. Noted, not fixed.

### Fixed in
1. Fixed in this branch: the drill now uses `--update-env-vars
   MAX_RESETS_PER_DAY=0`, an override scoped to one execution, with a comment
   saying why not `--args`. Verified the flag exists on this gcloud (565.0.0).
2. Fixed in this branch: `human_window()` in `jobs/alert_payloads.py` renders a
   window in the largest unit it divides into cleanly, and the sentence no
   longer claims a schedule it does not know. Both sibling emails re-read
   correctly ("90 minutes", "8 days"), and the 52 existing alert tests still
   pass.
3. Not fixed — argued above.
4. Not fixed — argued above.

## State

Done: all three slices, landed verdict above. Settings (TTL 1800, session
affinity, streamlit==1.65.0), `jobs/watch_disconnects.py` + its image, deploy
script and weekly trigger, metric + renotifying policy + 8-day silence policy.
80 tests pass across the four touched files; 10 deliberate mutations each
reddened exactly one guard; the live read-only end-to-end ran against the real
project.

In flight: nothing — the branch is complete and clean.

Next: the overseer's three deploys in order (`deploy.sh`,
`jobs/deploy-watch-disconnects.sh`, `jobs/deploy-alerts.sh`), then
`jobs/deploy-watch-disconnects.sh --drill` and check the mail arrived.

Traps (with dates):
- 2026-10-17: `gcloud run jobs execute --args` replaces the container's args;
  with a `CMD`-only image that breaks the container start. Use
  `--update-env-vars` for a one-off override.
- 2026-10-17: `absence_policy`'s email text was written for an hourly job.
  Any new window has to be read back in words before it ships.
- 2026-10-16: a mutation test is worthless on an uncommitted file —
  `git checkout` silently does nothing to an untracked path, so four
  mutations stacked up unnoticed. Commit before mutating.
- 2026-10-16: Streamlit's disconnected-session TTL needs Cloud Run session
  affinity to mean anything across instances; the TTL alone is half a fix.

