# Brief: poller-paging

Stages: review — DOWNGRADED (dropped: product · architecture · design · slices)
Downgraded: repo default "groot" wanted product · architecture · design · slices.
Reason: Martin 2026-09-24: one-function bug fix (poller reads only page 1 of Dataform invocations), review only

Written by the overseer (window 1) before work starts; the first commit on this
branch. The worktree session reads this before touching anything. (wt-new.sh
fills in the two `<!-- ... -->` markers on this page — the line above with
this task's `Stages: ...` summary, the one below with this task's gate
fragments from TEMPLATE.d/, in WT_STAGE_ORDER; if either marker text is still
here, something skipped that step.)

## Agentic review

### Verdict
Verdict: `<fill in — pass, or changes requested>`

### Findings
What the overseer's review subagent flagged — style, bugs, security —
one line each. A trimmer before Martin's read, not a replacement for it.

### Fixed in
Which commit fixed each finding, or "not fixed — see report" — one line
each.

This section is filled last, after the overseer runs its review subagent
and sends the findings back — never by the worker reviewing its own
diff. Record the verdict, fix what needs fixing, commit, then report
again the normal way.

wt-done.sh's check on this is literal: it greps this brief for a line
starting with exactly `Verdict:` at the very start of the line (column 0)
— no bold, no indent, no renamed label, no different case. Keep the
`Verdict:` line reading exactly as it does above, or the guard cannot see
it and treats the brief as not yet reviewed.


## Goal

poll_dataform_failures reads every page of workflowInvocations (nextPageToken) and filters by time locally, so no failure is missed; backlog since the watermark (2026-05-20) is logged to app_logs in full but raises ONE summary BTB_ALERT, not one per failure (Martin's decision). Red-first test with a multi-page, unordered fake API. No live Dataform/BigQuery calls from tests.

## Done when

A new `tests/test_poll_dataform_failures.py` (run with
`/opt/anaconda3/bin/pytest tests/test_poll_dataform_failures.py` — no live
Dataform/BigQuery calls, everything is faked) passes, including:

1. `test_get_failed_invocations_follows_pagination` — a fake API returning
   three pages (linked by `nextPageToken`), with FAILED invocations spread
   unevenly across pages and out of time order. Proved red first against
   today's code (which reads only page 1, `pageSize=50`, and never looks at
   `nextPageToken`) — it must miss the failures on pages 2 and 3. Green
   after `get_failed_invocations` loops until a response has no
   `nextPageToken`, still filtering each invocation's `startTime` against
   `since` locally on every page, same as today.
2. `test_main_sends_one_summary_alert_not_one_per_failure` — a fake API
   returning several FAILED invocations for `grant_ticket_labels` in one
   run (the shape a first fixed run sees: the backlog since the
   2026-05-20 watermark). Proved red first against today's code (one
   `raillog.alert()` call per matching failure). Green after `main()`
   groups alerted failures by action name and calls `raillog.alert()`
   once per name, with a message naming how many failures and their
   invocation ids — every underlying failure still gets its own row
   written to `app_logs` via `log_failure`; only the alert call count
   changes.
3. Existing behaviour stays covered: a `get_failed_invocations` fetch
   error still exits non-zero with a `SOURCE_FAILED` alert (2026-09-23
   trap below) — add or keep a test for that path in the same file.

Spec: unchanged because this repo has no `docs/specs/` tree yet (checked —
`docs/specs` does not exist), so there is nothing to update.

## May touch

Module: `jobs` (the Cloud Run Job `poll-dataform-failures`, the smallest
thing deployed on its own via `jobs/Dockerfile.poll_dataform`).

- `jobs/poll_dataform_failures.py` — paginate `get_failed_invocations`
  through `nextPageToken`; group alerted failures in `main()` into one
  `raillog.alert()` call per action name instead of one per failure.
- `tests/test_poll_dataform_failures.py` — new file, offline fakes only.

## Deploy implied

Cloud Run Job redeploy of `poll-dataform-failures` from
`jobs/Dockerfile.poll_dataform`. Not run from this worktree — the overseer
redeploys from `main` after landing, then redoes the break-on-purpose
firedrill to prove alert policies 13511530526976011919 (log-match) and
9606063400841394205 (threshold) actually fire.

## Context

Overseer memory message, received 2026-09-24 (helpdesk-opzichter):

1. Trap: `get_failed_invocations` (`jobs/poll_dataform_failures.py:72`)
   reads only the first page of `workflowInvocations` (`pageSize=50`) and
   never follows `nextPageToken`. Dataform returns invocations in no time
   order. The first page ran from 2026-05-20 to 07:30 that morning. The
   fix must walk every page and filter by time locally.
2. Proof it is broken (2026-09-24 firedrill): invocation
   `1790246841-035551e3` of `grant_ticket_labels` was made to fail on
   purpose on the throwaway branch `firedrill-break`. Execution
   `poll-dataform-failures-9l2x2` printed "Found 0 new failure(s)" and
   exited 0 — no email sent. The watermark for `grant-helpdesk` (`MAX
   created_at` in `app_logs` where `source = dataform.grant-helpdesk`) is
   `2026-05-20T10:40`. Nothing logged since May.
3. Decision by Martin (2026-09-24), backlog handling: the first fixed run
   picks up every FAILED invocation since 2026-05-20 — write every missed
   failure to `app_logs`, raise ONE summary `BTB_ALERT` for the backlog,
   not one per failure.
4. After landing, the overseer (not this worktree) deploys the job from
   `main` and redoes the break-on-purpose firedrill against policies
   13511530526976011919 (log-match) and 9606063400841394205 (threshold).
5. Trap (2026-08-19): `pytest` can trigger the live Dataform repo, because
   `bq_writes.trigger_assignment_refresh` fires a remote workflow
   invocation — this worktree's new test file must never call live
   Dataform or BigQuery.
6. Trap (2026-09-23): an earlier review found the poller silently exiting
   0 on a fetch failure while the watermark moved on — a paging error
   must exit non-zero and log a `BTB_ALERT SOURCE_FAILED` line, never get
   swallowed. (Already fixed on `main` per commit 46060a3 — keep it
   covered, don't regress it.)

## State

Replaced in full each time the context guard asks you to save — never append another checkpoint.
About 60 lines max. Old traps stay (they are short and worth keeping); everything else gets
overwritten with the current picture.

Done:
- Filled in this brief (commit ebc249f), folding in the overseer's firedrill
  memory message under Context.
- `jobs/poll_dataform_failures.py`: `get_failed_invocations` now loops on
  `nextPageToken` until a page has none, still filtering `startTime` vs
  `since` per invocation on every page (jobs/poll_dataform_failures.py:71-110).
- `jobs/poll_dataform_failures.py`: `main()` now collects alerted failures
  into `alerted_events` (name -> list of {repo, inv_id, detail}) and calls
  `raillog.alert()` once per action name via new `summarize_alert_events()`,
  instead of once per failing invocation (jobs/poll_dataform_failures.py:185-256).
- New `tests/test_poll_dataform_failures.py`, 5 tests, all offline
  (fakes `requests.get`, `bigquery.Client`, `raillog.alert` — no live
  Dataform/BigQuery). Proved red-then-green: ran the 2 new-behavior tests
  against the pre-fix code first (both failed — pagination test found 0 of
  2 later-page failures; alert test saw 3 calls instead of 1), then against
  the fixed code (5/5 pass). Also covers: pagination stops when a page has
  no `nextPageToken`; grouping doesn't drop any app_logs row; the existing
  fetch-failure -> SOURCE_FAILED-alert-and-exit-1 path still works.
- Uncommitted right now: `jobs/poll_dataform_failures.py` (modified),
  `tests/test_poll_dataform_failures.py` (new) — both ready, not yet
  committed as of this checkpoint.

In flight (file:line): none mid-edit — next action is to commit the two
files above, then run `wt-done.sh --check poller-paging`, merge
`origin/main`, and report to the overseer.

Next:
1. `git add jobs/poll_dataform_failures.py tests/test_poll_dataform_failures.py`
   and commit (one idea: paging + one-alert-per-backlog, per the Goal).
2. Merge `origin/main` once, right before reporting.
3. `git add -N .`, confirm `git status` clean.
4. `wt-done.sh --check poller-paging`, fix anything it refuses on, re-run
   to 0.
5. SendMessage to `helpdesk-opzichter` with branch, commit range, HEAD sha,
   5-line summary, red-then-green proof, deploy implication (Cloud Run Job
   `poll-dataform-failures` redeploy from `jobs/Dockerfile.poll_dataform`,
   overseer runs it from `main` after landing, then redoes the firedrill
   against policies 13511530526976011919 / 9606063400841394205).

Traps (with dates):
- 2026-09-24: this worktree's `python3` has no pytest. Use
  `/opt/anaconda3/bin/pytest tests/test_poll_dataform_failures.py`.
- 2026-08-19: `pytest` on this repo's other test files can hit live
  Dataform via `bq_writes.trigger_assignment_refresh` — run only
  `tests/test_poll_dataform_failures.py` here, don't run the whole suite
  unless credentials are meant to be live.
- 2026-09-23: a `get_failed_invocations` fetch error must still exit
  non-zero with a `SOURCE_FAILED` alert — this task's refactor kept that
  path (see `test_fetch_failure_still_alerts_and_exits_nonzero`), don't
  let a future edit swallow it again.
