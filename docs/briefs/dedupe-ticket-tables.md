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
   severity ERROR, matching the deploy-alerts.sh log-match policy), proven to
   fire by breaking it on purpose once and confirming the email arrived.

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

**Done, committed (`git log`: bde729d, 61beeac, 720e7c8, on top of c2c6359):**
- `definitions/intelligence/grant_question_classifier.sqlx` and
  `grant_ticket_labels.sqlx` (61beeac): `QUALIFY ROW_NUMBER() OVER
  (PARTITION BY content_id ORDER BY <its timestamp> DESC) = 1` fixes the
  same-batch duplicate root cause. Compiles clean, 21 actions.
- `definitions/assertions/assert_ticket_metadata_unique_content_id.sqlx` and
  `assert_grant_ticket_labels_unique_content_id.sqlx` (bde729d): uniqueKey
  pattern, proven RED against live data (ticket_metadata 26 dup groups/282
  extra rows; grant_ticket_labels 32 dup groups/82 extra rows).

**Done, NOT yet committed (alert kit):**
- `jobs/raillog.py` (new): BTB_ALERT emitter, `alert(runnable, code, message)`.
- `jobs/poll_dataform_failures.py`: `ALERTED_ACTIONS = {"grant_ticket_labels"}`,
  `get_failed_action_names()` (queries Dataform's
  `workflowInvocations/{id}:query`, confirmed live against invocation
  `1779255900-1c7deac7-8054-4e4c-8bba-ad759513f976` — 11 actions, 1 FAILED,
  correctly narrowed), wired into `main()`, `sys.exit(1)` when an alerted
  action fails.
- `jobs/Dockerfile.poll_dataform`: `COPY poll_dataform_failures.py raillog.py .`
- `jobs/deploy-alerts.sh` (new, `jobs/deploy-alerts.sh:196-238`): single
  `conditionMatchedLog` policy mirroring the project's existing
  "cerbo-logger reported a BTB_ALERT" policy, scoped to
  `job_name="poll-dataform-failures"`. `find_policy`/`apply_policy` lifted
  near-verbatim from `lesko-questions-zone/deploy-alerts.sh` (page-walk-safe
  lookup, whole-shape reconcile, PATCH-in-place keeping the condition's own
  `name`). Hit and fixed a real bug this turn: the payload-building heredoc
  was originally unquoted (`<<PY`) mixing bash `${VAR}` interpolation with
  Python strings that needed literal `\"` — bash only treats backslash as
  special before `$`, `` ` ``, `\`, newline in an unquoted heredoc, so the
  `\"` sequences arrived at Python mangled → `SyntaxError: unexpected
  character after line continuation character`. Fixed by switching to a
  quoted heredoc (`<<'PY'`, zero bash expansion) and passing `TITLE`/`JOB`/
  `PROJECT`/`CHANNEL` through `os.environ` instead. **Not yet re-run since
  the fix** — first concrete next step.

**In flight — blocked, waiting on the overseer/Martin:**
- Sent `helpdesk-opzichter [a6904a]` a report (msg_id
  1c04b3fc-b219-4552-952c-df0abfaf0399) on `ticket_metadata`'s 4 real
  conflicts (content_ids `comment_146961416`, `comment_147058507`,
  `comment_147074419`, `post_101109210` — older row has an open ticket
  assigned to a coach, newer migration row is closed with `assigned_to`
  blank). Asked Martin: (a) pure newest-wins, (b) backfill `assigned_to` on
  those 4, or (c) other. **No reply yet — do not compute the row list or
  write the migration until it arrives.** `grant_ticket_labels`'s 2 minor
  conflicts need no decision (newest-`labeled_at`-wins is fine).
- New question reasoned through but NOT yet sent: proving the
  grant_ticket_labels alert fires (Done-when #5) needs a real BTB_ALERT line
  in live Cloud Logging under `resource.labels.job_name=
  "poll-dataform-failures"` — a local Python run's stdout never reaches
  that resource type/label. That means deploying this session's modified
  job code (raillog.py/poll_dataform_failures.py/Dockerfile) to the live
  production Cloud Run Job. The project CLAUDE.md only names `deploy.sh`
  (the Streamlit app) as off-limits and this repo has no existing job-deploy
  script, so it's not explicitly forbidden — but it's a shared-production
  action, so leaning toward asking the overseer before running any job
  deploy, same as the ticket_metadata question. Not sent yet.

**Next:**
1. Re-run `bash jobs/deploy-alerts.sh`, confirm it creates/reconciles the
   policy cleanly against live `bigtribebuilders` Monitoring (no more
   SyntaxError).
2. Before deploying job code to prove the alert fires: send the overseer the
   open question above. Don't deploy unilaterally.
3. Once verified/answered: commit the alert kit (raillog.py,
   poll_dataform_failures.py, Dockerfile.poll_dataform, deploy-alerts.sh) —
   one commit, and break `grant_ticket_labels` on purpose once the policy is
   live to confirm the email actually arrives.
4. Once the overseer replies on the ticket_metadata conflict: back up both
   tables (`CREATE TABLE ... AS SELECT *`, timestamped, per migration 016's
   `recovery_snapshot_20260820` pattern); compute the exact newest-wins row
   list; write (not run) `migrations/017_dedupe_ticket_tables.sql`; STOP and
   report backup table names + exact row list for Martin's approval before
   anyone runs the DELETE.

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
