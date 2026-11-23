import copy
import json
import tempfile
import unittest
from pathlib import Path

from super6.evidence import RESEARCH, validate
from super6.import_round import save
from super6.model import distribution, golden_goal, points, predict, result_probabilities
from super6.report import report


# Artificial inputs exercise the pipeline only. They are never loaded by the dashboard.
def example():
    source = {
        'url': 'https://example.invalid/snapshot',
        'available_at': '2025-01-01T10:00:00Z',
        'note': 'Synthetic test input',
    }
    research = {category: dict(source) for category in RESEARCH}
    research['odds']['decimal'] = [2.1, 3.2, 3.6]
    research['xg'].update(home=1.6, away=1.1)
    research['xga'].update(home=0.9, away=1.3)
    return {
        'id': 'Synthetic test only',
        'deadline': '2025-01-01T12:00:00Z',
        'official': dict(source, url='https://www.skysports.com/test'),
        'fixtures': [
            {'home': f'A{i}', 'away': f'B{i}', 'kickoff': '2025-01-01T12:00:00Z',
             'research': copy.deepcopy(research),
             'result': dict(source, available_at='2025-01-01T14:00:00Z', score=[1, 0])}
            for i in range(6)
        ],
    }


class EvidenceTests(unittest.TestCase):
    def test_six_unique_fixtures_and_official_source_required(self):
        for corruption in ('short', 'duplicate', 'unofficial'):
            with self.subTest(corruption=corruption), self.assertRaises(ValueError):
                item = example()
                if corruption == 'short':
                    item['fixtures'].pop()
                elif corruption == 'duplicate':
                    item['fixtures'][1]['away'] = item['fixtures'][0]['home']
                else:
                    item['official']['url'] = 'https://skysports.com.example.invalid/test'
                validate(item)

    def test_research_after_round_deadline_rejected_even_before_later_kickoff(self):
        item = example()
        item['fixtures'][0]['kickoff'] = '2025-01-01T13:00:00Z'
        item['fixtures'][0]['research']['odds']['available_at'] = '2025-01-01T12:01:00Z'
        with self.assertRaisesRegex(ValueError, 'Late evidence'):
            validate(item)

    def test_partial_evidence_and_missing_research_do_not_generate_picks(self):
        item = example()
        del item['fixtures'][0]['research']['injuries']
        self.assertIsNone(report([item], {})['rounds'][0]['prediction'])
        with self.assertRaisesRegex(ValueError, 'pre-deadline'):
            predict(item)

    def test_import_conflict_and_invalid_replacement_preserve_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'rounds.json'
            item = example()
            save(item, archive)
            with self.assertRaisesRegex(ValueError, 'already exists'):
                save(item, archive)
            item['fixtures'].pop()
            with self.assertRaises(ValueError):
                save(item, archive, replace=True)
            self.assertEqual(len(json.loads(archive.read_text())[0]['fixtures']), 6)


class ModelTests(unittest.TestCase):
    def test_probabilities_and_scoring(self):
        scores = distribution(1.7, 1.1)
        self.assertAlmostEqual(sum(scores.values()), 1)
        self.assertAlmostEqual(sum(result_probabilities(scores)), 1)
        self.assertEqual([points([1, 0], result) for result in ([1, 0], [2, 0], [0, 0])],
                         [5, 2, 0])

    def test_simulation_is_reproducible_and_matches_analytic_totals(self):
        item = example()
        result = predict(item)
        self.assertEqual(result, predict(item))
        self.assertEqual(sum(result['points_counts']), 100_000)
        self.assertEqual(result['probability_13_plus'], sum(result['points_counts'][13:]) / 100_000)
        self.assertAlmostEqual(result['expected_points'],
                               sum(f['expected_points'] for f in result['fixtures']), delta=0.06)

    def test_golden_goal_uses_all_six_fixtures(self):
        small = golden_goal([(1, 1)] * 6)
        large = golden_goal([(2, 2)] * 6)
        self.assertAlmostEqual(sum(small['minute_probabilities']) + small['no_goal'], 1)
        self.assertLess(large['minute'], small['minute'])

    def test_backtest_scores_results_without_changing_predictions(self):
        item = example()
        result = report([item], {})
        before = result['rounds'][0]['prediction']
        for fixture, prediction in zip(item['fixtures'], before['fixtures']):
            fixture['result']['score'] = prediction['score']
        after = report([item], {})
        self.assertEqual(after['rounds'][0]['prediction'], before)
        self.assertEqual(after['backtest']['mean_points'], 30)
        self.assertEqual(after['backtest']['hit_rate_13_plus'], 1)

    def test_checked_in_archive_and_baseline(self):
        rounds = json.loads(Path('data/rounds.json').read_text())
        baseline = json.loads(Path('data/baseline.json').read_text())
        self.assertTrue(rounds)
        self.assertEqual(baseline['points'], 7)
        self.assertEqual(baseline['exact_scores'] * 5 + baseline['additional_correct_results'] * 2, 7)
        report(rounds, baseline)


if __name__ == '__main__':
    unittest.main()
