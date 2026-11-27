import copy
import json
import unittest
from pathlib import Path

from super6.backtest import adjusted, choice_metrics, fit_rho, strategies, study
from super6.evidence import timestamp
from super6.model import distribution, result_probabilities

AS_OF = timestamp('2026-11-23T00:00:00Z')


def archive():
    return json.loads(Path('data/rounds.json').read_text())


class BacktestTests(unittest.TestCase):
    def test_real_archive_has_two_complete_reconstructions_and_one_holdout(self):
        run = study(archive(), AS_OF)
        self.assertEqual([r['round']['id'] for r in run['rounds']],
                         ['2020–21 Round 1', '2021–22 Round 1'])
        self.assertEqual([r['round'] for r in run['excluded']], ['2026–27 Round 18'])
        self.assertEqual(run['summary']['expected_points']['average_points'], 6.5)
        self.assertAlmostEqual(run['summary']['expected_points']['correct_result_accuracy'], 5 / 12)
        self.assertEqual(run['summary']['expected_points']['observed_13_plus'], 0)
        self.assertEqual(run['summary']['threshold_13']['calibration'][0]['rounds'], 2)
        self.assertEqual(run['dixon_coles'][0]['training_matches'], 6)

    def test_missing_results_and_unavailable_by_cutoff_are_excluded(self):
        rounds = archive()
        del rounds[1]['fixtures'][0]['result']
        self.assertEqual(len(study(rounds, AS_OF)['rounds']), 1)
        before_release = timestamp('2020-09-12T21:00:00+01:00')
        self.assertEqual(study(rounds, before_release)['rounds'], [])

    def test_heldout_outcome_does_not_change_fit_or_predictions(self):
        rounds = archive()
        prior = study(rounds, AS_OF)
        rounds[1]['fixtures'][0]['result']['score'] = [1, 0]
        updated = study(rounds, AS_OF)
        self.assertEqual(prior['dixon_coles'][0]['rho'], updated['dixon_coles'][0]['rho'])
        self.assertEqual(prior['rounds'][1]['strategies']['modal']['picks'],
                         updated['rounds'][1]['strategies']['modal']['picks'])

    def test_prior_round_whose_results_were_published_late_cannot_train(self):
        rounds = copy.deepcopy(archive())
        rounds[0]['fixtures'][0]['result']['available_at'] = '2021-08-07T15:00:00+01:00'
        self.assertEqual(study(rounds, AS_OF)['dixon_coles'], [])

    def test_late_deadline_evidence_rejected(self):
        rounds = archive()
        rounds[1]['deadline_evidence']['available_at'] = rounds[1]['deadline']
        with self.assertRaisesRegex(ValueError, 'predate'):
            study(rounds, AS_OF)

    def test_threshold_is_distinct_when_tail_objective_changes_pick(self):
        rates = [(0.92, 1.60), (0.54, 2.28), (1.28, 2.45),
                 (2.59, 2.20), (0.56, 0.89), (1.81, 2.56)]
        scores = [distribution(*rate) for rate in rates]
        results = strategies(scores)
        expected = results['expected_points'][1]
        threshold = results['threshold_13'][1]
        self.assertGreater(threshold['probability_13_plus'], expected['probability_13_plus'])
        self.assertLess(threshold['expected_points'], expected['expected_points'])
        direct = choice_metrics(scores, list(map(result_probabilities, scores)), results['threshold_13'][0])
        self.assertEqual(direct, threshold)

    def test_dixon_coles_is_normalized_and_requires_training(self):
        self.assertIsNone(fit_rho([((1.4, 1.1), (0, 0))] * 5))
        self.assertIsNone(adjusted((3.0, 3.0), 0.12))
        corrected = adjusted((1.4, 1.1), -0.1)
        self.assertAlmostEqual(sum(corrected.values()), 1)
        self.assertGreater(corrected[0, 0], distribution(1.4, 1.1)[0, 0])
