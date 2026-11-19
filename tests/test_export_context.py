import json
import sqlite3
import unittest
from datetime import date, datetime, timezone

from scripts.export_context import export_context


class ContextExportTest(unittest.TestCase):
    def test_baseline_missing_days_and_same_session_linkage(self):
        day = date(2026, 1, 20)
        start = datetime(2026, 1, 20, tzinfo=timezone.utc).timestamp()
        secret = 'a' * 64
        with sqlite3.connect(':memory:') as db:
            db.executescript("""
                CREATE TABLE sessions (id TEXT, test INTEGER);
                CREATE TABLE events (ts REAL, session TEXT, eventid TEXT, ip TEXT, message TEXT);
                CREATE TABLE artifacts (ts REAL, session TEXT, confidence TEXT,
                                        sha256 TEXT, path TEXT, operation TEXT);
                INSERT INTO sessions VALUES ('private-a', 0), ('private-b', 0), ('private-test', 1);
            """)
            db.executemany('INSERT INTO events VALUES (?,?,?,?,?)', [
                (start - 86400, 'private-a', 'cowrie.session.connect', '192.0.2.1', 'private command'),
                (start, 'private-a', 'cowrie.session.connect', '192.0.2.1', 'private command'),
            ])
            db.executemany('INSERT INTO artifacts VALUES (?,?,?,?,?,?)', [
                (start - 86400, 'private-a', 'host-verified', secret, '/private', 'upload'),
                (start - 86400, 'private-b', 'inferred', '', '/private', 'download attempt'),
                (start, 'private-a', 'host-verified', secret, '/private', 'upload'),
                (start + 1, 'private-a', 'inferred', '', '/private', 'download attempt'),
                (start + 2, 'private-a', 'inferred', '', '/private', 'download attempt'),
                (start + 3, 'private-a', 'host-verified', secret, '/private', 'upload'),
                (start + 4, 'private-test', 'host-verified', secret, '/private', 'upload'),
            ])
            report = export_context(db, day, b'x' * 32)
            self.assertEqual(report, export_context(db, day, b'x' * 32))
            rotated = export_context(db, day, b'y' * 32)
        self.assertEqual(len(report['history']), 30)
        self.assertIsNone(report['history'][0]['metrics'])
        self.assertEqual(report['baseline']['n_days'], 1)
        self.assertEqual(report['baseline']['medians']['connections'], 1)
        sample, = report['recurring_samples']
        self.assertTrue(sample['observed_today'])
        self.assertEqual(sample['days_observed'], 2)
        self.assertEqual(sample['observations'][0]['capture_sessions_with_download_attempt'], 0)
        self.assertEqual(sample['observations'][1]['capture_sessions_with_download_attempt'], 1)
        self.assertEqual(sample['observations'][1]['verified_captures'], 2)
        self.assertNotEqual(sample['evidence_id'], rotated['recurring_samples'][0]['evidence_id'])
        for private in (secret, '192.0.2.1', 'private-a', '/private', 'private command'):
            self.assertNotIn(private, json.dumps(report))
