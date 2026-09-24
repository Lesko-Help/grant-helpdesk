# Brief: dedupe-ticket-tables

Written by the overseer (window 1) before work starts; the first commit on this
branch. The worktree session reads this before touching anything.

## Goal

Stop ticket_metadata and grant_ticket_labels from creating duplicate rows, back up and dedupe both to one row per content_id (newest wins; Martin approves the production delete), add uniqueKey(content_id) assertions proven red then green, and bring in the alert kit (raillog.py, deploy-alerts.sh from Lesko) with the grant_ticket_labels runnable's alert proven to fire.

## Done when

1. `definitions/assertions/assert_ticket_metadata_unique_content_id.sqlx` and
   `assert_grant_ticket_labels_unique_content_id.sqlx` (uniqueKey(content_id) on
   both tables) go from FAILING (red, proven against live data before the
   dedupe) to PASSING (green, after the approved dedupe lands).
2. The confirmed writer bug(s) — see Context — are fixed so re-running the
   pipeline does not reopen the assertions.
3. Both tables are backed up before any row is removed.
4. The production DELETE that performs the one-time dedupe is run only after
   Martin approves the exact row list (via the overseer) — this session STOPS
   and reports before running it.
5. `grant_ticket_labels`'s runnable has a BTB_ALERT alert (structured JSON,
   severity ERROR, matching the deploy-alerts.sh log-match policy). Per
   Martin's 2026-09-23 call ("land first, I deploy"), the fire-proof runs
   AFTER landing: the overseer deploys the job from `main`, breaks it once on
   purpose, and confirms the email — not this worktree session. This
   worktree's part of #5 is done once the alert kit is committed and the
   policy exists live (it does — see State).

## May touch

- `definitions/intelligence/grant_ticket_labels.sqlx` — the confirmed
  still-growing duplicate writer (MERGE with an un-deduped source).
- `definitions/intelligence/grant_question_classifier.sqlx` — suspected same
  bug class, upstream of grant_ticket_labels (see Context).
- `definitions/assertions/*.sqlx` — new uniqueKey(content_id) assertions.
- `jobs/poll_dataform_failures.py` — wire in the new alert helper for the
  grant_ticket_labels runnable.
- New alert helper module (named `raillog.py` per the global kit convention,
  adapted for this repo — no existing HTTP-rail callers here) and a
  repo-local `deploy-alerts.sh` adapted from lesko-provisioning's.
- `migrations/` — a new, NOT-YET-RUN one-time dedupe migration file, written
  but not executed until Martin approves.
- `bq_writes.py` — read-only investigation; current writers there
  (update_ticket_meta, set_ticket_lane, set_ticket_assignee,
  execute_bulk_close) already MERGE on content_id safely (see Context). Touch
  only if further investigation finds otherwise.
- This brief.

Out of scope: `lesko-questions-zone` repo (its own uniqueKey(content_id)
assertions on these same physical tables are deliberately red and must not be
weakened — they go green on their own once the live tables are deduped).
Never `deploy.sh`, never Dataform release/workflow config changes, never
`git worktree`, never push to main — those are the overseer's.

## Deploy implied

- Dataform: `definitions/` changes compile from `main` on merge (hourly
  release). The grant-helpdesk-5min workflow config trap applies if the
  overseer needs to pause it around the dedupe (see Context) — overseer's
  call, not this session's.
- `deploy-alerts.sh` (new, repo-local): creates/verifies the Cloud Monitoring
  alert policy. Whether the worktree session or the overseer runs it is still
  open — leaning toward this session running it since proving the alert fires
  is explicitly part of this brief's done-when, but flagging it because
  CLAUDE.md's default is "overseer deploys."
- The one-time dedupe DELETE: overseer runs it (or approves this session
  running it) only after Martin signs off.
- No `deploy.sh` / Cloud Run service redeploy needed — no app.py changes.

## Context

**Overseer's memory message, received 2026-09-14 (after this brief's first
commit was already in flight — folded in here per protocol):**

> DECISIONS
> - 2026-09-14, Martin, scope: fix the writers of ticket_metadata and
>   grant_ticket_labels. Back up both tables. Dedupe to one row per
>   content_id, newest updated_at / labeled_at wins. uniqueKey(content_id)
>   assertions, red today, then green. ORDER: 1 fix the writers, 2 backup +
>   one-time dedupe, 3 assertions.
> - The production DELETE is Martin's to approve. STOP and report to me
>   before running it, with the backup table names and the exact rows it
>   will remove. Auto mode also blocks live BQ UPDATE/DELETE without his
>   per-statement approval (2026-05-28).
> - 2026-09-14, Martin: the alert kit is IN SCOPE here. This repo has no
>   raillog.py and no deploy-alerts.sh. Copy them from ~/Lesko (start from
>   Lesko's raillog.py and deploy-alerts.sh). Give the grant_ticket_labels
>   runnable a BTB_ALERT alert, and prove it fires by breaking it on purpose
>   once and showing the email arrived. No landing without that.
> - lesko-questions-zone declares both tables. Its uniqueKey(content_id)
>   assertions are red on purpose and go green when this lands. Do not
>   weaken anything there.
>
> LIVE NUMBERS, 2026-09-14
> - ticket_metadata: 26 duplicate groups, 282 extra rows. 24 tickets / 300
>   rows are exact copies with closed_by='system_migration_20260518' at
>   2026-05-18 16:48 (migration 016_archive_recovered_backlog.sql MERGEs
>   into this table). 6 tickets also have extra app-written rows, the last
>   on 2026-08-19. 5 tickets have CONFLICTING values (e.g. status), so
>   "newest wins" must be checked on those 5. content_id is REQUIRED.
> - On 2026-08-20, 812 archived rows were MERGEd into ticket_metadata with
>   closed_by='migration/016 watermark recovery'.
> - grant_ticket_labels: 32 groups, 82 extra rows. 24 are exact copies; 6
>   differ only by labeled_at. STILL GROWING (new duplicates 2026-08-31 and
>   2026-09-14). Writer: definitions/intelligence/grant_ticket_labels.sqlx,
>   a MERGE. Suspected cause, NOT confirmed: its source holds duplicate
>   content_ids, so WHEN NOT MATCHED inserts each one.
> - grant_tickets LEFT JOINs ticket_metadata without deduping: 8,438 rows
>   for 6,181 content_ids (2026-08-20). Today's reads survive only because
>   bq_reads.py dedupes with QUALIFY ROW_NUMBER() OVER (PARTITION BY
>   content_id ...) = 1.
>
> TRAPS
> - Dataform pulls DEFINITIONS from GitHub main. A release config 'main'
>   compiles hourly (0 * * * *). Workflow config grant-helpdesk-5min runs
>   */30 on the latest PINNED compile. Merging to main is itself the
>   trigger. Pausing grant-helpdesk-5min (PATCH ?updateMask=disabled) FAILS
>   unless the body also carries releaseConfig. Pausing, pushing and
>   deploying are MINE: write the exact sequence in your report, don't run
>   it.
> - pytest calls bq_writes.trigger_assignment_refresh(), which fires a
>   REMOTE Dataform run from main. On 2026-08-19 that rebuilt grant_tickets
>   from old code mid-session. Keep tests from reaching the live repo, or
>   know that they do.
> - grant_classification_feedback is NOT tagged helpdesk, so tag-scoped runs
>   never rebuild it.
> - A schema change to an incremental model needs --full-refresh, and
>   stg_grant_candidates (a view) must be redeployed too.
> - Migration 014's DELETE block is superseded by 015. Never re-run it.
> - Migration 013 step 3 (null the legacy status markers) was NOT applied
>   as of 2026-08-19. Don't assume either way; check live if it matters.
> - A preview harness exists: HELPDESK_PREVIEW=1 repoints
>   TICKETS_TABLE/META_TABLE at bigtribebuilders.grant_helpdesk_preview.
> - gcloud run deploy needs
>   CLOUDSDK_API_ENDPOINT_OVERRIDES_RUN=https://run.googleapis.com/ (deploy
>   is mine, FYI).
> - 2026-09-03 elsewhere: a job-abort line at DEFAULT severity paged nobody.
>   Your alert line must be structured JSON with "severity":"ERROR" and the
>   BTB_ALERT text.

**This session's own findings, 2026-09-14:**

- Live BQ counts confirmed exactly against the memory: `ticket_metadata` 26
  dup groups / 282 extra rows; `grant_ticket_labels` 32 dup groups / 82 extra
  rows (read-only `bq query`, no writes).
- `ticket_metadata` duplicate rows by `closed_by`, among the 26 dup groups:
  300 rows `closed_by='system_migration_20260518'` (all timestamped exactly
  2026-05-18 16:48:05 — a single historical one-time script, not present
  anywhere in this repo's git history, already run and gone); 6 rows
  `closed_by IS NULL` (2026-04-23..2026-05-08); 2 rows
  `closed_by=` a staff account (2026-08-19 16:43:27).
- All four current `bq_writes.py` writers to `ticket_metadata`
  (`update_ticket_meta`, `set_ticket_lane`, `set_ticket_assignee`,
  `execute_bulk_close`) already `MERGE ... ON T.content_id = S.content_id`
  with a source that is either a single literal row or (`execute_bulk_close`)
  already deduped via `QUALIFY ROW_NUMBER() OVER (PARTITION BY content_id
  ...) = 1`. **These look safe already** — the live duplicates appear to be
  historical/migration-origin, not actively reproducing from the app today.
  Have not found any other current writer to `ticket_metadata` in this repo
  (`jobs/*.py` don't touch it; `definitions/*.sqlx` that reference it are
  reads/joins, not writes, except migration 016 which already ran).
- **Root cause of `grant_ticket_labels` still growing, now confirmed one
  level deeper than the memory's "suspected":** its upstream source
  `grant_question_classifier` (`definitions/intelligence/grant_question_classifier.sqlx`,
  an *incremental* table that itself declares `uniqueKey: ["content_id"]`)
  **already holds live duplicate content_id rows today** — spot-checked
  (e.g. `comment_147308843`, `post_101600495` each x2, several more). A
  declared `uniqueKey` only makes Dataform MERGE incrementally against rows
  already in the target; it does not dedupe two rows for the same key
  arriving in the *same* incremental batch — same defect class as
  `grant_ticket_labels.sqlx`'s own MERGE. `stg_grant_candidates` itself has
  **zero** duplicate content_ids right now (checked), so the duplication is
  introduced at `grant_question_classifier`, not earlier. **This means the
  writer fix likely needs to cover `grant_question_classifier.sqlx` as well
  as `grant_ticket_labels.sqlx`** — not yet read that file's body to confirm
  the exact mechanism; next step.
- Possible related trap, unconfirmed, worth the overseer knowing regardless
  of how this task resolves: `stg_grant_posts`, `stg_grant_articles`,
  `stg_grant_member_comments` also declare `uniqueKey: ["content_id"]` as
  incremental models. If any of *their* sources can ever deliver two rows
  for the same content_id within one run, they have the same latent
  same-batch-duplicate exposure as `grant_question_classifier`. Not checked
  yet.
- `jobs/poll_dataform_failures.py` is an existing hourly Cloud Run Job that
  already polls Dataform for FAILED invocations (across repos including
  `grant-helpdesk`) and logs them into `grant_helpdesk.app_logs` — but only
  via a plain `bq.insert_rows_json` row plus `print()`, not the CLAUDE.md
  `BTB_ALERT ... severity=ERROR` structured pattern (a BigQuery row is
  exactly the kind of alert-that-nothing-watches CLAUDE.md warns about).
  Plan: add a small alert helper module (kept named `raillog.py` per the
  global kit's naming convention, adapted — this repo has no existing
  HTTP-rail callers, so it's a smaller module than lesko-provisioning's)
  that emits `BTB_ALERT grant-helpdesk/<runnable> <CODE>: <message>` via
  `logging.error` as structured JSON at severity ERROR, and call it from
  `poll_dataform_failures.py` when a FAILED invocation is for the
  `grant_ticket_labels` action/tag. `deploy-alerts.sh` will be adapted from
  `/Users/admin/Lesko/lesko-provisioning/deploy-alerts.sh` (idempotent
  log-match Cloud Monitoring policy on the BTB_ALERT marker + severity
  ERROR).
- Tools confirmed available in this worktree: `bq`, `gcloud`, `dataform`
  CLIs, all authenticated (`.df-credentials.json` carried in per
  `.werk.conf`). Read-only `bq query` against live production already used
  above and is safe under auto-mode (only UPDATE/DELETE are gated).

**Still to do, in order:** read `grant_question_classifier.sqlx` and confirm/fix
its MERGE the same way as `grant_ticket_labels.sqlx`; add the two uniqueKey
assertions and prove them red on live data; fix the writer(s); re-run
assertions to confirm they're still red (dedupe hasn't happened yet) but the
*rate of new duplication* has stopped; take backups; compute the exact
newest-wins row list including manual resolution of the 5 conflicting
`ticket_metadata` tickets; write (not run) the one-time dedupe migration;
STOP and report to the overseer with backup table names + exact row list for
Martin's approval; build and prove the alert kit; only then are assertions
expected to go green (after the approved delete actually runs).

## State (2026-09-23, this session — supersedes the "Still to do" paragraph above)

**Done, committed, stable:**
- Writer fix + assertions (`git log`: bde729d, 61beeac, 720e7c8): `QUALIFY
  ROW_NUMBER() OVER (PARTITION BY content_id ORDER BY <ts> DESC) = 1` in
  `grant_question_classifier.sqlx` + `grant_ticket_labels.sqlx`; both
  uniqueKey(content_id) assertions, proven RED live.
- Dedupe migration (`git log`: e58779d, a695112, 23aa05e):
  `migrations/017_dedupe_ticket_tables.sql` — per-table BEGIN TRANSACTION /
  temp tables (dup ids + expected row count, both computed INSIDE the
  transaction) / DELETE scoped to dup ids / INSERT survivors / ASSERT no
  dup remains and row count matches / COMMIT. Dry-run clean, NOT executed.
  Undo scoped to just the deduped content_ids, not a full-table swap.
- Alert kit (`git log`: d2f39fd, 1abd401, 12d0e5e, 9d6ce75, 730f808):
  `raillog.py`, `poll_dataform_failures.py`, `Dockerfile.poll_dataform`,
  `deploy-alerts.sh`. Cloud Monitoring policy verified LIVE (create +
  idempotent no-op) against `bigtribebuilders`.
- Deploy ownership resolved: Martin, via the overseer, "Land first, I
  deploy" — this worktree never deploys to production.

**Done this turn — overseer's review (verdict CHANGES NEEDED, 14 findings),
fixed in new commits, per-finding:**
- #1-3 blocker/should (commit 12d0e5e): `poll_dataform_failures.py`'s
  `get_failed_action_names` turned every API error into `[]` and ran AFTER
  `log_failure` had already moved the watermark — a transient error during
  a real grant_ticket_labels failure meant no alert, exit 0, never
  rechecked. Now it raises, runs BEFORE `log_failure`, and an outer
  try/except around `main()` turns any escaping exception into
  `raillog.alert(..., "UNEXPECTED", ...)` before re-raising. A failed
  `get_failed_invocations` call now alerts (SOURCE_FAILED) and forces a
  non-zero exit instead of a silent `continue`.
- #4 should (commit 9d6ce75): `deploy-alerts.sh` was missing the 24h
  re-notify (global CLAUDE.md rule 3). Added
  `alertStrategy.notificationChannelStrategy[].renotifyInterval: "86400s"`.
  Per overseer note B: NOT run live from here — verified locally that the
  payload's Python still builds valid JSON with the field; the overseer
  runs it live from `main` after landing, which is the real test of
  whether the API accepts it on a conditionMatchedLog policy.
- #5-6 should (commit 23aa05e): the migration's temp tables were built
  BEFORE `BEGIN TRANSACTION` — a concurrent app write to a duplicated
  content_id in that gap would've been silently lost. Moved inside the
  transaction; added ASSERTs (no dup content_id remains; row count matches
  a pre-DELETE snapshot) before each COMMIT. Undo rewritten to scope its
  DELETE+INSERT to just the deduped content_ids, not `WHERE TRUE` (which
  would've discarded every app write since the backup was taken).
- #7 should (docs only, per overseer note C): added a note to the
  migration's ORDER OF RUN — the writer QUALIFY fix only stops same-batch
  duplicates (35/38 classifier groups); 3 classifier + 6 grant_ticket_labels
  groups have different timestamps, pointing at overlapping runs (scheduled
  workflow, hourly release, pytest's remote trigger). QUALIFY can't stop
  those — the uniqueKey assertions are the guard. Stopping pytest's trigger
  from hitting the live repo is a follow-up the **overseer owns**, not built
  here.
- #8 should (docs only, per overseer note C): no silence/heartbeat alert
  exists yet for the hourly `poll-dataform-failures` job itself (rule 4).
  Recorded as a follow-up the **overseer owns**, not built here.
- #9 nit: documented in the migration — expect the project-wide "a Dataform
  invocation failed" policy to email on every `helpdesk`-tagged
  grant-helpdesk-5min run between "writer fix compiles" and "migration
  runs" (both assertions red until then). Run 017 promptly; warn Martin.
- #11 nit (commit 730f808): `Dockerfile.poll_dataform`'s `COPY a b .` only
  works via undocumented BuildKit behavior — changed destination to `./`.
- #12 nit: this file's own trap about "dedupe via CREATE OR REPLACE TABLE"
  was stale (contradicted the approved DELETE+INSERT migration) — corrected
  below.
- #13 nit: a staff account's email was in this file (now "a staff
  account") and in the commit that first wrote it (`c2c6359`). Per overseer
  note A this is the one case where history is rewritten — happening next,
  via `git rebase -i` editing `c2c6359` directly (branch never pushed, safe).
- #10, #14: no change needed (assertion shape and raillog.py both confirmed
  correct as-is).

**Next:**
1. Rewrite `c2c6359` to remove the staff email from its diff (finding #13 /
   overseer note A), confirm clean.
2. Add "## Agentic review" section (Verdict / Findings / Fixed) below.
3. Report back to the overseer with the new commit range.

**Traps (dated, old ones stay):**
- 2026-08-19: Dataform compiles from GitHub main hourly; nothing here
  pushes to main — that's the overseer's.
- 2026-08-20: pausing the workflow needs `releaseConfig` in the PATCH body
  too; a full refresh needs `stg_grant_candidates` redeployed. Overseer's
  call, not this session's.
- 2026-08-20: `grant_tickets` LEFT JOINs `ticket_metadata` without
  deduplicating (8,438 rows/6,181 ids as of 2026-08-20) — only
  `bq_reads.py`'s `QUALIFY` hides this today. Expect counts to shift once
  the dedupe lands.
- 2026-05-28: auto-mode blocks live BQ UPDATE/DELETE and workflow
  enable/disable without Martin's per-statement approval.
- 2026-09-23: an unquoted bash heredoc (`<<PY`) reprocesses backslashes
  before Python sees them — use `<<'PY'` + `os.environ` whenever a heredoc
  body needs its own literal quotes alongside bash-supplied values.
- 2026-09-23: proving a Cloud Monitoring alert fires for a Cloud Run Job
  requires the log line to come from the real deployed job (resource
  type/labels must match) — a local script run can never trigger it.
- 2026-09-23: BigQuery `ROW_NUMBER() OVER (... ORDER BY <ts> DESC)` is
  non-deterministic on ties — harmless if the tied rows are byte-identical,
  but silently picks an arbitrary one when they differ (2 of
  grant_ticket_labels's 32 dup groups). Always add a secondary deterministic
  tiebreak (e.g. `TO_JSON_STRING(t) DESC`) and check for ties before trusting
  a newest-wins dedupe. **Corrected 2026-09-23 (review finding #12):** the
  live migration does NOT use `CREATE OR REPLACE TABLE ... AS SELECT ...
  WHERE rn = 1` — that first-draft approach silently drops
  `ticket_metadata.content_id`'s REQUIRED mode and `grant_ticket_labels`'s
  table description (both confirmed live). The actual migration is
  DELETE+INSERT inside a transaction, scoped to duplicated content_ids, with
  ASSERTs before COMMIT — see migrations/017_dedupe_ticket_tables.sql.
- 2026-09-23 (review finding #7, overseer-owned follow-up, not built in
  this branch): the writer QUALIFY fix only stops duplicates created within
  one Dataform run. 3 of the classifier's dup groups and 6 of
  grant_ticket_labels's have differing timestamps, meaning they came from
  separate overlapping runs (scheduled workflow, hourly release, and
  pytest's remote trigger hitting the live repo) — QUALIFY can't see across
  runs. The migration's uniqueKey assertions catch it after the fact; they
  don't stop it from recurring. Stopping pytest's remote trigger from
  writing to the live repo is the real fix and belongs to the overseer.
- 2026-09-23 (review finding #8, overseer-owned follow-up, not built in
  this branch): `poll-dataform-failures` itself has no silence/heartbeat
  alert — global CLAUDE.md rule 4 ("silence is a failure") isn't satisfied
  for this job yet. If the hourly Cloud Run Job stops running (scheduler
  misconfigured, image fails to start, etc.) nothing notices. Needs a
  policy that fires when no successful run happened within schedule +
  margin, same pattern as other repos' heartbeat alerts. Overseer's to
  build, not this session's.

## Agentic review

Verdict: pass — round 2, 2026-09-23, helpdesk-opzichter: all 14 findings fixed and verified at 58b7ca0 (compile, 017 dry-run, py/sh syntax, staff address gone from history)

**Round 1 verdict (from `helpdesk-opzichter`, cross-session review of this branch):**
CHANGES NEEDED — 14 findings.

**Findings, summarized:**
1. Blocker — `get_failed_action_names` swallowed API errors to `[]` and ran
   after the watermark-moving `log_failure`, so a transient error during a
   real grant_ticket_labels failure silently never alerted and was never
   rechecked.
2. Should — `get_failed_invocations` failures were only printed then
   `continue`d, exiting 0 with no alert.
3. Should — no outer guard turned an unhandled exception in `main()` into a
   BTB_ALERT line.
4. Should — `deploy-alerts.sh`'s alert policy was missing the 24h re-notify
   required by global CLAUDE.md rule 3.
5. Should — the migration's temp tables were built before `BEGIN
   TRANSACTION`, so a concurrent write in that gap could be silently lost.
6. Should — the migration's Undo did `DELETE ... WHERE TRUE` then reloaded
   the whole backup, discarding any app write made after the backup.
7. Should — the writer QUALIFY fix only stops same-run duplicates; several
   dup groups came from separate overlapping runs it can't see.
8. Should — `poll-dataform-failures` has no silence/heartbeat alert of its
   own.
9. Nit — no note warning that FAILED emails are expected on every
   `helpdesk`-tagged run between the writer fix compiling and migration 017
   running.
10. Nit — (no change needed; assertion shape confirmed correct as written).
11. Nit — `Dockerfile.poll_dataform`'s multi-source `COPY a b .` relies on
    undocumented BuildKit behavior instead of the documented `./` form.
12. Nit — this brief's trap list still described a stale `CREATE OR REPLACE
    TABLE` dedupe approach, contradicting the approved DELETE+INSERT
    migration.
13. Nit — a staff account's email address was committed in this file, in
    the commit that first wrote it.
14. Nit — (no change needed; raillog.py confirmed correct — structured
    JSON, `severity: ERROR`, fixed CODES set, BTB_ALERT format).

**Fixed:**
- #1-3: `jobs/poll_dataform_failures.py` — lookup reordered before the
  watermark write, exceptions now propagate instead of `except: []`,
  `get_failed_invocations` failures alert + force non-zero exit, and
  `main()` is wrapped so anything that escapes still alerts `UNEXPECTED`
  before re-raising. Commit `12d0e5e`.
- #4: `jobs/deploy-alerts.sh` — added
  `alertStrategy.notificationChannelStrategy[].renotifyInterval: "86400s"`.
  Per overseer note B, **not run live from this worktree** — verified only
  that the payload's Python still builds valid JSON with the field added;
  the overseer runs it live from `main` after landing. Commit `9d6ce75`.
- #5-6: `migrations/017_dedupe_ticket_tables.sql` — temp tables moved
  inside each `BEGIN TRANSACTION`, two `ASSERT`s added per table before
  `COMMIT` (no dup content_id remains; row count matches a pre-DELETE
  snapshot), Undo scoped to just the deduped content_ids instead of a
  full-table swap. Commit `23aa05e`.
- #7: docs only, per overseer note C — added to the migration's ORDER OF
  RUN section and to this brief's traps above. The pytest-trigger fix
  itself is recorded as an overseer-owned follow-up, not built here.
- #8: docs only, per overseer note C — recorded as an overseer-owned
  follow-up in this brief's traps above; the heartbeat alert itself is not
  built here.
- #9: documented in the migration's ORDER OF RUN section.
- #11: `Dockerfile.poll_dataform` — `COPY ... .` changed to `COPY ... ./`.
  Commit `730f808`.
- #12: trap list corrected above, in this commit.
- #13: the one finding where history is rewritten per overseer note A, not
  a new commit on top — `git rebase -i origin/main` editing `c2c6359`
  directly, since this branch has never been pushed. Done in the commit
  immediately after this one; see that commit's message for the before/after
  and the verification command used (a grep scoped to the specific staff
  address, not the bare `@gmail.com` substring the overseer's proposed
  `grep -c '@gmail.com'` check used — that broader form would not reach 0
  even after the fix, since it also matches all 12 commits'
  `Author: holyjezusandgod <martin.j.menke@gmail.com>` metadata lines, which
  are Martin's own expected git identity, not a leak).
- #10, #14: no change needed.
