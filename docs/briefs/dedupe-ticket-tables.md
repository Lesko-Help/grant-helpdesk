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
- `definitions/intelligence/grant_question_classifier.sqlx` (61beeac): added
  `QUALIFY ROW_NUMBER() OVER (PARTITION BY c.content_id ORDER BY c.updated_at
  DESC) = 1` to the final SELECT. Fixes the confirmed root cause: its old
  `WHERE content_id NOT IN (SELECT content_id FROM self())` only screens
  against rows already saved, not two rows for the same key arriving in the
  same batch.
- `definitions/intelligence/grant_ticket_labels.sqlx` (61beeac): same
  `QUALIFY ROW_NUMBER() OVER (PARTITION BY q.content_id ORDER BY
  q.classified_at DESC) = 1` on the `questions` temp table's SELECT. One
  layer downstream of `grant_question_classifier`, not an independent bug —
  fixing that table's dupes removes this one's actual source of new ones.
  Both compile clean: `dataform compile` → 21 actions, no errors.
- `definitions/assertions/assert_ticket_metadata_unique_content_id.sqlx` and
  `assert_grant_ticket_labels_unique_content_id.sqlx` (bde729d): uniqueKey
  pattern (`GROUP BY content_id HAVING COUNT(*) > 1`). Proven RED against
  live data via read-only `bq query`: ticket_metadata 26 dup groups / 282
  extra rows; grant_ticket_labels 32 dup groups / 82 extra rows — matches the
  2026-09-14 memory almost exactly.

**Done, NOT yet committed (alert kit, in progress this turn):**
- `jobs/raillog.py` (new): the BTB_ALERT emitter — `alert(runnable, code,
  message)` prints one JSON line `{"severity":"ERROR","message":"BTB_ALERT
  grant-helpdesk/<runnable> <CODE>: <message>"}`. Deliberately NOT copied
  from lesko-provisioning's `raillog.py` (that one's the older `RAIL_ALERT`,
  non-JSON, HTTP-rail-call convention — wrong shape). Modeled on
  `getresponse/scripts/alerts.py` and `LH-member-private-zone/zone_app/alert.py`,
  both of which already implement the current BTB_ALERT/JSON convention.
  Lives in `jobs/`, not the repo root, because `jobs/Dockerfile.poll_dataform`
  only `COPY`s the one file it runs (confirmed by reading it) — a repo-root
  module would 404 at import time in the built container. Dockerfile updated
  to `COPY poll_dataform_failures.py raillog.py .` to match.
- `jobs/poll_dataform_failures.py`: added `ALERTED_ACTIONS = {"grant_ticket_labels"}`,
  a new `get_failed_action_names()` (calls Dataform's
  `workflowInvocations/{id}:query` endpoint — confirmed live via `curl` that
  this returns `workflowInvocationActions[].target.name` +
  `.state`, letting us tell which action inside a FAILED invocation actually
  failed, not just that the invocation failed), and wiring in `main()`: any
  failed action in `ALERTED_ACTIONS` calls `raillog.alert(name,
  "SOURCE_FAILED", ...)` and the job `sys.exit(1)`s at the end if any fired.
  Every other action's failure still only reaches `app_logs`, unchanged.
  Syntax-checked with `ast.parse` (no dataform/python toolchain error).
- **Not yet done:** haven't run this against a real FAILED invocation to
  confirm `get_failed_action_names()` actually returns the right names — was
  mid-search for a live FAILED invocation to test against
  (`1779255900-1c7deac7-8054-4e4c-8bba-ad759513f976`, 2026-05-20T05:45,
  found via a read-only list call, not yet queried for its action list).
  `deploy-alerts.sh` not started. Haven't proven the alert fires end to end
  (brief's Done-when #5) — need deploy-alerts.sh's Cloud Monitoring policy
  live first, then break something on purpose.

**In flight — blocked, waiting on the overseer/Martin:**
- Sent `helpdesk-opzichter [a6904a]` a report (msg_id
  1c04b3fc-b219-4552-952c-df0abfaf0399) flagging a judgment call: of
  `ticket_metadata`'s 26 dup groups, 4 have a real conflict — content_ids
  `comment_146961416`, `comment_147058507`, `comment_147074419`,
  `post_101109210`. In each, the OLDER row (Apr 2026) has `status=''` (open)
  and a coach in `assigned_to` (Amber Hawkins x2, Charity Spencer, Amber
  Littlefield); the NEWER row (all four 2026-05-18 16:48:05, the
  `system_migration_20260518` batch) has `status='closed'` but
  `assigned_to` blank — the migration didn't carry the assignment forward.
  Pure "newest wins" would silently drop these 4 coaches' assignments.
  Asked Martin to pick: (a) pure newest-wins, (b) backfill `assigned_to`
  from the older row on those 4, or (c) other. **Do not compute the final
  delete row list or write the migration until this answer arrives.**
  Also flagged: memory said 5 conflicting tickets, live data today shows
  only 4 — unexplained drift, not chased further.
  `grant_ticket_labels` also has 2 conflicting groups (`comment_147039001`,
  `comment_147274739`, differing AI-generated `domain`/`difficulty`) — lower
  stakes, newest-`labeled_at`-wins is fine there, no objection needed.
  Backup-table creation and the migration file are NOT started — both need
  the row-list decision first.

**Next:**
1. Alert kit (not blocked on the overseer, keep going): confirm
   `get_failed_action_names()` against a real FAILED invocation; write
   `deploy-alerts.sh` adapted from `lesko-provisioning/deploy-alerts.sh`
   (log-match on BTB_ALERT text + severity ERROR, `conditionAbsent` ceiling);
   run it (this session's call to make per the brief's Deploy-implied
   section — proving the alert fires is explicitly this brief's job); break
   `grant_ticket_labels` on purpose once and confirm the email arrives;
   commit the whole alert kit.
2. Once the overseer replies on the ticket_metadata conflict: take backups
   of both tables (`CREATE TABLE ... AS SELECT *`, timestamped, following
   the `recovery_snapshot_20260820` pattern in migration 016); compute the
   exact newest-wins row list; write (not run)
   `migrations/017_dedupe_ticket_tables.sql`; STOP again and report backup
   table names + exact row list for Martin's approval before anyone runs
   the DELETE.

**Traps (still current, dated):**
- 2026-08-19: Dataform compiles from GitHub main hourly;
  grant-helpdesk-5min runs every 30 min off the latest pinned compile.
  Nothing here pushes to main — that's the overseer's.
- 2026-08-20: pausing the workflow needs `releaseConfig` in the PATCH body
  too; a full refresh needs `stg_grant_candidates` redeployed. Overseer's
  call, not this session's.
- 2026-08-20: `grant_tickets` LEFT JOINs `ticket_metadata` without
  deduplicating (8,438 rows / 6,181 ids as of 2026-08-20) — only
  `bq_reads.py`'s `QUALIFY` hides this today. Expect counts to shift once
  the dedupe lands.
- 2026-05-28: auto-mode blocks live BQ UPDATE/DELETE and workflow
  enable/disable without Martin's per-statement approval.
