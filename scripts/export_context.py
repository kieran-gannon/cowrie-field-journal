#!/usr/bin/env python3
"""Build the exact public-safe daily input for the Cowrie field journal."""

import argparse
import hmac
import json
import sqlite3
from collections import defaultdict
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from statistics import median

if __package__:
    from .export_day import export_day
else:
    from export_day import export_day

CONTEXT_DAYS = 30
BASELINE_DAYS = 7
MAX_RECURRING_SAMPLES = 12


def recurring_samples(conn, start, end, day, alias_key):
    bounds = (start.timestamp(), end.timestamp())
    rows = conn.execute("""
        WITH evidence AS (
            SELECT date(ts, 'unixepoch') day, session, lower(sha256) digest,
                   confidence, operation
            FROM artifacts
            WHERE ts >= ? AND ts < ?
              AND session NOT IN (SELECT id FROM sessions WHERE test = 1)
              AND path NOT LIKE '%DASHBOARD_VALIDATION%'
        ), attempts AS (
            SELECT DISTINCT day, session FROM evidence
            WHERE operation = 'download attempt' AND confidence = 'inferred' AND session <> ''
        )
        SELECT e.day, e.digest, count(*) captures,
               count(DISTINCT CASE WHEN a.session IS NOT NULL THEN e.session END) linked_sessions
        FROM evidence e
        LEFT JOIN attempts a ON a.day = e.day AND a.session = e.session
        WHERE e.confidence = 'host-verified' AND length(e.digest) = 64
          AND e.digest NOT GLOB '*[^0-9a-f]*'
        GROUP BY e.day, e.digest ORDER BY e.day
    """, bounds)
    samples = defaultdict(list)
    for observed_day, digest, captures, linked_sessions in rows:
        samples[digest].append({
            'day_utc': observed_day,
            'verified_captures': captures,
            'capture_sessions_with_download_attempt': linked_sessions,
        })

    recurring = []
    for digest, observations in samples.items():
        if len(observations) < 2:
            continue
        suffix = hmac.digest(alias_key, bytes.fromhex(digest), 'sha256').hex()[:20]
        recurring.append({
            'evidence_id': f'sample-{suffix}',
            'days_observed': len(observations),
            'observed_today': observations[-1]['day_utc'] == day.isoformat(),
            'observations': observations,
        })
    recurring.sort(key=lambda sample: (
        not sample['observed_today'], -sample['days_observed'], sample['evidence_id']))
    return recurring[:MAX_RECURRING_SAMPLES]


def export_context(conn, day, alias_key):
    if len(alias_key) < 32:
        raise ValueError('The private alias key must contain at least 32 bytes')
    earliest = day - timedelta(days=CONTEXT_DAYS)
    history = []
    for offset in range(CONTEXT_DAYS + 1):
        record = export_day(conn, earliest + timedelta(days=offset))
        record['evidence_id'] = f"day-{record['day_utc']}"
        if record['coverage']['status'] == 'no_observations' and not record['metrics']['host_verified_captures']:
            record['metrics'] = None
        history.append(record)
    today = history.pop()
    eligible = [row for row in history[-BASELINE_DAYS:]
                if row['coverage']['hours_with_cowrie_events']]
    baseline = {key: median(row['metrics'][key] for row in eligible)
                for key in eligible[0]['metrics']} if eligible else None
    return {
        'schema_version': 1,
        'today': today,
        'history': history,
        'baseline': {'evidence_id': 'baseline-7d', 'n_days': len(eligible),
                     'days_used': [row['day_utc'] for row in eligible], 'medians': baseline},
        'recurring_samples': recurring_samples(
            conn, datetime.combine(earliest, time.min, timezone.utc),
            datetime.combine(day + timedelta(days=1), time.min, timezone.utc), day, alias_key),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--alias-key-file', required=True, type=Path)
    parser.add_argument('--day', type=date.fromisoformat,
                        default=datetime.now(timezone.utc).date() - timedelta(days=1))
    args = parser.parse_args()
    if args.day >= datetime.now(timezone.utc).date():
        parser.error('--day must be a completed UTC day')
    alias_key = args.alias_key_file.read_bytes()
    with closing(sqlite3.connect(args.db.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        conn.execute('BEGIN')
        context = export_context(conn, args.day, alias_key)
    print(json.dumps(context, indent=2))


if __name__ == '__main__':
    main()
