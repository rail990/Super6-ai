import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from super6.archive import candidate_index, load_rounds, score_feed, verified_result
from super6.backtest import study
from super6.evidence import timestamp


class ArchiveExpansionTests(unittest.TestCase):
    def test_real_cohort_and_evidence(self):
        result = study(load_rounds(), timestamp('2026-11-23T00:00:00Z'))
        self.assertEqual(Counter(r['source_quality'] for r in result['rounds']), {
            'sky_advertised': 9, 'sky_first_kickoff_rule': 8, 'sky_revised_preview': 3
        })
        self.assertEqual(len(result['rounds']), 20)
        manifest = json.loads(Path('data/archive-review.json').read_text())
        self.assertEqual(len(manifest['rounds']), 18)
        self.assertAlmostEqual(result['summary']['fixed_poisson']['average_points'], 7.1)
        self.assertAlmostEqual(result['summary']['threshold_13']['average_points'], 6.8)
        self.assertEqual(len(result['dixon_coles']), 19)
        for row in result['rounds']:
            record = row['round']
            for fixture in record['fixtures']:
                self.assertLess(timestamp(record['deadline']), verified_result(fixture['result']))
                for history in fixture['venue_history'].values():
                    self.assertTrue(all(timestamp(m['available_at']) < timestamp(record['deadline'])
                                        for m in history))

    def test_incomplete_leads_are_separate_from_backtest(self):
        entries = candidate_index()
        self.assertEqual(Counter(item['quality'] for item in entries), {
            'secondary_lead': 82, 'primary_partial': 13
        })
        self.assertTrue(all(item['status'] == 'incomplete' for item in entries))
        self.assertFalse(set(r['id'] for r in load_rounds()) & {c['id'] for c in entries})

    def test_score_feed_uses_uk_availability_and_ignores_odds(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'data.csv'
            path.write_text('Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,B365CH\n'
                            '20/10/18,15:00,Home,Away,2,1,H,not-a-price\n')
            feed = score_feed(path, '1819/E0.csv')
            self.assertEqual(feed['fixtures'][0][3:], ('15:00', [2, 1]))
            self.assertEqual(feed['matches'][0][0].isoformat(), '2018-10-21T00:00:00+01:00')
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                verified_result({'url': feed['url'], 'sha256': 'unverified'})
