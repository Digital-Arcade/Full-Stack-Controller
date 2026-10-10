-- 035_controller_access.sql
-- Opens the four controller tables from 034 to the controller, and to nothing
-- else. Paste-safe: no BEGIN/COMMIT.
--
-- THE CLAIM
-- gs_is_platform() reads a gs_platform claim the Worker mints only for the
-- controller, signed with SUPABASE_JWT_SECRET exactly as gsAppAuthHeaders
-- already signs the app_id claim (worker.js:14307). Anything holding this
-- claim bypasses tenant isolation entirely, so it is minted in one place,
-- behind gsOwnerCredsMatch, and never inlined into a tenant page.
--
-- Reads BOTH claim shapes. PostgREST exposes claims as individual
-- request.jwt.claim.<name> GUCs on older versions and as a single
-- request.jwt.claims json on newer ones. Checking both means this works
-- without me having to assume which one gs_current_app_id() happens to use.

create or replace function public.gs_is_platform()
returns boolean
language sql
stable
as $$
  select coalesce(
    nullif(current_setting('request.jwt.claim.gs_platform', true), ''),
    (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'gs_platform')
  ) = 'true'
$$;

-- ---------------------------------------------------------------- revisions
-- Platform sees everything. An app owner sees the history of their own
-- deployments through the same clause every gs_scoped_* policy already uses,
-- so the controller is a superset of what they can already reach, not a
-- parallel permission system.
drop policy if exists gs_platform_revisions on public.gs_revisions;
create policy gs_platform_revisions on public.gs_revisions
  as permissive for all to anon, authenticated
  using (
    public.gs_is_platform()
    or auth.role() = 'service_role'
    or exists (select 1 from public.deployments d
                where d.id = gs_revisions.deployment_id
                  and d.user_id = auth.uid())
  )
  with check (
    public.gs_is_platform() or auth.role() = 'service_role'
  );

-- -------------------------------------------------------------------- blobs
-- NO owner clause, deliberately. Blobs are content-addressed and shared across
-- every tenant: two apps with an identical GenieShell.tsx point at one row.
-- There is no deployment_id to scope on, and adding one would defeat the
-- dedupe that keeps this table flat. Handing an owner read access here would
-- hand them other tenants' source. Platform and service_role only.
drop policy if exists gs_platform_revision_blobs on public.gs_revision_blobs;
create policy gs_platform_revision_blobs on public.gs_revision_blobs
  as permissive for all to anon, authenticated
  using (public.gs_is_platform() or auth.role() = 'service_role')
  with check (public.gs_is_platform() or auth.role() = 'service_role');

-- ---------------------------------------------------------------- watchdogs
-- Rules are platform configuration. Owners do not get to disable the watchdog
-- that is watching them.
drop policy if exists gs_platform_watchdogs on public.gs_watchdogs;
create policy gs_platform_watchdogs on public.gs_watchdogs
  as permissive for all to anon, authenticated
  using (public.gs_is_platform() or auth.role() = 'service_role')
  with check (public.gs_is_platform() or auth.role() = 'service_role');

-- ------------------------------------------------------------------- alerts
-- Owners may read alerts raised against their own deployments; only the
-- platform may acknowledge or clear them.
drop policy if exists gs_platform_alerts on public.gs_alerts;
create policy gs_platform_alerts on public.gs_alerts
  as permissive for all to anon, authenticated
  using (
    public.gs_is_platform()
    or auth.role() = 'service_role'
    or exists (select 1 from public.deployments d
                where d.id = gs_alerts.deployment_id
                  and d.user_id = auth.uid())
  )
  with check (
    public.gs_is_platform() or auth.role() = 'service_role'
  );

-- ------------------------------------------------------------------- grants
-- RLS decides the rows; grants decide whether the role may ask at all. Without
-- these the policies above are unreachable and every controller read is a
-- bare permission error rather than an empty set.
grant select, insert, update, delete
  on public.gs_revisions, public.gs_revision_blobs,
     public.gs_watchdogs, public.gs_alerts
  to anon, authenticated;
grant usage, select on sequence public.gs_revisions_id_seq to anon, authenticated;
grant usage, select on sequence public.gs_alerts_id_seq to anon, authenticated;
grant usage, select on sequence public.gs_watchdogs_id_seq to anon, authenticated;

-- ------------------------------------------------------- controller reporting
-- Fleet view: one row per deployment with its latest capture. This is the
-- controller's home screen and it must stay cheap, so it reads the newest
-- revision per deployment rather than aggregating the whole history.
create or replace view public.gs_fleet as
select d.id                       as deployment_id,
       d.name,
       d.status,
       d.user_id,
       d."customDomain"           as custom_domain,
       r.id                       as latest_revision,
       r.surface,
       r.file_count,
       r.byte_size,
       r.created_at               as last_change,
       r.actor                    as last_actor,
       coalesce(a.open_alerts, 0) as open_alerts
from public.deployments d
left join lateral (
  select * from public.gs_revisions gr
   where gr.deployment_id = d.id
   order by gr.id desc limit 1
) r on true
left join lateral (
  select count(*) as open_alerts from public.gs_alerts ga
   where ga.deployment_id = d.id and not ga.acknowledged
) a on true;

-- Dead-file detector. Files uploaded to a project land in a folder named after
-- the app instead of src/, are never part of the build, and never render
-- (HANDOFF section 4). Dealer-Exchange 2 (1) is carrying four of them right
-- now, including a second supabase-app.ts. This finds every instance across
-- the fleet from the captured trees, with no extra scanning machinery.
create or replace view public.gs_dead_files as
select r.deployment_id,
       d.name,
       k.key as path,
       r.created_at as seen_at
from public.gs_revisions r
join public.deployments d on d.id = r.deployment_id
cross join lateral jsonb_object_keys(r.file_hashes) as k(key)
where r.id = (select max(id) from public.gs_revisions gr
               where gr.deployment_id = r.deployment_id
                 and gr.surface = r.surface)
  and r.surface = 'app'
  and k.key not like 'src/%'
  and k.key not in ('index.html','manifest.json','sw.js','gs-push.js',
                    'package.json','vite.config.ts','tsconfig.json','README.md');

grant select on public.gs_fleet, public.gs_dead_files to anon, authenticated;
