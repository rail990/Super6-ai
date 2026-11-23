import copy
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from super6.evidence import validate
from super6.model import chronological_goal, forecast, golden_goal
from super6.report import FORM, report
from super6.research import api_data, capture, enrich
from test_system import example

OBSERVED = '2025-01-01T11:00:00Z'
CSV = b"""date,home,away,ft_home,ft_away,ft_result
2024-12-01,A0,X,0,0,D
2024-12-05,X,A0,1,2,A
2024-12-08,A0,Y,1,0,H
2025-01-01,A0,Z,19,0,H
"""


class ResearchTests(unittest.TestCase):
    def test_csv_form_missing_teams_and_late_capture(self):
        dataset = capture('open-matchday', CSV, 'https://example.invalid/results.csv', OBSERVED, 'CL')
        item = enrich(example(), [dataset, dataset])
        stats = item['fixtures'][0]['stats']
        self.assertEqual(stats['home']['recent'], {
            'matches': 3, 'won': 2, 'drawn': 1, 'lost': 0,
            'goals_for': 3, 'goals_against': 1, 'clean_sheets': 2,
        })
        self.assertEqual(stats['home']['venue']['matches'], 2)
        self.assertEqual(stats['away']['recent']['matches'], 0)
        self.assertIsNone(stats['away']['opposition_ppg'])
        result = report([item], {})['rounds'][0]
        self.assertIsNone(result['recommended_model'])
        self.assertTrue(result['quality_flags'])
        with self.assertRaisesRegex(ValueError, 'before the round deadline'):
            enrich(example(), {**dataset, 'available_at': '2025-01-01T12:00:01Z'})

    def test_provider_future_result_cannot_be_relabelled(self):
        data = capture('open-matchday', CSV, 'https://example.invalid/results.csv', OBSERVED, 'CL')
        data['matches'][0]['available_at'] = '2025-01-01T11:01:00Z'
        with self.assertRaisesRegex(ValueError, 'unavailable at capture'):
            enrich(example(), data)

    def test_api_reads_regular_finished_only_and_keeps_token_out_of_output(self):
        match = {'status': 'FINISHED', 'id': 1, 'utcDate': '2024-12-02T20:00:00Z',
                 'competition': {'code': 'CL'}, 'homeTeam': {'name': 'Home'}, 'awayTeam': {'name': 'Away'},
                 'score': {'duration': 'REGULAR', 'fullTime': {'home': 1, 'away': 0}}}
        body = json.dumps({'matches': [match, {**match, 'status': 'SCHEDULED', 'id': 2}]}).encode()
        with (patch.dict('os.environ', {'FOOTBALL_DATA_TOKEN': 'test-token'}),
              patch('super6.research.build_opener') as opener):
            context = opener.return_value.open.return_value
            context.__enter__.return_value = Mock(read=Mock(return_value=body))
            result = api_data('CL', '2024-12-01', '2025-01-01')
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(request.get_header('X-auth-token'), 'test-token')
            self.assertNotIn('test-token', json.dumps(result))
            self.assertEqual([match['id'] for match in result['matches']], ['1'])
            fixtures = api_data('CL', '2024-12-01', '2025-01-01', fixtures=True)
            self.assertEqual(len(fixtures['matches']), 2)
            self.assertIn('cross-checking only', fixtures['note'])

    def test_real_round_has_provisional_forecast_and_stale_inputs_are_withheld(self):
        archive = json.loads(Path('data/rounds.json').read_text())
        item = next(r for r in archive if r['id'] == '2026–27 Round 18')
        self.assertEqual(len({f['id'] for f in item['fixtures']}), 6)
        row = report([item], {})['rounds'][0]
        self.assertEqual(row['recommended_model'], FORM)
        self.assertIsNone(row['prediction'])
        pred = row['benchmarks'][FORM]['prediction']
        self.assertTrue(all(len(f['top_scores']) == 5 for f in pred['fixtures']))
        self.assertGreater(pred['probability_all_exact'], 0)
        self.assertEqual(pred['trials'], 100_000)
        stale = copy.deepcopy(item)
        stale['fixtures'][0]['stats']['home']['latest_available_at'] = '2026-09-01T00:00:00Z'
        self.assertIsNone(report([stale], {})['rounds'][0]['recommended_model'])
        duplicate = copy.deepcopy(item)
        duplicate['fixtures'][0]['id'] = duplicate['fixtures'][1]['id']
        with self.assertRaisesRegex(ValueError, 'distinct fixture identifiers'):
            validate(duplicate)


class ForecastTests(unittest.TestCase):
    def test_staggered_kickoffs_and_alternative_combinations(self):
        early = datetime(2026, 11, 24, 20, tzinfo=timezone.utc)
        late = datetime(2026, 11, 25, 20, tzinfo=timezone.utc)
        rates = [(1.4, 1.0)] * 6
        same_time = chronological_goal(rates, [early] * 6)
        staggered = chronological_goal(rates, [early] * 3 + [late] * 3)
        self.assertEqual(same_time['elapsed_minute'], golden_goal(rates)['minute'])
        self.assertGreater(staggered['elapsed_minute'], same_time['elapsed_minute'])
        self.assertEqual(staggered['windows'][1]['start'], 1440)
        prediction = forecast([(r, None) for r in rates])
        self.assertGreaterEqual(prediction['modal_combination']['probability_all_exact'],
                                prediction['probability_all_exact'])
        self.assertEqual(len(prediction['modal_combination']['scores']), 6)
