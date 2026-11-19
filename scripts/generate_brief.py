#!/usr/bin/env python3
"""Ask DeepSeek to select findings and render them from verified public values."""

import argparse
import json
import os
import urllib.request
from pathlib import Path

MODEL = 'deepseek/deepseek-v4.1-flash'
PROMPT_VERSION = 'field-journal-1'
PROMPT = Path(__file__).with_name('brief_prompt.txt').read_text()
SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'properties': {
        'findings': {
            'type': 'array', 'maxItems': 3,
            'items': {
                'type': 'object', 'additionalProperties': False,
                'properties': {
                    'kind': {'type': 'string', 'enum': ['daily', 'baseline', 'recurrence']},
                    'evidence_id': {'type': 'string'},
                },
                'required': ['kind', 'evidence_id'],
            },
        },
    },
    'required': ['findings'],
}
METRIC_NAMES = {
    'connections': 'connections',
    'unique_source_ips': 'unique source IPs',
    'sessions_with_accepted_login': 'sessions with an accepted decoy login',
    'failed_login_attempts': 'failed login attempts',
    'sessions_with_commands': 'sessions with shell input',
    'shell_commands': 'shell commands',
    'host_verified_captures': 'host-verified file captures',
    'unique_host_verified_samples': 'unique host-verified samples',
    'backend_connection_errors': 'guest backend connection errors',
}


def eligible_findings(context):
    today = context['today']
    metrics = today['metrics'] or {}
    baseline = context['baseline']
    candidates = {}
    for key, value in metrics.items():
        label = METRIC_NAMES[key]
        ref = f"{today['evidence_id']}:{key}"
        candidates['daily', ref] = ([ref], f'Cowrie recorded {value:,} {label} in the UTC reporting window.')
        prior = (baseline['medians'] or {}).get(key)
        if baseline['n_days'] >= 3 and prior is not None and value != prior:
            comparison = 'up from' if value > prior else 'down from'
            candidates['baseline', ref] = (
                [ref, f"{baseline['evidence_id']}:{key}"],
                f'Cowrie recorded {value:,} {label}, {comparison} a median of {prior:,} '
                f'across {baseline["n_days"]} prior days with observed events in the seven-day window.',
            )

    for sample in context['recurring_samples']:
        if not sample['observed_today']:
            continue
        current = sample['observations'][-1]
        ref = sample['evidence_id']
        sentence = (
            f'The same bytes ({ref}) were verified on {sample["days_observed"]} UTC days '
            f'in the reporting window and its 30 prior days. '
            f'The current day accounted for {current["verified_captures"]} captures.'
        )
        linked = current['capture_sessions_with_download_attempt']
        if linked:
            sentence += (
                f' Cowrie also logged download attempts in {linked} of the sessions with a capture. '
                'The delivery path and process execution are unverified.'
            )
        candidates['recurrence', ref] = ([ref], sentence)
    return candidates


def render_findings(context, response):
    if not isinstance(response, dict) or set(response) != {'findings'}:
        raise ValueError('Expected a findings object')
    findings = response['findings']
    if not isinstance(findings, list) or len(findings) > 3:
        raise ValueError('Expected up to three findings')
    candidates = eligible_findings(context)
    rendered = []
    seen = set()
    for finding in findings:
        if not isinstance(finding, dict) or set(finding) != {'kind', 'evidence_id'}:
            raise ValueError('Invalid finding fields')
        kind, ref = finding['kind'], finding['evidence_id']
        if not isinstance(kind, str) or not isinstance(ref, str):
            raise ValueError('Invalid finding types')
        if (kind, ref) not in candidates or ref in seen:
            raise ValueError('Unknown, ineligible, or duplicate finding')
        seen.add(ref)
        sources, text = candidates[kind, ref]
        rendered.append({'kind': kind, 'evidence_ids': sources, 'text': text})
    return rendered


def ask(context, api_key):
    payload = {
        'model': MODEL,
        'messages': [
            {'role': 'system', 'content': PROMPT},
            {'role': 'user', 'content': json.dumps(context, separators=(',', ':'))},
        ],
        'max_tokens': 4096,
        'reasoning': {'effort': 'low'},
        'response_format': {'type': 'json_schema', 'json_schema': {
            'name': 'field_journal_findings', 'strict': True, 'schema': SCHEMA}},
        'provider': {'sort': 'price', 'require_parameters': True,
                     'max_price': {'prompt': 0.15, 'completion': 0.65}},
    }
    request = urllib.request.Request(
        'https://openrouter.ai/api/v1/chat/completions',
        data=json.dumps(payload).encode(),
        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        result = json.load(response)
    if result['model'] != MODEL:
        raise ValueError('Unexpected model')
    choice = result['choices'][0]
    if choice['finish_reason'] != 'stop':
        raise ValueError('Model response did not complete')
    return json.loads(choice['message']['content'])


def generate(context, api_key):
    brief = {'model': MODEL, 'prompt_version': PROMPT_VERSION,
             'state': 'unavailable', 'findings': []}
    if not eligible_findings(context):
        return {**brief, 'state': 'no_observations'}
    if not api_key:
        return brief
    try:
        findings = render_findings(context, ask(context, api_key))
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return brief
    return {**brief, 'state': 'ready' if findings else 'no_findings', 'findings': findings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('context', type=Path)
    args = parser.parse_args()
    context = json.loads(args.context.read_text())
    print(json.dumps({
        'schema_version': 1,
        'day_utc': context['today']['day_utc'],
        'stats': context['today'],
        'brief': generate(context, os.environ.get('OPENROUTER_API_KEY')),
    }, indent=2))


if __name__ == '__main__':
    main()
