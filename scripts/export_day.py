#!/usr/bin/env python3
"""Emit only public-safe, day-level Cowrie measurements as JSON."""

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

EVENTS = (
    'cowrie.session.connect',
    'cowrie.login.success',
    'cowrie.login.failed',
    'cowrie.command.input',
    'cowrie.proxy.backend_connect_error',
)


def export_day(conn, day):
    start = datetime.combine(day, time.min, timezone.utc)
    end = start + timedelta(days=1)
    bounds = (start.timestamp(), end.timestamp())
    events = conn.execute(
        """SELECT eventid, count(*) AS events, count(DISTINCT nullif(session, '')) AS sessions,
                  count(DISTINCT nullif(ip, '')) AS sources
           FROM events
           WHERE ts >= ? AND ts < ?
             AND session NOT IN (SELECT id FROM sessions WHERE test = 1)
             AND message NOT LIKE '%DASHBOARD_VALIDATION%'
             AND eventid IN (?, ?, ?, ?, ?)
           GROUP BY eventid""", (*bounds, *EVENTS),
    )
    counts = {event_id: (n, sessions, sources) for event_id, n, sessions, sources in events}

    def count(event_id, column=0):
        return counts.get(event_id, (0, 0, 0))[column]

    captures, unique_samples = conn.execute(
        """SELECT count(*), count(DISTINCT lower(sha256)) FROM artifacts
           WHERE ts >= ? AND ts < ? AND confidence = 'host-verified'
             AND length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-fA-F]*'
             AND session NOT IN (SELECT id FROM sessions WHERE test = 1)
             AND path NOT LIKE '%DASHBOARD_VALIDATION%'""", bounds,
    ).fetchone()
    observed_hours = conn.execute(
        """SELECT count(DISTINCT cast(ts / 3600 AS INTEGER)) FROM events
           WHERE ts >= ? AND ts < ? AND eventid GLOB 'cowrie.*'
             AND session NOT IN (SELECT id FROM sessions WHERE test = 1)
             AND message NOT LIKE '%DASHBOARD_VALIDATION%'""", bounds,
    ).fetchone()[0]

    return {
        'schema_version': 1,
        'day_utc': day.isoformat(),
        'window': {'start_utc': start.isoformat(), 'end_utc_exclusive': end.isoformat()},
        'coverage': {
            'hours_with_cowrie_events': observed_hours,
            'status': 'unverified' if observed_hours else 'no_observations',
        },
        'metrics': {
            'connections': count('cowrie.session.connect'),
            'unique_source_ips': count('cowrie.session.connect', 2),
            'sessions_with_accepted_login': count('cowrie.login.success', 1),
            'failed_login_attempts': count('cowrie.login.failed'),
            'sessions_with_commands': count('cowrie.command.input', 1),
            'shell_commands': count('cowrie.command.input'),
            'host_verified_captures': captures,
            'unique_host_verified_samples': unique_samples,
            'backend_connection_errors': count('cowrie.proxy.backend_connect_error'),
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--day', type=date.fromisoformat,
                        default=datetime.now(timezone.utc).date() - timedelta(days=1))
    args = parser.parse_args()
    if args.day >= datetime.now(timezone.utc).date():
        parser.error('--day must be a completed UTC day')
    with closing(sqlite3.connect(args.db.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        conn.execute('BEGIN')
        report = export_day(conn, args.day)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
