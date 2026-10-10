-- 045_rollback.sql - undoes 045_feed_checks.sql.
-- The view must go back first: a column cannot be dropped while a view uses it.
-- A view cannot LOSE columns through CREATE OR REPLACE, so it is dropped and
-- re-created exactly as 036 made it.
drop view if exists public.gs_feed_health;
create view public.gs_feed_health as
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
left join public.deployments d on d.id::text = f.app_id
left join lateral (
  select * from public.dealer_feed_runs fr
   where fr.feed_id = f.id
   order by fr.finished_at desc nulls last
   limit 1
) r on true
where public.gs_is_platform();
grant select on public.gs_feed_health to anon, authenticated;

alter table public.dealer_feeds drop column if exists last_check_at;
alter table public.dealer_feeds drop column if exists last_check_result;
alter table public.dealer_feeds drop column if exists last_check_bytes;
alter table public.dealer_feeds drop column if exists last_check_note;
notify pgrst, 'reload schema';
