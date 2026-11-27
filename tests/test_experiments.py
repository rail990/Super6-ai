import copy
import json
from datetime import timedelta
from unittest import TestCase

from super6.archive import load_rounds
from super6.evidence import timestamp
from super6.experiments import PROTOCOL, study


class ExperimentTest(TestCase):
    def test_discovery_rounds_never_enter_registered_holdout(self):
        result = study(load_rounds(), timestamp('2026-11-24T12:00:00Z'))
        self.assertEqual(result['eligible_holdouts'], 0)
        self.assertEqual(result['summary'], {})

    def test_synthetic_paired_fold_excludes_future_feed_results(self):
        rounds = [r for r in load_rounds() if r.get('source_quality') == 'sky_advertised']
        rounds.sort(key=lambda item: timestamp(item['deadline']))
        target = rounds[-1]
        cutoff = timestamp(target['deadline'])
        protocol = json.loads(PROTOCOL.read_text())
        protocol['holdout_deadline_from'] = target['deadline']
        protocol['minimum_holdout_rounds'] = 1
        sources = {}
        competitions = {target['id']: {}}
        for fixture in target['fixtures']:
            for history in fixture['venue_history'].values():
                for match in history:
                    feed = sources.setdefault(match['url'], {'sha256': match['sha256'], 'matches': []})
                    feed['matches'].extend([(cutoff - timedelta(days=1), match['opponent'], 'Test', [2, 1])] * 30)
            competitions[target['id']][fixture['home']] = fixture['venue_history']['home'][0]['url']
        future = copy.deepcopy(sources)
        for feed in future.values():
            feed['matches'].append((cutoff, 'Test', 'Future', [99, 99]))
        as_of = timestamp('2026-11-24T12:00:00Z')
        report = study(rounds, as_of, sources, competitions, protocol)
        self.assertEqual(report['eligible_holdouts'], 1)
        self.assertEqual(len(report['summary']), 7)
        self.assertEqual(report, study(rounds, as_of, future, competitions, protocol))
