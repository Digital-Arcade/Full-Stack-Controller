-- 040_infra_findings.sql
-- Findings raised by the infra triage pass, and the remedy queue the boxes
-- pull from. Paste-safe, idempotent, no BEGIN/COMMIT. Requires 036.
--
-- WHY A SEPARATE TABLE: gs_alerts is keyed to a deployment and a revision -
-- it answers "what changed in an app". An infra finding has neither. Reusing
-- it would mean nullable columns on a table whose contract is already relied
-- on by the changes timeline.

create table if not exists public.gs_infra_findings (
  id            bigserial primary key,
  host          text        not null,
  kind          text        not null,
  -- Stable identity for "the same problem". Triage checks for an open row
  -- with this fingerprint before inserting, so a fault that persists for a
  -- day is one finding, not 288 of them.
  fingerprint   text        not null,
  severity      text        not null default 'warn',
  verdict       text,
  steps         text,
  evidence      jsonb,
  -- Remedy names come from a fixed allowlist in the Worker. The model may
  -- VETO a candidate; it can never invent one, and no shell is ever stored
  -- here or sent to a host.
  remedy        text,
  remedy_state  text        not null default 'none',
  remedy_result jsonb,
  created_at    timestamptz not null default now(),
  resolved_at   timestamptz,
  acknowledged  boolean     not null default false
);

create index if not exists gs_infra_findings_open
  on public.gs_infra_findings (host, fingerprint) where resolved_at is null;
create index if not exists gs_infra_findings_recent
  on public.gs_infra_findings (created_at desc);

alter table public.gs_infra_findings enable row level security;

drop policy if exists gs_platform_infra_findings on public.gs_infra_findings;
create policy gs_platform_infra_findings on public.gs_infra_findings
  as permissive for all to anon, authenticated
  using (public.gs_is_platform() or auth.role() = 'service_role')
  with check (public.gs_is_platform() or auth.role() = 'service_role');

grant select, insert, update, delete on public.gs_infra_findings to anon, authenticated;
grant usage, select on sequence public.gs_infra_findings_id_seq to anon, authenticated;

-- Self-gating, same as every view in 036: a plain view runs with its owner's
-- privileges, so the claim check has to live in the body.
create or replace view public.gs_infra_open as
select f.*, extract(epoch from (now() - f.created_at))::bigint as age_s
from public.gs_infra_findings f
where f.resolved_at is null
  and public.gs_is_platform();

grant select on public.gs_infra_open to anon, authenticated;
