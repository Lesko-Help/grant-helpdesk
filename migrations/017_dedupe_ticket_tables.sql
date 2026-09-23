-- 017 — Dedupe ticket_metadata and grant_ticket_labels to one row per content_id.
--
-- NOT YET RUN. Written per the dedupe-ticket-tables brief's done-when #4: the
-- overseer reports the exact row counts and tiebreak picks below to Martin,
-- and only Martin's explicit approval turns this from a written file into a
-- statement someone actually runs.
--
-- The rule (Martin, 2026-09-14, refined 2026-09-23): one row per content_id,
-- newest wins. For ticket_metadata that's ORDER BY updated_at DESC. For
-- grant_ticket_labels that's ORDER BY labeled_at DESC. "Newest wins" is pure —
-- no backfilling fields from an older row into the surviving one, even where
-- the older row happens to have a value (e.g. assigned_to) the newer row
-- lacks. Confirmed explicitly for the 4 real conflicts below.
--
-- ── Why CREATE OR REPLACE, not DELETE ─────────────────────────────────────
--
-- BigQuery has no row-level DELETE without a real row identifier. Most of the
-- duplicate rows in both tables are byte-identical copies of each other (21
-- of 26 ticket_metadata groups; 24 of 32 grant_ticket_labels groups) — there
-- is no column, or combination of columns, that names "this one copy" out of
-- several that read exactly the same. So this migration rebuilds each table
-- from a deduplicated SELECT instead of deleting specific rows:
--
--   CREATE OR REPLACE TABLE ... AS
--   SELECT * EXCEPT(rn) FROM (
--     SELECT *, ROW_NUMBER() OVER (PARTITION BY content_id ORDER BY ...) AS rn
--     FROM ...
--   ) WHERE rn = 1
--
-- ── Why ORDER BY needs a second key ───────────────────────────────────────
--
-- ROW_NUMBER() OVER (... ORDER BY <timestamp> DESC) is only deterministic
-- when no two rows in a group share the same timestamp. Checked every dup
-- group in both tables for this before writing the queries below:
--
--   ticket_metadata: all 26 groups are timestamp-safe. The 21 pure-copy
--   groups are byte-identical, so which copy ROW_NUMBER() picks is moot. The
--   5 non-identical groups (4 real conflicts + comment_147732168, see below)
--   never have two rows with the same updated_at. ORDER BY updated_at DESC
--   alone is enough — no secondary key needed.
--
--   grant_ticket_labels: NOT timestamp-safe. Two groups have two rows with
--   the exact same labeled_at but different label values:
--     comment_147039001 (4 rows total: 1x easy/Community Support,
--       3x inappropriate/Other — the 3x are mutually tied on labeled_at too)
--     comment_147274739 (2 rows: null/Community Support vs null/Other, tied
--       on labeled_at)
--   Plain ORDER BY labeled_at DESC would let BigQuery pick arbitrarily,
--   possibly differently on a re-run. Added TO_JSON_STRING(t) DESC as a
--   second, deterministic key — confirmed it selects inappropriate/Other for
--   comment_147039001 (matching the 3-of-4 majority) and domain='Other' for
--   comment_147274739 (arbitrary content but a fixed, reproducible pick).
--
-- ── Row counts, measured live 2026-09-23 (re-check before running — these ──
-- ──          numbers are stale the moment either table changes again)      ──
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

CREATE OR REPLACE TABLE `bigtribebuilders.grant_helpdesk.ticket_metadata` AS
SELECT * EXCEPT(rn) FROM (
  SELECT
    *,
    ROW_NUMBER() OVER (
      PARTITION BY content_id
      ORDER BY updated_at DESC
    ) AS rn
  FROM `bigtribebuilders.grant_helpdesk.ticket_metadata`
)
WHERE rn = 1;

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

CREATE OR REPLACE TABLE `bigtribebuilders.grant_helpdesk.grant_ticket_labels` AS
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
)
WHERE rn = 1;

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

-- ── Verify — both uniqueKey(content_id) assertions go green ──────────────
--
-- After this runs, `assert_ticket_metadata_unique_content_id.sqlx` and
-- `assert_grant_ticket_labels_unique_content_id.sqlx` (both already RED,
-- proven against live data before this migration) are expected to go GREEN
-- on the next Dataform run — that transition is the done-when #1 proof.

-- ── Undo ───────────────────────────────────────────────────────────────────
--
-- Restores the pre-dedupe table exactly, from the untouched backup. Only if
-- something looks wrong after running this migration.
--
--   CREATE OR REPLACE TABLE `bigtribebuilders.grant_helpdesk.ticket_metadata` AS
--   SELECT * FROM `bigtribebuilders.grant_helpdesk.ticket_metadata_backup_20260923`;
--
--   CREATE OR REPLACE TABLE `bigtribebuilders.grant_helpdesk.grant_ticket_labels` AS
--   SELECT * FROM `bigtribebuilders.grant_helpdesk.grant_ticket_labels_backup_20260923`;
