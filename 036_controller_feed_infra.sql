-- 036_controller_feed_infra.sql
-- Adds two things the controller can watch: the Dealerslink inventory feed,
-- and the health of the boxes that carry it. Paste-safe: no BEGIN/COMMIT,
-- idempotent, safe to run twice.
--
-- SELF-GATING VIEWS
-- Every view here ends in `where public.gs_is_platform()`. That matters:
-- a plain view runs with its OWNER's privileges, so granting it to `anon`
-- would otherwise let any tenant page holding the anon key read it. The
-- claim check inside the view body means a caller without the platform claim
-- gets zero rows no matter which key they hold, and nothing about
-- dealer_feeds' own grants or RLS has to change.
--
-- dealer_feeds carries FTP credentials and secret_token. Those columns are
-- named-excluded from the view below and must stay that way.

-- ------------------------------------------------------------- feed health
-- One row per configured feed with its newest run folded in.
--
-- NOTE ON STALENESS: dealer_feed_runs only gets a row when the vendor's file
-- actually CHANGED. The relay fetches every 30 minutes but skips identical
-- files, so observed gaps between rows run 9-15 hours. Anything under ~26h
-- is normal and must not be treated as a fault.
create or replace view public.gs_feed_health as
select f.id                      as feed_id,
       f.app_id,
       d.name                    as app_name,
       f.provider,
       f.mode,
       f.enabled,
       f.seller_ref,
       f.last_run_at,
       f.last_status,
       r.started_at,
       r.finished_at,
       r.status                  as run_status,
       r.rows_seen,
       r.rows_created,
       r.rows_updated,
       r.rows_skipped,
       r.rows_withdrawn,
       r.errors,
       r.notes,
       extract(epoch from (now() - f.last_run_at))::bigint as age_s
from public.dealer_feeds f
-- d.id is uuid, f.app_id is text. Cast the UUID side to text, never the
-- other way: text -> uuid throws on any row whose app_id is not a valid
-- UUID, which would take the whole view down over one bad record.
left join public.deployments d on d.id::text = f.app_id
left join lateral (
  select * from public.dealer_feed_runs fr
   where fr.feed_id = f.id
   order by fr.finished_at desc nulls last
   limit 1
) r on true
where public.gs_is_platform();

-- Run history for the detail panel.
create or replace view public.gs_feed_runs as
select fr.id, fr.feed_id, fr.app_id, fr.seller_ref,
       fr.started_at, fr.finished_at, fr.status,
       fr.rows_seen, fr.rows_created, fr.rows_updated,
       fr.rows_skipped, fr.rows_withdrawn, fr.errors, fr.notes
from public.dealer_feed_runs fr
where public.gs_is_platform();

grant select on public.gs_feed_health, public.gs_feed_runs to anon, authenticated;

-- -------------------------------------------------------------- host beats
-- Proxmox is behind CGNAT, so nothing can poll it. The box PUSHES a beat
-- every five minutes and silence is the signal: a host that stops beating is
-- a host whose network died, which is exactly the failure that took the feed
-- down on 2026-10-03.
create table if not exists public.gs_host_beats (
  id                 bigserial primary key,
  host               text        not null,
  beat_at            timestamptz not null default now(),
  uptime_s           bigint,
  load1              numeric,
  mem_used_pct       numeric,
  disk_used_pct      numeric,
  failed_units       integer,
  failed_unit_names  text,
  dns_ok             boolean,
  feed_timer_ok      boolean,
  last_backup_status text,
  extra              jsonb
);

create index if not exists gs_host_beats_host_time
  on public.gs_host_beats (host, beat_at desc);

alter table public.gs_host_beats enable row level security;

drop policy if exists gs_platform_host_beats on public.gs_host_beats;
create policy gs_platform_host_beats on public.gs_host_beats
  as permissive for all to anon, authenticated
  using (public.gs_is_platform() or auth.role() = 'service_role')
  with check (public.gs_is_platform() or auth.role() = 'service_role');

grant select, insert, delete on public.gs_host_beats to anon, authenticated;
grant usage, select on sequence public.gs_host_beats_id_seq to anon, authenticated;

-- Latest beat per host, with its age. `age_s` is what the console colours on:
-- beats arrive every 5 minutes, so past ~15 minutes the host is not talking.
create or replace view public.gs_host_health as
select b.host, b.beat_at, b.uptime_s, b.load1, b.mem_used_pct, b.disk_used_pct,
       b.failed_units, b.failed_unit_names, b.dns_ok, b.feed_timer_ok,
       b.last_backup_status, b.extra,
       extract(epoch from (now() - b.beat_at))::bigint as age_s
from (
  select distinct on (host) *
    from public.gs_host_beats
   order by host, beat_at desc
) b
where public.gs_is_platform();

grant select on public.gs_host_health to anon, authenticated;
