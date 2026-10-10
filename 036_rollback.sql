-- 036_rollback.sql — undoes 036_controller_feed_infra.sql.
drop view if exists public.gs_host_health;
drop view if exists public.gs_feed_runs;
drop view if exists public.gs_feed_health;
drop policy if exists gs_platform_host_beats on public.gs_host_beats;
drop table if exists public.gs_host_beats;
