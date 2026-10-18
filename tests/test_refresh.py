import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('refresh', ROOT / 'scripts/refresh_data.py')
refresh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refresh)


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / 'data/events.json').read_text(encoding='utf8'))

    def test_current_data(self):
        refresh.validate(self.data)

    def test_partial_source_is_rejected(self):
        broken = copy.deepcopy(self.data)
        broken['events'] = [e for e in broken['events'] if e['state'] != 'WA']
        with self.assertRaises(ValueError): refresh.validate(broken, self.data)

    def test_large_drop_is_rejected_even_with_consistent_counts(self):
        broken = copy.deepcopy(self.data)
        broken['events'] = [e for e in broken['events'] if e['state'] != 'CA'] + [next(e for e in self.data['events'] if e['state'] == 'CA')]
        broken['metadata']['counts']['CA'] = 1
        broken['metadata']['totalRecords'] = len(broken['events'])
        with self.assertRaises(ValueError): refresh.validate(broken, self.data)

    def test_no_fabricated_evidence(self):
        self.data['events'][0]['postedDate'] = '2026-10-17'
        with self.assertRaises(ValueError): refresh.validate(self.data)

    def test_fingerprint_ignores_reordering_but_detects_corrections(self):
        same = copy.deepcopy(self.data)
        same['events'].reverse()
        same['events'][0]['id'] = 'reordered'
        self.assertEqual(refresh.fingerprint(same), refresh.fingerprint(self.data))
        same['events'][0]['workers'] += 1
        self.assertNotEqual(refresh.fingerprint(same), refresh.fingerprint(self.data))


if __name__ == '__main__': unittest.main()
