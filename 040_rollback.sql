-- 040_rollback.sql
drop view if exists public.gs_infra_open;
drop policy if exists gs_platform_infra_findings on public.gs_infra_findings;
drop table if exists public.gs_infra_findings;
