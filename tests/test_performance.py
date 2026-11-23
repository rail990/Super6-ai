import unittest

from super6.archive import load_rounds
from super6.evidence import timestamp
from super6.performance import METRICS, investigate, paired_intervals


class PerformanceAuditTests(unittest.TestCase):
    def test_paired_bootstrap_preserves_each_rounds_difference(self):
        differences = [dict.fromkeys(METRICS, value) for value in (-2, 2)]
        intervals = paired_intervals(differences, draws=500, seed=7)
        self.assertEqual(intervals['points'], {'difference': 0, 'interval_95': [-2, 2]})

    def test_archive_fixture_deltas_reconcile_with_paired_rounds(self):
        result = investigate(load_rounds(), timestamp('2026-11-23T00:00:00Z'), draws=100)
        for name, size, total_delta, different_picks in (
            ('full', 20, -6, 68), ('exclude_revised', 17, -15, 56)
        ):
            with self.subTest(cohort=name):
                audit = result[name]
                self.assertEqual(audit['round_count'], size)
                self.assertEqual(audit['comparisons']['expected_points_minus_threshold_13']
                                 ['different_picks'], 0)
                comparison = audit['comparisons']['expected_points_minus_fixed_poisson']
                self.assertEqual(comparison['different_picks'], different_picks)
                self.assertEqual(sum(row['point_difference'] for row in comparison['by_actual_wdl']),
                                 total_delta)
                self.assertAlmostEqual(comparison['paired_metrics']['points']['difference'],
                                       total_delta / size)
                for row in audit['rounds']:
                    self.assertEqual(len(row['fixtures']), 6)
                    for strategy, metrics in row['strategies'].items():
                        self.assertEqual(sum(f['picks'][strategy]['points'] for f in row['fixtures']),
                                         metrics['points'])
        self.assertTrue(all(r['source_quality'] != 'sky_revised_preview'
                            for r in result['exclude_revised']['rounds']))

    def test_empty_study_has_no_intervals(self):
        result = investigate([], timestamp('2026-11-23T00:00:00Z'), draws=1)
        self.assertEqual(result['full'], {'round_count': 0})
        self.assertEqual(result['exclude_revised'], {'round_count': 0})
