# Official record snapshot

The initial snapshot was retrieved October 17, 2026. Current retrieval times and counts are in events.json metadata. Automated collection now checks hourly through GitHub Actions; the coverage counts below describe the initial snapshot. Run `python scripts/data_build.py` from the app root to reproduce `events.json` and `sources.json` from saved snapshots. The script uses the Python standard library. `--refresh` retrieves current sources and changes the sample; review changed schemas before interpreting updated results.

## Coverage

- California: 368 detailed rows in EDD's July 1–October 14, 2026 current fiscal WARN report. 17,617 reported affected workers, matching the workbook summary. Call-center relocation sheet excluded.
- New York: 208 impacted-site rows in the DOL Tableau dashboard's default CSV export. This is the default current export, not the full historical database. Different sites and repeated companies remain separate.
- Washington: 15 rows on the first page of the official ESD public database. No claim of comprehensive Washington coverage.

The data unit is an official source record/impacted site, not a deduplicated notice. Samples cover different periods and cannot support state prevalence comparisons. Counts describe reported planned actions and affected workers; they do not establish realized job loss.

## Dates and news

`noticeDate`, `receivedDate`, `processedDate`, `effectiveDate`, and `listedPostedDate` retain their source-specific meanings. California's processed date and Washington's receipt date are **not** first public posting timestamps. New York's displayed Date Posted is preserved in `listedPostedDate`; it has not been verified as the initial posting rather than an update. Therefore `postedDate` is null for every row.

Every `newsStatus` is `unreviewed`. `firstNewsDate`, `newsUrl`, and `latencyDays` are null. No real record is classified as quiet or covered. Any illustrative latency charts in the app must use a separately labeled synthetic example dataset and must not make claims about these employers.

## Map coordinates

2026 U.S. Census Gazetteer place internal points are matched to city names; unresolved place names may use the source county's internal point. These are approximate geographic points, not geocoded employer worksite addresses. `coordinatePrecision`, `geographyName`, and `geographyId` preserve this distinction. Multi-city Washington records are retained in totals but left without map coordinates; worker counts are not arbitrarily assigned to one city or duplicated across cities.

## Provenance

`events.json` contains `{metadata, events}`. Metadata includes retrieval date, sampling caveats, source URLs, and SHA-256 hashes of the raw snapshots. California records include source worksheet row, New York records include CSV row, and Washington records link directly to the original notice PDF.

Snapshot filenames: `ca.xlsx`, `ny-csv.txt` (CSV), `wa-db.txt` (HTML), `places.zip`, and `counties.zip`. Additional CA/WA source-page HTML snapshots document source discovery. `sources.json` includes official source portals, Census geography, the DOL WARN overview, and GDELT documentation for future article discovery. GDELT has not supplied any reviewed matches in this dataset.
