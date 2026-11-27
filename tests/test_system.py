import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from super6.capture import freeze, frozen
from super6.evidence import RESEARCH, validate
from super6.import_round import save
from super6.model import distribution, golden_goal, points, predict, result_probabilities
from super6.report import report
from super6.venue import attach, load


# Artificial inputs exercise the pipeline only. They are never loaded by the dashboard.
def example():
    source = {
        'url': 'https://example.invalid/snapshot',
        'available_at': '2025-01-01T10:00:00Z',
        'note': 'Synthetic test input',
        'captured_at': '2025-01-01T10:01:00Z',
        'source_sha256': '0' * 64,
    }
    research = {category: dict(source) for category in RESEARCH}
    research['odds']['decimal'] = [2.1, 3.2, 3.6]
    research['xg'].update(home=1.6, away=1.1)
    research['xga'].update(home=0.9, away=1.3)
    return {
        'id': 'Synthetic test only',
        'deadline': '2025-01-01T12:00:00Z',
        'deadline_basis': 'Synthetic posted deadline',
        'official': dict(source, url='https://www.skysports.com/test'),
        'fixtures': [
            {'home': f'A{i}', 'away': f'B{i}', 'kickoff': '2025-01-01T12:00:00Z',
             'research': copy.deepcopy(research),
             'result': dict(source, available_at='2025-01-01T14:00:00Z', captured_at='2025-01-01T14:01:00Z',
                            score=[1, 0], status='final')}
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
        item['fixtures'][0]['research']['odds'].update(
            available_at='2025-01-01T12:01:00Z', captured_at='2025-01-01T12:02:00Z')
        with self.assertRaisesRegex(ValueError, 'Late evidence'):
            validate(item)

    def test_partial_evidence_and_missing_research_do_not_generate_picks(self):
        item = example()
        del item['fixtures'][0]['research']['injuries']
        self.assertIsNone(report([item], {})['rounds'][0]['prediction'])
        with self.assertRaisesRegex(ValueError, 'pre-deadline'):
            predict(item)

    def test_bad_evidence_url_rejected(self):
        for url in ('https://example.invalid:abc/test', 'https://user@example.invalid/test',
                    'https://example.invalid/test path'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                item = example()
                item['fixtures'][0]['research']['form']['url'] = url
                validate(item)

    def test_final_status_and_timing_required(self):
        item = example()
        result = item['fixtures'][0]['result']
        result['status'] = 'live'
        with self.assertRaisesRegex(ValueError, 'final status'):
            validate(item)
        result.update(status='final', available_at='2025-01-01T12:01:00Z')
        with self.assertRaisesRegex(ValueError, 'too early'):
            validate(item)

    def test_no_golden_goal_conflicts_with_a_scoring_match(self):
        item = example()
        item['golden_goal'] = dict(item['fixtures'][0]['result'],
                                   url='https://www.skysports.com/test', minute=None)
        with self.assertRaisesRegex(ValueError, 'goalless'):
            validate(item)

    def test_snapshot_refuses_unarchived_late_evidence_and_detects_input_changes(self):
        item = example()
        evidence = item['fixtures'][0]['research']['odds']
        evidence['captured_at'] = '2025-01-01T12:01:00Z'
        with tempfile.TemporaryDirectory() as directory:
            snapshots = Path(directory)
            with self.assertRaises(ValueError):
                freeze(item, snapshots)
            evidence.update(archive_url='https://example.invalid/archived',
                            archived_at='2025-01-01T11:00:00Z')
            file = freeze(item, snapshots)
            self.assertEqual(freeze(item, snapshots), file)
            self.assertTrue(frozen(item, snapshots))
            evidence['decimal'][0] = 2.15
            self.assertFalse(frozen(item, snapshots))
            self.assertTrue(file.exists())

    def test_freeze_checks_captured_source_bytes(self):
        item = example()
        data = b'local synthetic source'
        digest = hashlib.sha256(data).hexdigest()
        item['official']['source_sha256'] = digest
        for fixture in item['fixtures']:
            for record in fixture['research'].values():
                record['source_sha256'] = digest
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            source = path / digest
            source.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'has changed'):
                freeze(item, path / 'snapshots', path)
            source.write_bytes(data)
            self.assertTrue(freeze(item, path / 'snapshots', path).exists())

    def test_report_withholds_model_forecast_without_frozen_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(report([example()], {}, Path(directory))['rounds'][0]['prediction'])

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



class VenueTests(unittest.TestCase):
    def test_dated_results_are_filtered_before_deadline_and_odds_are_ignored(self):
        item = example()
        with tempfile.TemporaryDirectory() as directory:
            table = Path(directory) / 'results.csv'
            lines = ['Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,B365CH']
            for i in range(6):
                for day in range(25, 31):
                    lines.extend([f'{day}/12/2024,A{i},Opponent,1,0,H,unused',
                                  f'{day}/12/2024,Opponent,B{i},0,2,A,unused'])
                lines.extend([f'01/01/2025,A{i},Opponent,90,0,H,unused',
                              f'01/01/2025,Opponent,B{i},90,0,H,unused'])
            table.write_text('\n'.join(lines))
            source = load(table, 'https://example.invalid/results.csv')
            attach(item, [source, source], {})
            for fixture in item['fixtures']:
                self.assertEqual([m['score'] for m in fixture['venue_history']['home']], [[1, 0]] * 5)
                self.assertEqual([m['score'] for m in fixture['venue_history']['away']], [[2, 0]] * 5)
                self.assertEqual(fixture['venue_history']['home'][0]['available_at'],
                                 '2024-12-31T00:00:00+00:00')


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
        self.assertEqual(result['simulated_probability_13_plus'], sum(result['points_counts'][13:]) / 100_000)
        self.assertAlmostEqual(result['probability_13_plus'], result['simulated_probability_13_plus'], delta=0.005)
        self.assertAlmostEqual(result['expected_points'],
                               sum(f['expected_points'] for f in result['fixtures']), delta=0.06)

    def test_golden_goal_uses_all_six_fixtures(self):
        small = golden_goal([(1, 1)] * 6)
        large = golden_goal([(2, 2)] * 6)
        self.assertAlmostEqual(sum(small['minute_probabilities']) + small['no_goal'], 1)
        self.assertLess(large['minute'], small['minute'])

    def test_backtest_scores_results_without_changing_predictions(self):
        item = example()
        with tempfile.TemporaryDirectory() as directory:
            snapshots = Path(directory)
            freeze(item, snapshots)
            result = report([item], {}, snapshots)
            before = result['rounds'][0]['prediction']
            for fixture, prediction in zip(item['fixtures'], before['fixtures']):
                fixture['result']['score'] = prediction['score']
            after = report([item], {}, snapshots)
        self.assertEqual(after['rounds'][0]['prediction'], before)
        self.assertEqual(after['backtest']['mean_points'], 30)
        self.assertEqual(after['backtest']['hit_rate_13_plus'], 1)

    def test_checked_in_archive_and_baseline(self):
        rounds = json.loads(Path('data/rounds.json').read_text())
        baseline = json.loads(Path('data/baseline.json').read_text())
        self.assertTrue(rounds)
        self.assertEqual(baseline['points'], 7)
        self.assertEqual(baseline['exact_scores'] * 5 + baseline['additional_correct_results'] * 2, 7)
        result = report(rounds, baseline)
        self.assertEqual(result['rounds'][0]['derived_goal'], 13)
        self.assertEqual(result['historical']['venue_goals']['rounds'], 2)
        self.assertEqual(result['historical']['venue_goals']['golden_goal_minute_rounds'], 1)
        self.assertEqual(result['matched_backtest']['xg_market']['rounds'], 0)


if __name__ == '__main__':
    unittest.main()
