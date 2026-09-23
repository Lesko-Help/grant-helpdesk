-- 017 — Dedupe ticket_metadata and grant_ticket_labels to one row per content_id.
--
-- NOT YET RUN. The overseer runs this, not the worktree session that wrote
-- it — see ORDER OF RUN below. Rewritten (2026-09-23, Martin's approval:
-- "Approve, safer rewrite") from a CREATE OR REPLACE TABLE version: checked
-- live, `ticket_metadata.content_id` is mode REQUIRED and CTAS would
-- silently rebuild the table with it NULLABLE; `grant_ticket_labels` carries
-- a table description ("AI classification of confirmed questions...") that
-- CTAS would drop, since CREATE OR REPLACE TABLE ... AS SELECT does not
-- carry over the source table's schema options, only its column types. Both
-- confirmed against INFORMATION_SCHEMA immediately before this rewrite.
--
-- This version instead does DELETE + INSERT inside a single transaction per
-- table, touching only the content_ids that actually have duplicates — every
-- other row, and the table's own schema (column modes, description, any
-- other option), is left completely alone.
--
-- Reviewed 2026-09-23 (see brief's "## Agentic review"): the kept-rows temp
-- table and the row-count guard now live INSIDE each BEGIN TRANSACTION, not
-- before it — built before the transaction, a concurrent app write to a
-- duplicated content_id (e.g. update_ticket_meta) between the snapshot and
-- the DELETE would be silently lost (DELETE removes the concurrent write,
-- INSERT puts back the stale snapshot). Inside the transaction, BigQuery's
-- isolation means that same concurrent write instead aborts the
-- transaction — a conflict looks like a conflict, not a silent loss. Each
-- transaction also now ASSERTs its own result before COMMIT, so a wrong
-- result rolls back instead of only being visible in a commented-out query
-- someone has to remember to run.
--
-- ── ORDER OF RUN — read before running ────────────────────────────────────
--
-- Run this ONLY after:
--   1. This branch (dedupe-ticket-tables) has landed on main, AND
--   2. Dataform has compiled the writer fix from main (hourly release
--      config; allow up to 1 hour after landing).
-- The writer fix (QUALIFY ROW_NUMBER() ... = 1 in grant_question_classifier
-- and grant_ticket_labels, commit 61beeac) stops NEW same-batch duplicates.
-- Until that fix is live, the grant-helpdesk-5min workflow keeps running the
-- old MERGE every 30 minutes and will re-insert duplicates as fast as this
-- migration removes them. Running this migration before the fix compiles
-- would look like it worked, then silently undo itself.
--
-- The writer fix only stops same-batch duplicates (35 of 38 live
-- ticket_metadata groups, all sharing one classified_at). 3 classifier
-- groups and 6 of the 32 grant_ticket_labels groups have different
-- timestamps, pointing at overlapping runs (the scheduled workflow, the
-- hourly release, and pytest's remote trigger hitting the same live repo) —
-- QUALIFY cannot stop those. The uniqueKey(content_id) assertions below are
-- the guard that catches any of those still happening after this runs, not
-- the writer fix alone. Stopping pytest's remote trigger from hitting the
-- live repo, and an absence/heartbeat alert for the hourly
-- poll-dataform-failures job itself (rule 4 — silence is a failure), are
-- both follow-ups the overseer owns; not built in this branch.
--
-- Also expect noise right after landing: every */30 grant-helpdesk-5min
-- Dataform invocation between "writer fix compiles" and "this migration
-- runs" will report state=FAILED (tagged `helpdesk`) because both
-- assertions are red, and the project-wide "a Dataform invocation failed"
-- policy will email each one. That's expected — nothing else is failing.
-- Run this migration promptly after the first compile to stop it, and warn
-- Martin those emails are coming.
--
-- ── The rule ───────────────────────────────────────────────────────────────
--
-- One row per content_id, newest wins (Martin, 2026-09-14, refined
-- 2026-09-23). Pure newest-wins — no backfilling fields from an older row
-- into the surviving one, even where the older row has a value (e.g.
-- assigned_to) the newer row lacks.
--
-- ticket_metadata: ORDER BY updated_at DESC. All 26 live dup groups are
-- timestamp-safe (no two rows in any group share updated_at), so no
-- secondary key is needed.
--
-- grant_ticket_labels: ORDER BY labeled_at DESC, TO_JSON_STRING(t) DESC.
-- Two groups (comment_147039001, comment_147274739) have rows tied on
-- labeled_at with different label content — a plain ORDER BY labeled_at DESC
-- is non-deterministic on those in BigQuery. TO_JSON_STRING(t) DESC breaks
-- the tie deterministically: confirmed it selects inappropriate/Other for
-- comment_147039001 (matches the 3-of-4 majority) and domain='Other' for
-- comment_147274739 (arbitrary content, but fixed and reproducible).
--
-- ── Row counts, measured live 2026-09-23 (re-check before running — stale ──
-- ──          the moment either table changes again)                        ──
--
--   ticket_metadata:      7,366 rows / 7,084 distinct content_id today
--                          -> expect exactly 7,084 rows after this runs
--   grant_ticket_labels:  5,894 rows / 5,812 distinct content_id today
--                          -> expect exactly 5,812 rows after this runs
--
-- ── Backups (already created, non-destructive, this session) ─────────────
--
--   bigtribebuilders.grant_helpdesk.ticket_metadata_backup_20260923
--     (7,366 rows, full untouched copy)
--   bigtribebuilders.grant_helpdesk.grant_ticket_labels_backup_20260923
--     (5,894 rows, full untouched copy)

-- ── STEP 1 — dedupe ticket_metadata ───────────────────────────────────────
--
-- Sanity check before running — expect 282 (26 groups' worth of extra rows):
--
--   SELECT SUM(cnt - 1) FROM (
--     SELECT content_id, COUNT(*) AS cnt
--     FROM `bigtribebuilders.grant_helpdesk.ticket_metadata`
--     GROUP BY content_id HAVING COUNT(*) > 1
--   );

BEGIN TRANSACTION;

-- Snapshot of "how many rows this table SHOULD have once every content_id
-- is unique" — taken here, before the DELETE, so the post-COMMIT ASSERT
-- below is checking against the state at transaction start, not recomputing
-- from a table the DELETE already changed (which would trivially always
-- match).
CREATE TEMP TABLE ticket_metadata_expected_row_count AS
SELECT COUNT(DISTINCT content_id) AS expected_rows
FROM `bigtribebuilders.grant_helpdesk.ticket_metadata`;

-- Computed once, read twice below (the DELETE's id list and the INSERT's
-- rows) so the two statements can't disagree with each other. Inside the
-- transaction (not before it — see the header comment) so a concurrent
-- write to one of these content_ids aborts this transaction instead of
-- being silently overwritten by a stale snapshot.
CREATE TEMP TABLE ticket_metadata_kept_rows AS
SELECT * EXCEPT(rn) FROM (
  SELECT
    *,
    ROW_NUMBER() OVER (
      PARTITION BY content_id
      ORDER BY updated_at DESC
    ) AS rn
  FROM `bigtribebuilders.grant_helpdesk.ticket_metadata`
  -- Scope to duplicated content_ids only — computed here at run time, never
  -- a hard-coded list, so this stays correct even if the live counts have
  -- drifted since 2026-09-23.
  WHERE content_id IN (
    SELECT content_id
    FROM `bigtribebuilders.grant_helpdesk.ticket_metadata`
    GROUP BY content_id
    HAVING COUNT(*) > 1
  )
)
WHERE rn = 1;

-- Removes ALL rows (winner + losers) for each duplicated content_id — every
-- non-duplicated row in the table is never touched by this statement.
DELETE FROM `bigtribebuilders.grant_helpdesk.ticket_metadata`
WHERE content_id IN (SELECT content_id FROM ticket_metadata_kept_rows);

-- Puts back exactly one row — the newest-wins winner — per content_id
-- removed above.
INSERT INTO `bigtribebuilders.grant_helpdesk.ticket_metadata`
SELECT * FROM ticket_metadata_kept_rows;

-- Guards: a wrong result rolls back this transaction instead of landing
-- silently and only being caught by a manual query someone has to remember
-- to run.
ASSERT (
  SELECT COUNT(*) FROM (
    SELECT content_id
    FROM `bigtribebuilders.grant_helpdesk.ticket_metadata`
    GROUP BY content_id
    HAVING COUNT(*) > 1
  )
) = 0 AS 'ticket_metadata still has a duplicated content_id after dedupe';

ASSERT (
  SELECT COUNT(*) FROM `bigtribebuilders.grant_helpdesk.ticket_metadata`
) = (SELECT expected_rows FROM ticket_metadata_expected_row_count)
  AS 'ticket_metadata row count does not match its pre-delete distinct content_id count';

COMMIT TRANSACTION;

-- Sanity check after — expect 7,084 rows, 0 duplicate content_ids (now also
-- enforced by the ASSERTs above, not just this manual query):
--
--   SELECT COUNT(*) AS total, COUNT(DISTINCT content_id) AS distinct_ids
--   FROM `bigtribebuilders.grant_helpdesk.ticket_metadata`;

-- ── STEP 2 — dedupe grant_ticket_labels ───────────────────────────────────
--
-- Sanity check before running — expect 82 (32 groups' worth of extra rows):
--
--   SELECT SUM(cnt - 1) FROM (
--     SELECT content_id, COUNT(*) AS cnt
--     FROM `bigtribebuilders.grant_helpdesk.grant_ticket_labels`
--     GROUP BY content_id HAVING COUNT(*) > 1
--   );

BEGIN TRANSACTION;

CREATE TEMP TABLE grant_ticket_labels_expected_row_count AS
SELECT COUNT(DISTINCT content_id) AS expected_rows
FROM `bigtribebuilders.grant_helpdesk.grant_ticket_labels`;

CREATE TEMP TABLE grant_ticket_labels_kept_rows AS
SELECT * EXCEPT(rn) FROM (
  SELECT
    *,
    ROW_NUMBER() OVER (
      PARTITION BY content_id
      -- Secondary key breaks the 2 genuine labeled_at ties deterministically
      -- (comment_147039001, comment_147274739) — see header comment.
      ORDER BY labeled_at DESC, TO_JSON_STRING(t) DESC
    ) AS rn
  FROM `bigtribebuilders.grant_helpdesk.grant_ticket_labels` AS t
  WHERE content_id IN (
    SELECT content_id
    FROM `bigtribebuilders.grant_helpdesk.grant_ticket_labels`
    GROUP BY content_id
    HAVING COUNT(*) > 1
  )
)
WHERE rn = 1;

DELETE FROM `bigtribebuilders.grant_helpdesk.grant_ticket_labels`
WHERE content_id IN (SELECT content_id FROM grant_ticket_labels_kept_rows);

INSERT INTO `bigtribebuilders.grant_helpdesk.grant_ticket_labels`
SELECT * FROM grant_ticket_labels_kept_rows;

ASSERT (
  SELECT COUNT(*) FROM (
    SELECT content_id
    FROM `bigtribebuilders.grant_helpdesk.grant_ticket_labels`
    GROUP BY content_id
    HAVING COUNT(*) > 1
  )
) = 0 AS 'grant_ticket_labels still has a duplicated content_id after dedupe';

ASSERT (
  SELECT COUNT(*) FROM `bigtribebuilders.grant_helpdesk.grant_ticket_labels`
) = (SELECT expected_rows FROM grant_ticket_labels_expected_row_count)
  AS 'grant_ticket_labels row count does not match its pre-delete distinct content_id count';

COMMIT TRANSACTION;

-- Sanity check after — expect 5,812 rows, 0 duplicate content_ids, and the
-- two tied groups resolved as documented above:
--
--   SELECT COUNT(*) AS total, COUNT(DISTINCT content_id) AS distinct_ids
--   FROM `bigtribebuilders.grant_helpdesk.grant_ticket_labels`;
--
--   SELECT content_id, difficulty, domain, labeled_at
--   FROM `bigtribebuilders.grant_helpdesk.grant_ticket_labels`
--   WHERE content_id IN ('comment_147039001', 'comment_147274739');
--   -- expect: comment_147039001 -> inappropriate/Other
--   --         comment_147274739 -> domain='Other' (difficulty null)

-- ── Verify — schema untouched by the DELETE + INSERT pattern ─────────────
--
-- Confirms this migration did NOT do what the earlier CREATE OR REPLACE
-- TABLE version would have: silently widened content_id to NULLABLE, or
-- dropped grant_ticket_labels' table description.
--
--   SELECT column_name, is_nullable
--   FROM `bigtribebuilders.grant_helpdesk.INFORMATION_SCHEMA.COLUMNS`
--   WHERE table_name = 'ticket_metadata' AND column_name = 'content_id';
--   -- expect is_nullable = 'NO'
--
--   SELECT option_value
--   FROM `bigtribebuilders.grant_helpdesk.INFORMATION_SCHEMA.TABLE_OPTIONS`
--   WHERE table_name = 'grant_ticket_labels' AND option_name = 'description';
--   -- expect the AI-classification description, unchanged

-- ── Verify — both uniqueKey(content_id) assertions go green ──────────────
--
-- After this runs (and Dataform has recompiled from main per ORDER OF RUN
-- above), `assert_ticket_metadata_unique_content_id.sqlx` and
-- `assert_grant_ticket_labels_unique_content_id.sqlx` (both already RED,
-- proven against live data before this migration) are expected to go GREEN
-- on the next Dataform run — that transition is the done-when #1 proof.

-- ── Undo ───────────────────────────────────────────────────────────────────
--
-- Restores ONLY the content_ids this migration touched, from the untouched
-- backups — not a full-table WHERE TRUE swap (review finding #6: that would
-- also discard every app write either table received after the backup was
-- taken, e.g. update_ticket_meta or set_ticket_assignee). The scope is
-- exactly the content_ids that had duplicates in the backup, which is also
-- exactly the set this migration's DELETE + INSERT touched — every
-- non-duplicated row was never part of this migration and so is never part
-- of the Undo either.
--
-- NOT a CREATE OR REPLACE TABLE ... AS SELECT from the backup — checked live
-- and the backups themselves (made via CREATE TABLE ... AS SELECT * FROM the
-- live table, same CTAS mechanism this migration deliberately avoids above)
-- ALREADY lost the schema this migration protects: content_id is NULLABLE on
-- ticket_metadata_backup_20260923 (was REQUIRED on the live table), and
-- grant_ticket_labels_backup_20260923 has no description at all. A CTAS undo
-- would carry that data faithfully but silently reintroduce both schema
-- regressions into the live table. Same DELETE + INSERT shape as the
-- migration itself avoids that, because it never recreates the live table —
-- only replaces the rows it's scoped to, so the table's existing schema
-- (REQUIRED mode, description) is never touched:
--
--   BEGIN TRANSACTION;
--   DELETE FROM `bigtribebuilders.grant_helpdesk.ticket_metadata`
--   WHERE content_id IN (
--     SELECT content_id
--     FROM `bigtribebuilders.grant_helpdesk.ticket_metadata_backup_20260923`
--     GROUP BY content_id
--     HAVING COUNT(*) > 1
--   );
--   INSERT INTO `bigtribebuilders.grant_helpdesk.ticket_metadata`
--   SELECT * FROM `bigtribebuilders.grant_helpdesk.ticket_metadata_backup_20260923`
--   WHERE content_id IN (
--     SELECT content_id
--     FROM `bigtribebuilders.grant_helpdesk.ticket_metadata_backup_20260923`
--     GROUP BY content_id
--     HAVING COUNT(*) > 1
--   );
--   COMMIT TRANSACTION;
--
--   BEGIN TRANSACTION;
--   DELETE FROM `bigtribebuilders.grant_helpdesk.grant_ticket_labels`
--   WHERE content_id IN (
--     SELECT content_id
--     FROM `bigtribebuilders.grant_helpdesk.grant_ticket_labels_backup_20260923`
--     GROUP BY content_id
--     HAVING COUNT(*) > 1
--   );
--   INSERT INTO `bigtribebuilders.grant_helpdesk.grant_ticket_labels`
--   SELECT * FROM `bigtribebuilders.grant_helpdesk.grant_ticket_labels_backup_20260923`
--   WHERE content_id IN (
--     SELECT content_id
--     FROM `bigtribebuilders.grant_helpdesk.grant_ticket_labels_backup_20260923`
--     GROUP BY content_id
--     HAVING COUNT(*) > 1
--   );
--   COMMIT TRANSACTION;
