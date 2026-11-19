import unittest
from unittest.mock import patch

from scripts.generate_brief import generate, render_findings


class BriefTest(unittest.TestCase):
    def setUp(self):
        self.context = {
            'today': {'evidence_id': 'day-2026-11-18', 'metrics': {'connections': 100}},
            'baseline': {'evidence_id': 'baseline-7d', 'n_days': 5, 'medians': {'connections': 50}},
            'recurring_samples': [
                {'evidence_id': 'sample-1', 'days_observed': 2, 'observed_today': True,
                 'observations': [{'verified_captures': 3,
                                   'capture_sessions_with_download_attempt': 1}]}
            ],
        }

    def test_renders_from_exact_evidence(self):
        findings = render_findings(self.context, {'findings': [
            {'kind': 'baseline', 'evidence_id': 'day-2026-11-18:connections'},
            {'kind': 'recurrence', 'evidence_id': 'sample-1'},
        ]})
        self.assertIn('100 connections', findings[0]['text'])
        self.assertIn('median of 50', findings[0]['text'])
        self.assertIn('baseline-7d:connections', findings[0]['evidence_ids'])
        self.assertIn('execution are unverified', findings[1]['text'])

    def test_invalid_response_preserves_stats_only_state(self):
        with patch('scripts.generate_brief.ask', return_value={'findings': [
            {'kind': 'baseline', 'evidence_id': 'day-2026-11-18:invented'},
        ]}):
            self.assertEqual(generate(self.context, 'fixture')['state'], 'unavailable')
        self.assertEqual(generate(self.context, None)['findings'], [])
