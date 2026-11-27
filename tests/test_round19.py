import json
from pathlib import Path
from unittest import TestCase

from super6.evidence import timestamp
from super6.experiments import PROTOCOL
from super6.round19 import matching_scores


class Round19ResearchTest(TestCase):
    def test_frozen_research_record_covers_registered_models(self):
        record = json.loads(Path('data/prospective/research/round19-early.json').read_bytes())
        candidates = json.loads(PROTOCOL.read_bytes())['candidates']
        self.assertEqual(set(record['models']), {'fixed_poisson', *candidates})
        self.assertLess(timestamp(record['frozen_at']), timestamp(record['deadline']))
        for reference in record['fixtures']:
            self.assertAlmostEqual(sum(reference['market']['normalized_1x2']), 1)
        for forecast in record['models'].values():
            self.assertEqual(sum(forecast['points_counts']), 100_000)
            self.assertEqual(len(forecast['fixtures']), 6)

    def test_league_feed_conflict_fails_closed(self):
        feed = {'matches': [(timestamp('2026-11-22T00:00:00Z'), 'Tottenham', 'Ipswich', (2, 0))]}
        cards = [{'fixtures': [{'home': 'Spurs', 'away': 'Ipswich', 'score': [0, 2],
                                 'competition': 'Premier League', 'kickoff': '2026-11-21T15:00:00Z'}]}]
        with self.assertRaisesRegex(ValueError, 'League score differs'):
            matching_scores(feed, cards, timestamp('2026-11-24T00:00:00Z'))
