"""Collect, validate, and atomically archive WARN evidence without deploying a site."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from refresh_data import validate, fingerprint

ROOT = Path(__file__).resolve().parents[1]


def rpc(name, body):
    url = os.environ['SUPABASE_URL'].rstrip('/') + '/rest/v1/rpc/' + name
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
        'apikey': os.environ['SUPABASE_PUBLISHABLE_KEY'],
        'Content-Type': 'application/json',
    })
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code < 500 or attempt == 2:
                # Do not include request bodies (which carry the collector credential).
                raise RuntimeError(f'{name}: API returned HTTP {error.code}') from None
        except urllib.error.URLError:
            if attempt == 2:
                raise RuntimeError(f'{name}: API unavailable') from None
        time.sleep(2 ** attempt)


def publish(payload, run_key):
    return rpc('ingest_snapshot', {'p_token': os.environ['COLLECTOR_TOKEN'],
        'p_payload': payload, 'p_run_key': run_key})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seed', action='store_true', help='Import the preserved snapshot with its original timestamp')
    args = parser.parse_args()
    if args.seed:
        original = json.loads((ROOT / 'data/events.json').read_text(encoding='utf8'))
        validate(original)
        if not original['metadata'].get('retrievedAt'):
            raise ValueError('Cannot seed a snapshot without an evidenced retrieval timestamp')
        print(json.dumps(publish(original, 'seed:' + original['metadata']['retrievedAt'])))
        return

    # The database is authoritative even if a previous Git backup push failed.
    previous = rpc('get_snapshot', {})
    if previous is None:
        previous = json.loads((ROOT / 'data/events.json').read_text(encoding='utf8'))
        validate(previous)
        if not previous['metadata'].get('retrievedAt'):
            raise ValueError('Cannot bootstrap without an evidenced retrieval timestamp')
        publish(previous, 'seed:' + previous['metadata']['retrievedAt'])
    with tempfile.TemporaryDirectory(prefix='quiet-cuts-') as folder:
        staged = Path(folder) / 'data'
        shutil.copytree(ROOT / 'data', staged)
        subprocess.run([sys.executable, str(ROOT / 'scripts/data_build.py'), '--refresh'],
            env=dict(os.environ, QUIET_CUTS_DATA_DIR=str(staged)), check=True)
        candidate = json.loads((staged / 'events.json').read_text(encoding='utf8'))
        validate(candidate, previous)
        changed = fingerprint(candidate) != fingerprint(previous)
        # A retry uses the same run key and cannot create duplicate observations.
        run_key = 'github:' + os.environ['GITHUB_RUN_ID'] if os.environ.get('GITHUB_RUN_ID') else 'local:' + candidate['metadata']['retrievedAt']
        result = publish(candidate, run_key)
        local = json.loads((ROOT / 'data/events.json').read_text(encoding='utf8'))
        if fingerprint(candidate) != fingerprint(local):
            shutil.copy2(staged / 'events.json', ROOT / 'data/events.json')
        shutil.copy2(staged / 'sources.json', ROOT / 'data/sources.json')
        for name in ('ca.xlsx', 'ny-csv.txt', 'wa-db.txt'):
            shutil.copy2(staged / 'snapshots' / name, ROOT / 'data/snapshots' / name)
        print(json.dumps(dict(result, changed=changed)))


if __name__ == '__main__':
    main()
