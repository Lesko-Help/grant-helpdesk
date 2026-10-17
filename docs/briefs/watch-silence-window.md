---
client: Lesko
repo: helpdesk
rails: watch-disconnects (Cloud Run job)
module: alert_payloads
spec: docs/specs/modules/alert_payloads.md
folder: .claude/worktrees/watch-silence-window
---

# Brief: watch-silence-window

Stages: product (gate 1) · architecture (gate 2) · slices (gate 3)

## Goal

Give watch-disconnects a silence alert that Cloud Monitoring will actually
accept, and a guard that would have caught the one it rejected.

## Done when

`jobs/deploy-alerts.sh` applies a silence policy for watch-disconnects without
an API error, and `tests/test_disconnect_resilience.py` holds every silence
window between its job's schedule and the platform's ceiling. Red first: the
new guard fails on `origin/main`, which carries the 8-day window the API
refused.

# Gate

## Product

Problem, live 2026-10-17: `jobs/deploy-alerts.sh` could not create the
watch-disconnects silence policy.

    Field alert_policy.conditions[0].condition_absent.duration had an invalid
    value of "192h": Durations longer than 23h30m are not supported.

So the job that watches the coaches has no heartbeat, and global rule 4
("silence is a failure") is unmet for it. Everything else from
disconnect-resilience is live and working.

The limit is not a quirk of 8 days. A conditionAbsent policy fires when the
metric has been absent for longer than its window, so the window must be
LONGER than the gap between runs — and the window can never exceed 23h30m.
Together those mean conditionAbsent can only watch a job that runs at least
every ~23 hours. A weekly job cannot be watched this way at all. The hourly
poller's 90-minute window hides this: 1h < 1.5h < 23.5h, so it never met
either edge.

User: Martin, on the BTB-ALERT mail. It says the coach-session watcher has
stopped running, so the quiet he is reading as "the TTL fix held" is not
evidence of anything.

## Architecture

Run the watcher twice a day instead of weekly, and the window fits: schedule
every 12h, window 18h (1.5x, the same ratio the poller uses), ceiling 23h30m.
One missed run pages 18 hours later; a normal cycle never does.

Running twice a day is not a cost: each run is one Cloud Logging read of a few
hundred rows. It also means a regression reaches Martin within 12 hours
instead of up to a week.

What must NOT change is the mail: Martin asked for one review a week after
landing, not two a day for a week. `REPORT_ALWAYS_UNTIL` (report on every run
before a date) becomes `REPORT_ALWAYS_ON` (report on one named date). Both of
that date's runs raise a line; the threshold policy aligns over 24h and
renotifies every 24h, so Monitoring opens one incident and sends one mail.

Rejected: keeping the weekly schedule and watching it some other way. A longer
alignment period is capped at about 25h too, so a rolling 8-day sum is no more
expressible than an 8-day absence. The alternatives were a second, more
frequent job whose only purpose is to watch the first, or folding the check
into the hourly poller — both put the heartbeat further from the thing it
watches, for a job whose own cost is one log read.

## Slices

1. The guard first, in `tests/test_disconnect_resilience.py`: every silence
   window sits above its job's schedule gap and below the platform ceiling.
   Red on `origin/main`.
2. The fix: 12-hourly schedule, 18h window, `REPORT_ALWAYS_ON`.

## May touch

`jobs/deploy-watch-disconnects.sh`, `jobs/deploy-alerts.sh`,
`jobs/watch_disconnects.py`, `tests/test_disconnect_resilience.py`,
`tests/test_watch_disconnects.py`, this brief. Nothing else.

## Deploy implied

`jobs/deploy-watch-disconnects.sh` then `jobs/deploy-alerts.sh`, by the
overseer after landing. No `deploy.sh` — the app is untouched.

## Context

The watcher, its metric and its BTB_ALERT threshold policy are already live
(2026-10-17). Only the silence policy is missing. The Scheduler trigger
currently says `17 8 * * 5`.

## Agentic review

### Verdict
Verdict: pass, with the same self-review limit as disconnect-resilience named
there. Reviewed 2026-10-17 over `git diff origin/main...HEAD`. No new findings;
the change is small and the guard that would have prevented the original defect
now exists and goes red three ways.

### Findings
1. Changing the policy's displayName from "in 8 days" to "in 18 hours" means
   `apply_policy` sees a new title and creates a second policy rather than
   patching the first. Harmless here only because the 8-day one was never
   created - the API refused it. Worth knowing before renaming a policy that
   does exist: it orphans the old one instead of updating it.
2. `cron_gap_seconds` reports any day-of-week or day-of-month restricted cron
   as a 7-day gap rather than computing it. That is right for the only thing
   the test does with it - rejecting a schedule too sparse to be watched - and
   wrong as a general cron library. Named so nobody reuses it as one.

### Fixed in
1. Not fixed, nothing to fix - recorded as a trap.
2. Not fixed, deliberate; the docstring says so.

## State

Done: both slices. 78 tests pass across the three touched files; the new guard
was red on main's weekly/8-day pair and goes red on a window over the ceiling,
a window under the schedule gap, and a return to the weekly schedule.

In flight: nothing.

Next: `jobs/deploy-watch-disconnects.sh` then `jobs/deploy-alerts.sh`, then
`--drill` and check the mail.

Traps (with dates):
- 2026-10-17: Cloud Monitoring caps conditionAbsent.duration at 23h30m, and
  the window must also exceed the gap between runs. So conditionAbsent cannot
  watch any job running less often than about daily - a weekly job needs a
  different heartbeat or a denser schedule.
- 2026-10-17: renaming a policy's displayName creates a new policy and
  orphans the old one; apply_policy matches on title.

