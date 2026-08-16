-- ============================================================================
-- supabase-migration-case-study-fields.sql
--
-- This file was referenced by app.py / edit_project.html ("requires the
-- Supabase migration to be run first") but was missing from the project.
-- This is almost certainly why editing a project failed with a generic
-- error: the admin edit form POSTs these columns on every save, and if
-- they don't exist yet, PostgREST rejects the whole update.
--
-- Run this once in the Supabase SQL editor for your project
-- (Project -> SQL Editor -> New query -> paste -> Run).
-- It's safe to run more than once (IF NOT EXISTS guards on every column).
-- ============================================================================

alter table projects add column if not exists status text default 'live';
alter table projects add column if not exists problem text;
alter table projects add column if not exists solution text;
alter table projects add column if not exists architecture text;
alter table projects add column if not exists challenges text;
alter table projects add column if not exists results text;
alter table projects add column if not exists lessons_learned text;
alter table projects add column if not exists future_improvements text;
alter table projects add column if not exists featured_rank integer;

-- Backfill any existing rows so status is never null (index.html / admin.html
-- check project.status == 'coming_soon', so null is fine too, but this keeps
-- the column meaningful for filtering/sorting later).
update projects set status = 'live' where status is null;
