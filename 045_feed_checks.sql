-- 045_feed_checks.sql
-- Lets the controller tell a QUIET VENDOR from a BROKEN RELAY.
-- Paste-safe: no BEGIN/COMMIT, idempotent, safe to run twice. Requires 036.
--
-- WHY: dealer_feed_runs only gets a row when the vendor's file CHANGED. The
-- relay fetches every 30 minutes and skips identical files, so a vendor who
-- publishes nothing for 33 hours (2026-10-04 03:47 -> 10-05 12:49, 58 clean
-- "SAME" checks) and a relay that died 33 hours ago looked exactly alike from
-- here: "last import 33h ago". The box knew the difference. Nothing told us.
--
-- Now relay.sh reports every run, not just the ones that import. Four columns
-- on the feed row hold the newest report:
--
--   last_check_at      when the relay last told us anything
--   last_check_result  'changed'      the file was new and imported
--                      'same'         fetched fine, identical to the last one
--                      'fetch_failed' could not download it from the vendor
--                      'refused'      downloaded, but too small or not the
--                                     inventory file - not forwarded
--   last_check_bytes   size of the file it looked at
--   last_check_note    the relay's own words for a failure (curl exit code,
--                      why it refused). Never a credential: relay.sh builds it.
--
-- "Unchanged since" needs no column of its own: it is last_run_at, the last
-- time a changed file imported.

alter table public.dealer_feeds add column if not exists last_check_at     timestamptz;
alter table public.dealer_feeds add column if not exists last_check_result text;
alter table public.dealer_feeds add column if not exists last_check_bytes  bigint;
alter table public.dealer_feeds add column if not exists last_check_note   text;

-- Same view as 036 with the check columns appended. CREATE OR REPLACE VIEW
-- only allows new columns at the END, which is why they sit after age_s and
-- why the first twenty are repeated here unchanged, in the same order.
--
-- Still names every column: dealer_feeds carries secret_token and the FTP
-- credentials, and that list is the security boundary. Still ends in
-- gs_is_platform(), for the reason written at the top of 036.
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
       extract(epoch from (now() - f.last_run_at))::bigint as age_s,
       f.last_check_at,
       f.last_check_result,
       f.last_check_bytes,
       f.last_check_note,
       extract(epoch from (now() - f.last_check_at))::bigint as check_age_s
from public.dealer_feeds f
left join public.deployments d on d.id::text = f.app_id
left join lateral (
  select * from public.dealer_feed_runs fr
   where fr.feed_id = f.id
   order by fr.finished_at desc nulls last
   limit 1
) r on true
where public.gs_is_platform();

grant select on public.gs_feed_health to anon, authenticated;

-- PostgREST caches the schema; without this the Worker's PATCH to the new
-- columns answers "column not found" until the cache next reloads by itself.
notify pgrst, 'reload schema';
