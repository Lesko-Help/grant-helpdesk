-- Migration 018: private_thread_workflow table
--
-- Holds close/assign/lane state for a 1:1 member-question thread, keyed on
-- thread_id — one row per thread, written only by coach_inbox.set_thread_workflow.
-- This dataset is helpdesk-owned, so MERGE is allowed here (unlike the
-- insert-only private_chat zone tables). assignee/lane are columns for a
-- later task; this migration only lands them, nothing writes them yet.
--
-- NOT YET RUN. The worktree session that wrote this never runs it — the
-- overseer runs it against bigtribebuilders.grant_helpdesk on Martin's word,
-- before the app that depends on this table deploys.

CREATE TABLE IF NOT EXISTS `bigtribebuilders.grant_helpdesk.private_thread_workflow` (
  thread_id   STRING,
  status      STRING,
  assignee    STRING,
  lane        STRING,
  closed_at   TIMESTAMP,
  updated_at  TIMESTAMP,
  updated_by  STRING
);
