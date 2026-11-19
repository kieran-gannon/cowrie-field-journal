import json
import sqlite3
import unittest
from datetime import date, datetime, timezone

from scripts.export_day import export_day


class DayExportTest(unittest.TestCase):
    def test_counts_boundaries_and_excludes_private_fields(self):
        with sqlite3.connect(':memory:') as db:
            db.executescript("""
                CREATE TABLE sessions (id TEXT, test INTEGER);
                CREATE TABLE events (ts REAL, session TEXT, eventid TEXT, ip TEXT, message TEXT);
                CREATE TABLE artifacts (ts REAL, session TEXT, confidence TEXT, sha256 TEXT, path TEXT);
                INSERT INTO sessions VALUES ('secret-session', 0), ('validation-session', 1);
            """)
            start = datetime(2026, 1, 2, tzinfo=timezone.utc).timestamp()
            events = [
                (start - 1, 'secret-session', 'cowrie.session.connect', '192.0.2.42', 'old'),
                (start, 'secret-session', 'cowrie.session.connect', '192.0.2.42', 'secret-message'),
                (start + 1, 'secret-session', 'cowrie.command.input', '192.0.2.42', 'secret-command'),
                (start + 2, 'secret-session', 'cowrie.command.input', '192.0.2.42', 'secret-command'),
                (start + 3, 'validation-session', 'cowrie.session.connect', '192.0.2.43', 'test'),
                (start + 86400, 'secret-session', 'cowrie.session.connect', '192.0.2.44', 'tomorrow'),
            ]
            db.executemany('INSERT INTO events VALUES (?,?,?,?,?)', events)
            db.executemany('INSERT INTO artifacts VALUES (?,?,?,?,?)', [
                (start + 4, 'secret-session', 'host-verified', 'a' * 64, 'private-path'),
                (start + 5, 'secret-session', 'host-verified', 'a' * 64, 'private-path'),
                (start + 6, 'secret-session', 'guest-reported', 'b' * 64, 'private-path'),
            ])
            report = export_day(db, date(2026, 1, 2))
        self.assertEqual(report['metrics']['connections'], 1)
        self.assertEqual(report['metrics']['unique_source_ips'], 1)
        self.assertEqual(report['metrics']['shell_commands'], 2)
        self.assertEqual(report['metrics']['sessions_with_commands'], 1)
        self.assertEqual(report['metrics']['host_verified_captures'], 2)
        self.assertEqual(report['metrics']['unique_host_verified_samples'], 1)
        self.assertEqual(report['coverage']['hours_with_cowrie_events'], 1)
        serialized = json.dumps(report)
        for private_value in ('192.0.2.', 'secret-', 'private-path', 'a' * 64):
            self.assertNotIn(private_value, serialized)
