-- Public agency evidence is readable; all writes require the collector secret.
create schema if not exists quiet_cuts_private;
revoke all on schema quiet_cuts_private from public, anon, authenticated;
create table quiet_cuts_private.collector_credentials (
  singleton boolean primary key default true check (singleton),
  token_hash text not null
);

create table public.warn_snapshots (
  id bigint generated always as identity primary key,
  content_hash text not null unique,
  payload jsonb not null,
  stored_at timestamptz not null default now()
);
create table public.warn_observations (
  id bigint generated always as identity primary key,
  run_key text not null unique,
  snapshot_id bigint not null references public.warn_snapshots(id),
  checked_at timestamptz not null,
  source_hashes jsonb not null,
  recorded_at timestamptz not null default now()
);
create index warn_observations_checked_at_idx on public.warn_observations(checked_at desc, id desc);
create index warn_observations_snapshot_idx on public.warn_observations(snapshot_id);
alter table public.warn_snapshots enable row level security;
alter table public.warn_observations enable row level security;
create policy public_evidence_read on public.warn_snapshots for select to anon, authenticated using (true);
create policy public_observations_read on public.warn_observations for select to anon, authenticated using (true);
revoke all on public.warn_snapshots, public.warn_observations from anon, authenticated;
grant select on public.warn_snapshots, public.warn_observations to anon, authenticated;

-- A single transaction stores a validated version and its observation. No update/delete API.
create function public.ingest_snapshot(p_token text, p_payload jsonb, p_run_key text)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  v_checked timestamptz;
  v_hash text;
  v_snapshot bigint;
  v_previous jsonb;
  v_state text;
  v_count integer;
  v_total integer;
  v_result jsonb;
begin
  if p_token is null or not exists (
    select 1 from quiet_cuts_private.collector_credentials
    where token_hash = encode(sha256(convert_to(p_token, 'UTF8')), 'hex')
  ) then raise exception 'Collector authorization required' using errcode = '42501'; end if;
  if p_run_key is null or length(p_run_key) not between 1 and 200 then
    raise exception 'Invalid run key';
  end if;
  perform pg_advisory_xact_lock(72183904);
  select jsonb_build_object('snapshotId', snapshot_id, 'duplicateRun', true)
    into v_result from public.warn_observations where run_key = p_run_key;
  if v_result is not null then return v_result; end if;
  if jsonb_typeof(p_payload->'events') is distinct from 'array'
     or jsonb_typeof(p_payload->'metadata') is distinct from 'object'
     or octet_length(p_payload::text) > 20000000 then
    raise exception 'Invalid snapshot shape or size';
  end if;
  v_total := jsonb_array_length(p_payload->'events');
  if v_total < 1 or v_total > 50000 or (p_payload#>>'{metadata,totalRecords}')::integer is distinct from v_total then
    raise exception 'Invalid record count';
  end if;
  if (select count(distinct e->>'id') from jsonb_array_elements(p_payload->'events') e) <> v_total then
    raise exception 'Duplicate or missing source row IDs';
  end if;
  if exists (select 1 from jsonb_array_elements(p_payload->'events') e
    where coalesce(e->>'state','') not in ('CA','NY','WA') or coalesce(trim(e->>'company'),'') = ''
      or coalesce(e->>'workers','') !~ '^[0-9]+$' or coalesce(e->>'sourceUrl','') not like 'https://%'
      or coalesce(e->>'newsStatus','') <> 'unreviewed'
      or e->>'postedDate' is not null or e->>'firstNewsDate' is not null or e->>'newsUrl' is not null
      or e->>'latencyDays' is not null) then
    raise exception 'Invalid record or unsupported evidence';
  end if;
  v_checked := (p_payload#>>'{metadata,retrievedAt}')::timestamptz;
  if v_checked is null or v_checked > now() + interval '10 minutes' then
    raise exception 'A genuine retrieval timestamp is required';
  end if;
  select s.payload into v_previous from public.warn_observations o
    join public.warn_snapshots s on s.id=o.snapshot_id
    where o.checked_at <= v_checked order by o.checked_at desc, o.id desc limit 1;
  foreach v_state in array array['CA','NY','WA'] loop
    select count(*) into v_count from jsonb_array_elements(p_payload->'events') e where e->>'state'=v_state;
    if v_count < 1 or (p_payload->'metadata'->'counts'->>v_state)::integer is distinct from v_count then
      raise exception '%: missing source or inconsistent count', v_state;
    end if;
    if v_previous is not null and v_count < (v_previous->'metadata'->'counts'->>v_state)::integer * 0.7 then
      raise exception '%: record loss exceeds 30 percent; source review required', v_state;
    end if;
  end loop;
  -- Preserve multiplicity; ignore row positions and retrieval-only metadata for deduplication.
  select encode(sha256(convert_to(jsonb_agg(row_data order by row_data::text)::text,'UTF8')),'hex')
    into v_hash from (select e - 'id' - 'sourceRow' as row_data from jsonb_array_elements(p_payload->'events') e) r;
  insert into public.warn_snapshots(content_hash,payload) values(v_hash,p_payload)
    on conflict(content_hash) do nothing;
  select id into v_snapshot from public.warn_snapshots where content_hash=v_hash;
  insert into public.warn_observations(run_key,snapshot_id,checked_at,source_hashes)
    values(p_run_key,v_snapshot,v_checked,coalesce(p_payload#>'{metadata,snapshots}','[]'::jsonb));
  return jsonb_build_object('snapshotId',v_snapshot,'checkedAt',v_checked,'records',v_total);
end $$;
revoke all on function public.ingest_snapshot(text,jsonb,text) from public, anon, authenticated;
grant execute on function public.ingest_snapshot(text,jsonb,text) to anon;

-- Read-only API: the most recent successful observation, or the last one in a UTC month.
create function public.get_snapshot(p_month text default null)
returns jsonb language plpgsql stable security invoker set search_path = '' as $$
declare v_result jsonb;
begin
  if p_month is not null and p_month !~ '^[0-9]{4}-(0[1-9]|1[0-2])$' then
    raise exception 'Expected YYYY-MM';
  end if;
  select jsonb_set(s.payload, '{metadata}', (s.payload->'metadata') || jsonb_build_object(
    'snapshotId',s.id,'lastCheckedAt',o.checked_at,'archiveMonth',p_month,
    'trackingStartedAt',(select min(checked_at) from public.warn_observations),
    'historyNote','Archive months are captured source observations, not complete monthly layoff totals. Missing months were not observed.'
  )) into v_result
  from public.warn_observations o join public.warn_snapshots s on s.id=o.snapshot_id
  where p_month is null or (
    o.checked_at >= (p_month||'-01T00:00:00Z')::timestamptz
    and o.checked_at < (p_month||'-01T00:00:00Z')::timestamptz + interval '1 month')
  order by o.checked_at desc,o.id desc limit 1;
  return v_result;
end $$;
create function public.get_archive_months()
returns jsonb language sql stable security invoker set search_path = '' as $$
  select coalesce(jsonb_agg(row_data order by row_data->>'month' desc),'[]'::jsonb)
  from (select jsonb_build_object('month',to_char(checked_at at time zone 'UTC','YYYY-MM'),
    'lastCheckedAt',max(checked_at),'checks',count(*),'versions',count(distinct snapshot_id)) row_data
    from public.warn_observations group by to_char(checked_at at time zone 'UTC','YYYY-MM')) m;
$$;
revoke all on function public.get_snapshot(text), public.get_archive_months() from public, anon, authenticated;
grant execute on function public.get_snapshot(text), public.get_archive_months() to anon, authenticated;
notify pgrst, 'reload schema';
