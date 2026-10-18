# Quiet Cuts data API

Independent collection and persistent history for [Quiet Cuts](https://github.com/PCTEJA/quiet-cuts).
The private repository contains agency parsers, raw evidence, validation, database migrations,
and the hourly collection trigger. It has no website deployment credentials or deployment steps.

## Deployment

- GitHub repository: `PCTEJA/quiet-cuts-data` (private).
- Supabase project: `ygmxwkmvruiihjzeljtk`, `quiet-cuts-data`, US East, free plan at creation.
- API root: `https://ygmxwkmvruiihjzeljtk.supabase.co/rest/v1/rpc/`.
- GitHub variables: `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`.
- GitHub secret: `COLLECTOR_TOKEN`. Its SHA-256 hash is stored in a private database schema.
- Workflow: `.github/workflows/collect.yml`; approximately hourly at minute 17, on collector code changes, or manual dispatch.

The browser uses the publishable key for read-only access. The publishable key alone cannot
write. The intentionally exposed `ingest_snapshot` function additionally requires a random
collector credential, validates the input, serializes concurrent writers, and commits one
observation atomically. The credential is never shipped to the browser or committed to Git.

## API

Send the publishable key in the `apikey` request header. Read endpoints support GET:

- `get_snapshot`: latest successfully captured source snapshot, `{metadata, events}`.
- `get_snapshot?p_month=2026-10`: last successful capture within the specified UTC month.
  Returns JSON `null` for a month without observations; it never substitutes current data.
- `get_archive_months`: observed months, last check, number of checks and distinct versions.
- `ingest_snapshot`: POST only, requires `p_token`, `p_payload`, and `p_run_key`.
  Retries with the same run key are idempotent.

`metadata.retrievedAt` is the original capture time for that content version;
`metadata.lastCheckedAt` is the selected successful observation time.
`metadata.trackingStartedAt` is the earliest evidenced capture retained in this database.
The website's archive selector uses capture months. Its record-date filters use dates
inside the selected snapshot; these are different concepts.

## History and accuracy

`warn_snapshots` keeps each distinct parsed content version as immutable JSONB.
`warn_observations` records every successful check, its source hashes, and its snapshot ID.
Unchanged checks reuse the content version, saving database space. Row reordering alone
does not create a new version. Multiplicity is preserved; source rows are not deduplicated
as unique layoffs. Row-number IDs in CA/NY are local to a snapshot, not durable event IDs.
Removed records remain retrievable in older snapshots. Corrections create a new version;
the old evidence is retained. There is no automatic history deletion.

The initial snapshot was imported with its recorded retrieval timestamp, not a fabricated
historical date. Collection currently covers CA's current fiscal report, NY's default
dashboard export, and WA's first database page. **There are no verified captured monthly
snapshots before tracking began.** Notices dated earlier may exist in current snapshots,
but that does not prove the source's past state or a complete monthly total. Historical
agency-file backfills need source-specific parsers and provenance review; do not infer
missing months, first publication dates, or news coverage. This database preserves evidence;
it cannot repair omissions in the agency feeds.

Large record losses (>30% for a state), empty sources, schema changes, duplicate IDs,
invalid dates, or invented evidence fail collection. A legitimate fiscal rollover needs
review before adjusting the guard; old versions are never deleted to accommodate it.

## Operation and recovery

Run `python -m unittest discover -s tests -p 'test_*.py'` for collector checks.
With the three environment variables configured, run `python scripts/collect.py`.
The first run imports the preserved baseline only if the database is empty. `--seed`
explicitly imports a preserved snapshot with its existing retrieval timestamp.

Database publication happens before the Git evidence backup. If the Git push fails,
the workflow reports failure but the published data remains available. The next run
compares against the database, preventing a stale checkout from overwriting validation
history. Failed downloads/validation publish nothing. GitHub run logs record failures;
the public API's last successful check reveals stale collection. Schedules may be delayed
or skipped by GitHub.

Apply SQL under `supabase/migrations/` using an administrative connection or the Supabase
SQL migration tool. Collector workflow credentials cannot apply migrations or delete data.
The database security advisor flags the anonymous SECURITY DEFINER ingestion function:
this is intentional and protected by the separate collector token. Public read functions
are SECURITY INVOKER and tables have RLS with SELECT-only policies.

Raw agency evidence changes are backed up through Git history. On free-tier storage
pressure, stop collection and export the database before any archival cleanup; do not
silently discard historical snapshots or automatically upgrade to a paid plan.

The website has its own code-only deployment workflow. Data collection never triggers it.
