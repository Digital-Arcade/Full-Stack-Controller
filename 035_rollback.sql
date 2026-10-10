-- 035_rollback.sql — reverses 035 only. Leaves 034 (capture) intact.
drop view if exists public.gs_dead_files;
drop view if exists public.gs_fleet;
drop policy if exists gs_platform_revisions on public.gs_revisions;
drop policy if exists gs_platform_revision_blobs on public.gs_revision_blobs;
drop policy if exists gs_platform_watchdogs on public.gs_watchdogs;
drop policy if exists gs_platform_alerts on public.gs_alerts;
drop function if exists public.gs_is_platform();
revoke all on public.gs_revisions, public.gs_revision_blobs,
              public.gs_watchdogs, public.gs_alerts from anon, authenticated;
