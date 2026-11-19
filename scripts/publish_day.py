#!/usr/bin/env python3
"""Generate and push one completed UTC day from the Cowrie VPS."""

import argparse
import json
import os
import re
import sqlite3
import subprocess
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

if __package__:
    from .export_context import BASELINE_DAYS, CONTEXT_DAYS, export_context
    from .generate_brief import METRIC_NAMES, generate
else:
    from export_context import BASELINE_DAYS, CONTEXT_DAYS, export_context
    from generate_brief import METRIC_NAMES, generate

REMOTE = 'git@github.com:kieran-gannon/cowrie-field-journal.git'
IDENTITY = 'Cowrie Field Journal Automation'
EMAIL = 'cowrie-field-journal@users.noreply.github.com'


def require(condition, field):
    if not condition:
        raise ValueError('Invalid public export field: ' + field)


def exact(record, keys, field):
    require(isinstance(record, dict) and set(record) == set(keys.split()), field)


def count(value):
    return type(value) is int and value >= 0


def validate_day(record, day):
    exact(record, 'schema_version day_utc window coverage metrics evidence_id', 'day')
    start = datetime.combine(day, time.min, timezone.utc)
    end = start + timedelta(days=1)
    require(record['schema_version'] == 1 and record['day_utc'] == day.isoformat()
            and record['evidence_id'] == f'day-{day}', 'day identifiers')
    require(record['window'] == {'start_utc': start.isoformat(), 'end_utc_exclusive': end.isoformat()},
            'reporting window')
    coverage = record['coverage']
    exact(coverage, 'hours_with_cowrie_events status', 'coverage')
    hours = coverage['hours_with_cowrie_events']
    require(count(hours) and hours <= 24 and coverage['status'] ==
            ('unverified' if hours else 'no_observations'), 'coverage values')
    metrics = record['metrics']
    if metrics is None:
        require(hours == 0, 'missing metrics')
    else:
        require(isinstance(metrics, dict) and set(metrics) == METRIC_NAMES.keys()
                and all(count(value) for value in metrics.values()), 'metric names and counts')
        require(hours > 0 or metrics['host_verified_captures'] > 0, 'empty observation metrics')


def validate_context(context, day):
    exact(context, 'schema_version today history baseline recurring_samples', 'context')
    require(context['schema_version'] == 1, 'context schema version')
    validate_day(context['today'], day)
    history = context['history']
    require(isinstance(history, list) and len(history) == CONTEXT_DAYS, 'history length')
    for offset, record in enumerate(history, start=-CONTEXT_DAYS):
        validate_day(record, day + timedelta(days=offset))
    baseline = context['baseline']
    exact(baseline, 'evidence_id n_days days_used medians', 'baseline')
    observed = [row['day_utc'] for row in history[-BASELINE_DAYS:]
                if row['coverage']['hours_with_cowrie_events']]
    require(baseline['evidence_id'] == 'baseline-7d' and baseline['days_used'] == observed
            and baseline['n_days'] == len(observed), 'baseline evidence')
    medians = baseline['medians']
    if not observed:
        require(medians is None, 'missing baseline')
    else:
        require(isinstance(medians, dict) and set(medians) == METRIC_NAMES.keys()
                and all(type(value) in (int, float) and 0 <= value < float('inf')
                        for value in medians.values()), 'baseline metrics')

    samples = context['recurring_samples']
    require(isinstance(samples, list) and len(samples) <= 12, 'sample list')
    known_days = {row['day_utc'] for row in [*history, context['today']]}
    aliases = set()
    for sample in samples:
        exact(sample, 'evidence_id days_observed observed_today observations', 'sample')
        alias = sample['evidence_id']
        require(isinstance(alias, str) and re.fullmatch(r'sample-[0-9a-f]{20}', alias)
                and alias not in aliases, 'sample alias')
        aliases.add(alias)
        observations = sample['observations']
        require(isinstance(observations, list) and 2 <= len(observations) <= CONTEXT_DAYS + 1
                and sample['days_observed'] == len(observations), 'sample observation count')
        dates = []
        for observation in observations:
            exact(observation, 'day_utc verified_captures capture_sessions_with_download_attempt',
                  'sample observation')
            captures = observation['verified_captures']
            linked = observation['capture_sessions_with_download_attempt']
            require(observation['day_utc'] in known_days and count(captures) and captures > 0
                    and count(linked) and linked <= captures, 'sample observation values')
            dates.append(observation['day_utc'])
        require(dates == sorted(set(dates)) and sample['observed_today'] is (day.isoformat() in dates),
                'sample dates')


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def git(repo, *args):
    subprocess.run(['git', '-C', str(repo), *args], check=True, timeout=90)


def publish(day, db, alias_key, dry_run):
    with TemporaryDirectory(prefix='cowrie-journal-') as work:
        repo = Path(work) / 'repo'
        git(work, 'clone', '--depth=1', '--branch', 'main', REMOTE, str(repo))
        data = repo / 'site' / 'data'
        index = json.loads((data / 'index.json').read_text())
        exact(index, 'days', 'archive index')
        days = index['days']
        require(isinstance(days, list) and all(isinstance(value, str) and
                re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) for value in days), 'archive dates')
        day_folder = data / day.isoformat()
        if day.isoformat() in days and not dry_run:
            print(f'{day} already published')
            return
        with closing(sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
            conn.execute('BEGIN')
            context = export_context(conn, day, alias_key)
        validate_context(context, day)
        if context['today']['metrics'] is None:
            print(f'{day} has no retained observations; leaving a gap in the archive')
            return
        brief = generate(context, os.environ.get('OPENROUTER_API_KEY'))
        report = {'schema_version': 1, 'day_utc': day.isoformat(),
                  'stats': context['today'], 'brief': brief}
        day_folder.mkdir(exist_ok=True)
        write_json(day_folder / 'context.json', context)
        write_json(day_folder / 'report.json', report)
        write_json(data / 'index.json', {'days': sorted(set([*days, day.isoformat()]))})
        git(repo, 'add', f'site/data/{day}/context.json', f'site/data/{day}/report.json',
            'site/data/index.json')
        git(repo, '-c', f'user.name={IDENTITY}', '-c', f'user.email={EMAIL}',
            'commit', *(['--allow-empty'] if dry_run else []), '-m', f'Publish Cowrie daily brief for {day} UTC')
        git(repo, 'push', *(['--dry-run'] if dry_run else []), 'origin', 'HEAD:main')
        print(f'{day} UTC · brief {brief["state"]} · {"dry run" if dry_run else "pushed"}')


def main():
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--alias-key-file', required=True, type=Path)
    parser.add_argument('--day', type=date.fromisoformat, default=yesterday)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if args.day > yesterday:
        parser.error('--day must be a completed UTC day')
    publish(args.day, args.db, args.alias_key_file.read_bytes(), args.dry_run)


if __name__ == '__main__':
    main()
