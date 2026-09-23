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

-- Computed once, read twice below (the DELETE's id list and the INSERT's
-- rows) so the two statements can't disagree with each other.
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

BEGIN TRANSACTION;

-- Removes ALL rows (winner + losers) for each duplicated content_id — every
-- non-duplicated row in the table is never touched by this statement.
DELETE FROM `bigtribebuilders.grant_helpdesk.ticket_metadata`
WHERE content_id IN (SELECT content_id FROM ticket_metadata_kept_rows);

-- Puts back exactly one row — the newest-wins winner — per content_id
-- removed above.
INSERT INTO `bigtribebuilders.grant_helpdesk.ticket_metadata`
SELECT * FROM ticket_metadata_kept_rows;

COMMIT TRANSACTION;

-- Sanity check after — expect 7,084 rows, 0 duplicate content_ids:
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

BEGIN TRANSACTION;

DELETE FROM `bigtribebuilders.grant_helpdesk.grant_ticket_labels`
WHERE content_id IN (SELECT content_id FROM grant_ticket_labels_kept_rows);

INSERT INTO `bigtribebuilders.grant_helpdesk.grant_ticket_labels`
SELECT * FROM grant_ticket_labels_kept_rows;

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
-- Restores the pre-dedupe tables exactly, from the untouched backups. Only
-- if something looks wrong after running this migration.
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
-- only replaces its rows, so its existing schema (REQUIRED mode,
-- description) is never touched:
--
--   BEGIN TRANSACTION;
--   DELETE FROM `bigtribebuilders.grant_helpdesk.ticket_metadata` WHERE TRUE;
--   INSERT INTO `bigtribebuilders.grant_helpdesk.ticket_metadata`
--   SELECT * FROM `bigtribebuilders.grant_helpdesk.ticket_metadata_backup_20260923`;
--   COMMIT TRANSACTION;
--
--   BEGIN TRANSACTION;
--   DELETE FROM `bigtribebuilders.grant_helpdesk.grant_ticket_labels` WHERE TRUE;
--   INSERT INTO `bigtribebuilders.grant_helpdesk.grant_ticket_labels`
--   SELECT * FROM `bigtribebuilders.grant_helpdesk.grant_ticket_labels_backup_20260923`;
--   COMMIT TRANSACTION;
