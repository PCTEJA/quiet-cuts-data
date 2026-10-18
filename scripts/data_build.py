"""Reproduce Quiet Cuts' official source snapshot. Python standard library only.

Run python scripts/data_build.py to rebuild from saved sources; add --refresh to
download the current sources. Refreshes change the observational sample.
No first-publication timestamp or news coverage is inferred from agency dates.
"""
from pathlib import Path
from datetime import datetime, timedelta, timezone
import csv, io, json, re, hashlib, zipfile, urllib.request, sys, html, os, time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get('QUIET_CUTS_DATA_DIR', ROOT / 'data'))
SNAP = DATA / 'snapshots'
SOURCES = {
    'ca.xlsx': 'https://edd.ca.gov/siteassets/files/jobs_and_training/warn/warn_report1.xlsx',
    'wa-db.txt': 'https://fortress.wa.gov/esd/file/WARN',
    'ny-csv.txt': 'https://public.tableau.com/views/WorkerAdjustmentRetrainingNotificationWARN/WARN.csv?:showVizHome=no',
    'places.zip': 'https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2026_Gazetteer/2026_Gaz_place_national.zip',
    'counties.zip': 'https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2026_Gazetteer/2026_Gaz_counties_national.zip',
}
SNAP.mkdir(parents=True, exist_ok=True)
if '--refresh' in sys.argv:
    for filename, url in SOURCES.items():
        # Census geometry is a versioned reference, not an hourly data feed.
        if filename.endswith('.zip') and (SNAP / filename).exists():
            continue
        for attempt in range(3):
            try:
                request = urllib.request.Request(url, headers={'User-Agent': 'QuietCuts/1.0 (public WARN research)'})
                data = urllib.request.urlopen(request, timeout=60).read()
                if not data: raise ValueError(f'Empty source: {filename}')
                break
            except Exception:
                if attempt == 2: raise
                time.sleep(2 ** attempt)
        (SNAP / filename).write_bytes(data)

def clean(s):
    return re.sub(r'\s+', ' ', str(s or '')).strip()

def gazetteer(filename):
    z = zipfile.ZipFile(SNAP / filename)
    return list(csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode('utf-8-sig')), delimiter='|'))

places = {}
for p in gazetteer('places.zip'):
    if p['USPS'] in ['CA', 'NY', 'WA']:
        name = re.sub(r' (city|town|village|CDP|borough)$', '', p['NAME'])
        places[(p['USPS'], name.lower())] = p
counties = {(p['USPS'], p['NAME'].lower()): p for p in gazetteer('counties.zip')}

def geo(state, address, city, county):
    if state == 'WA' and (',' in city or ' and ' in city or ';' in city):
        return dict(city=city, lat=None, lon=None, coordinatePrecision='Multiple locations; workers not allocated to cities; not plotted')
    # Exact place name suffix matching prevents shorter names winning over longer ones.
    p = places.get((state, city.lower()))
    if not p:
        target = re.sub(r',?\s*'+state+r'\b.*$', '', address).strip().lower()
        for (st, name), candidate in sorted(places.items(), key=lambda kv: -len(kv[0][1])):
            if st == state and (target == name or target.endswith(' '+name)):
                p, city = candidate, re.sub(r' (city|town|village|CDP|borough)$', '', candidate['NAME'])
                break
    level = 'place' if p else None
    if not p and county:
        name = county if county.endswith('County') else county + ' County'
        p = counties.get((state, name.lower()))
        if p: level = 'county'
    if not p:
        return dict(city=city or county or 'Unresolved location', lat=None, lon=None,
                    coordinatePrecision='Unresolved; not plotted')
    return dict(city=city or county, lat=float(p['INTPTLAT']), lon=float(p['INTPTLONG']),
                coordinatePrecision=f'Census {level} internal point; approximate region, not worksite',
                coordinateSource='https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html',
                geographyName=p['NAME'], geographyId=p['GEOID'])

def date(s):
    s = clean(s)
    if not s: return None
    for fmt in ['%Y-%m-%d', '%m/%d/%Y']:
        try: return datetime.strptime(s, fmt).date().isoformat()
        except ValueError: pass
    try: return (datetime(1899, 12, 30) + timedelta(days=float(s))).date().isoformat()
    except ValueError: return None

def base(state, company, workers, address, city='', county=''):
    return dict(state=state, company=clean(company), workers=int(str(workers).replace(',', '')),
                address=clean(address), county=county, industry='Unknown', receivedDate=None,
                noticeDate=None, processedDate=None, postedDate=None, listedPostedDate=None,
                effectiveDate=None, newsStatus='unreviewed', newsUrl=None, firstNewsDate=None,
                latencyDays=None, evidenceType='official', **geo(state, address, city, county))

events=[]
ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
z=zipfile.ZipFile(SNAP/'ca.xlsx')
ss=[''.join(t.itertext()) for t in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si',ns)]
sheet_rows = ET.fromstring(z.read('xl/worksheets/sheet3.xml')).findall('.//m:row',ns)
headers = {}
for cell in sheet_rows[1].findall('m:c', ns):
    value = cell.find('m:v', ns)
    if value is not None:
        headers[re.sub(r'\d', '', cell.get('r'))] = clean(ss[int(value.text)] if cell.get('t') == 's' else value.text)
expected_headers = {'A':'County/Parish','B':'Notice Date','C':'Processed Date','D':'Effective Date','E':'Company','F':'Layoff/ Closure','G':'No. Of Employees','H':'Address','I':'Related Industry'}
if headers != expected_headers:
    raise ValueError('California worksheet schema changed; review before publication')
for row in ET.fromstring(z.read('xl/worksheets/sheet3.xml')).findall('.//m:row',ns)[2:]:
    c={}
    for cell in row.findall('m:c',ns):
        v=cell.find('m:v',ns); val=v.text if v is not None else ''
        if cell.get('t')=='s': val=ss[int(val)]
        c[re.sub(r'\d','',cell.get('r'))]=val
    if not c.get('E') or not c.get('G','').isdigit(): continue
    address=c.get('H',''); parts=re.split(r'\s{2,}',address)
    city=re.sub(r'\s+CA\b.*$', '',parts[-1]).strip() if len(parts)>1 else ''
    event=base('CA',c['E'],c['G'],address,city,c.get('A',''))
    event.update(id=f"CA-{row.get('r')}",noticeDate=date(c.get('B')),processedDate=date(c.get('C')),
                 effectiveDate=date(c.get('D')),industry=re.sub(r'^[\d-]+\s*','',c.get('I','')) or 'Unknown',
                 eventType=c.get('F'),sourceUrl=SOURCES['ca.xlsx'],sourceTitle='California EDD detailed WARN report',
                 sourceRow=int(row.get('r')),sourceDateSemantics='Notice Date is employer notice date; Processed Date is agency processing, not first public posting. Effective Date is scheduled action date.')
    events.append(event)

for i,raw in enumerate(csv.DictReader((SNAP/'ny-csv.txt').open(encoding='utf-8-sig')),2):
    c={k.strip():v for k,v in raw.items()}
    event=base('NY',c['Business Legal Name'],c['Number of Affected Workers'],c['Impacted Site Address'],county=c['Impacted Site County'])
    event.update(id=f'NY-{i}',noticeDate=date(c['Date of WARN Notice']),listedPostedDate=date(c['Date Posted']),
                 effectiveDate=date(c['Date Layoff/Closure Starts']),eventType=c['Layoff or Closure?']+' '+c['Permanent or Temporary Layoff?'],
                 reason=c['Reason for Layoff/Closure'],sourceUrl='https://dol.ny.gov/warn-dashboard',
                 sourceDownloadUrl=SOURCES['ny-csv.txt'],sourceTitle='New York DOL WARN dashboard export',sourceRow=i,
                 sourceDateSemantics='Date Posted is preserved as listedPostedDate. Whether it is the first/original posting has not been verified, so postedDate and latency remain null. Each row is an impacted site, not necessarily a unique company notice.')
    events.append(event)

wa=(SNAP/'wa-db.txt').read_text(encoding='utf8')
for row in re.findall(r'<tr[^>]*>(.*?)</tr>',wa,re.S):
    cells=re.findall(r'<td[^>]*>(.*?)</td>',row,re.S)
    if len(cells)!=8 or 'DownloadFile.aspx' not in cells[7]: continue
    c=[clean(html.unescape(re.sub('<[^>]+>','',cell))) for cell in cells]
    if not c[3].isdigit(): continue
    link=html.unescape(re.search(r"href=['\"]([^'\"]+)",cells[7]).group(1))
    county=c[1] if c[1].endswith('County') else ''
    event=base('WA',c[0],c[3],c[1],c[1],county)
    event.update(id='WA-'+re.search(r'file=([^&]+)',link).group(1).replace('.pdf',''),
                 effectiveDate=date(c[2]),receivedDate=date(c[6]),eventType=c[4]+' '+c[5],
                 sourceUrl='https://fortress.wa.gov'+link,sourceTitle='Washington ESD WARN public notice',
                 sourceDateSemantics='Received Date is agency receipt, not first public posting. Multi-city notices are not split or allocated to cities; unresolved multi-location notices are not plotted.')
    events.append(event)

counts={state:sum(e['state']==state for e in events) for state in ['CA','NY','WA']}
manifest=[dict(filename=name,url=url,sha256=hashlib.sha256((SNAP/name).read_bytes()).hexdigest()) for name,url in SOURCES.items()]
retrieved_date = datetime.now(timezone.utc).date().isoformat() if '--refresh' in sys.argv else '2026-10-17'
metadata=dict(retrievedDate=retrieved_date,title='Official WARN source snapshot',counts=counts,totalRecords=len(events),
              unit='Source records / impacted sites; not deduplicated unique layoff events',
              sampling='CA: all detailed rows in current fiscal report; NY: default current dashboard CSV export; WA: first page of current database. These are different observation windows, not a representative comparative sample.',
              caveats=['All news matches are unreviewed. No quiet/covered classification or media latency can be inferred.',
                       'No original public posting timestamp has been verified. Agency notice, receipt and processed dates are distinct.',
                       'Records describe planned actions and reported affected workers, not confirmed unemployment or realized job losses.',
                       'Repeated companies and multiple worksite rows are retained. Do not describe row count as unique notices.',
                       'Coordinates are Census place/county internal points. Unresolved multi-city records are excluded from map points, retained in totals.',
                       'Source windows differ. State totals are sample totals and cannot support rankings of state layoff prevalence.',
                       'Illustrative news latency examples, if shown by the interface, must be kept separate from these official records.'],
              snapshots=manifest)
if '--refresh' in sys.argv:
    metadata['retrievedAt'] = datetime.now(timezone.utc).isoformat()
(DATA/'events.json').write_text(json.dumps(dict(metadata=metadata,events=events),indent=2,ensure_ascii=False),encoding='utf8')
sources=[
    dict(id='ca',title='California EDD · WARN reports',url='https://edd.ca.gov/warn',downloadUrl=SOURCES['ca.xlsx'],type='Official records',note='Current fiscal report; notice and processed dates are not first public posting dates.'),
    dict(id='ny',title='New York DOL · WARN dashboard',url='https://dol.ny.gov/warn-dashboard',downloadUrl=SOURCES['ny-csv.txt'],type='Official records',note='Default current export; impacted-site rows. Listed Date Posted not verified as original posting.'),
    dict(id='wa',title='Washington ESD · WARN database',url='https://esd.wa.gov/employer-requirements/layoffs-and-employee-notifications/worker-adjustment-and-retraining-notification-warn-layoff-and-closure-database',downloadUrl=SOURCES['wa-db.txt'],type='Official records',note='First page only. Received Date is agency receipt, not public posting.'),
    dict(id='census',title='U.S. Census Bureau · Gazetteer files',url='https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html',type='Official geography',note='2026 place/county internal points; approximate locations, not employer addresses.'),
    dict(id='dol',title='U.S. Department of Labor · WARN',url='https://www.dol.gov/agencies/eta/layoffs/warn',type='Methodology reference',note='Federal WARN overview; state rules and source coverage vary.'),
    dict(id='gdelt',title='GDELT · DOC 2.0 API documentation',url='https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/',type='Research tool',note='Candidate news discovery only; search results and GDELT timestamps require article-level validation. No matches have been reviewed in this snapshot.'),
]
(DATA/'sources.json').write_text(json.dumps(sources,indent=2),encoding='utf8')
print(json.dumps(dict(counts=counts,total=len(events),mapped=sum(e['lat'] is not None for e in events),workers=sum(e['workers'] for e in events))))
