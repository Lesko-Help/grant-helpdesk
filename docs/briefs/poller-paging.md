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
- Original fix + tests: brief filled (ebc249f), pagination + alert-grouping
  fix (3564257), reported to overseer, first review came back CHANGES with
  1 blocker + several minors (findings below). Now fixing each in its own
  commit, per the overseer's instructions.
- Fixed blocker #1 (90064f2): the repo loop in `main()` is now wrapped in
  `try/finally`; `alerted_events` is sent from the `finally` so an
  exception partway through the loop (e.g. `get_failed_action_names`
  raising on a later invocation) can't drop alerts already collected for
  earlier, already-logged invocations. Also corrected the neighbouring
  comment about when a raise here does/doesn't get re-checked next run
  (jobs/poll_dataform_failures.py:213-274, was item 6). Proved red first:
  new test with a "first" invocation that alerts and a "second" whose
  action lookup raises — asserted 1 alert call, failed with 0 against
  pre-fix code; green after the fix, 6/6 pass.
- Fixed minor #2 (1cbdb81): `get_failed_invocations` now passes `pageToken`
  via `requests.get(..., params=...)` instead of gluing it into the URL
  string unencoded (jobs/poll_dataform_failures.py:81-90). Test fakes
  updated to accept/inspect `params` instead of matching URL substrings.
- Fixed minor #3 (4a878f0): added a `seen_tokens` set in
  `get_failed_invocations`; raises if the API ever repeats a
  `nextPageToken`, which now feeds the existing SOURCE_FAILED/exit-1 path
  instead of looping until Cloud Run's task timeout (jobs/poll_dataform_failures.py:108-116).
  New test proves it raises.
- Added item-4 test (74d9738): page 1 succeeds, page 2 returns HTTP 500 —
  confirms `raise_for_status` propagates out and `main()` still sends
  SOURCE_FAILED and exits 1. No code change needed (overseer already
  verified this path was correct).
- All fixes to date: 8/8 tests pass
  (`/opt/anaconda3/bin/pytest tests/test_poll_dataform_failures.py`).

In flight (file:line): still owed from the review —
- item 5: `summarize_alert_events` (jobs/poll_dataform_failures.py, near
  line 185) should start its message "Dataform action failed N time(s) —
  ..." instead of dropping that wording.
- item 8: missing docstrings — `main()` has none; `get_failed_invocations`'s
  docstring doesn't state its output shape (list of
  `{inv_id, start_at, tags}`); test helpers `iso()` and `invocation()` have
  none.
- After those two commits: re-run the full test file, `git add -N .` +
  `git status --short` for a clean tree, `wt-done.sh --check poller-paging`,
  then report the new commit range + red-then-green proof (already have it
  for the blocker) + pytest count + the check's exit code back to the
  overseer, per its instructions. Do NOT fill in the brief's Verdict line —
  overseer does that after re-review.

Next: finish items 5 and 8 (each own commit), verify clean/green, report to
`helpdesk-opzichter`, then stop and wait for the re-review verdict.

Traps (with dates):
- 2026-09-24: this worktree's `python3` has no pytest. Use
  `/opt/anaconda3/bin/pytest tests/test_poll_dataform_failures.py`.
- 2026-08-19: `pytest` on this repo's other test files can hit live
  Dataform via `bq_writes.trigger_assignment_refresh` — run only
  `tests/test_poll_dataform_failures.py` here, don't run the whole suite
  unless credentials are meant to be live.
- 2026-09-23: a `get_failed_invocations` fetch error must still exit
  non-zero with a `SOURCE_FAILED` alert — kept covered through every
  review round, don't let a future edit swallow it again.
- 2026-09-24 (review round 1): any fake `requests.get` in this test file
  must accept a `params=None` kwarg now (pagination uses `params=`, not a
  glued URL) — a fake missing it raises TypeError on call, not a normal
  assertion failure.
