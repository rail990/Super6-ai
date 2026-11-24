import copy
import json
from unittest import TestCase

from super6.legacy_settlement import EXPECTATIONS, expectations, settle
from super6.live import encode
from super6.sky import url_for


class LegacySettlementTest(TestCase):
    def test_comparison_uses_pinned_picks_and_requires_completed_sky_slate(self):
        baseline = json.loads(EXPECTATIONS.read_bytes())
        self.assertEqual(encode(expectations()), EXPECTATIONS.read_bytes())
        fixtures = baseline['fixtures']
        picks = baseline['models']['recent_form']['fixtures']
        payload = {
            'id': 18, 'season': '2026-27', 'status': 'complete', 'isPaused': False,
            'startDateTime': '2026-11-22T18:45:00Z', 'endDateTime': baseline['deadline'],
            'goldenGoalChallenge': {'isGoldenGoalScored': True, 'time': 8},
            'scoreChallenges': [
                {'id': i, 'void': False, 'match': {
                    'homeTeam': {'name': fixture['home'], 'score': pick['score'][0]},
                    'awayTeam': {'name': fixture['away'], 'score': pick['score'][1]},
                    'kickOffDateTime': fixture['kickoff'], 'competitionName': 'UEFA Champions League',
                    'status': 'Match Complete', 'shortStatus': 'MC'}}
                for i, (fixture, pick) in enumerate(reversed(list(zip(fixtures, picks, strict=True))))]
        }
        capture = {'url': url_for(18), 'captured_at': '2026-11-26T00:00:00Z',
                   'source_sha256': 'a' * 64}
        result = settle(payload, capture, baseline)['comparisons']['recent_form']
        self.assertEqual(result['points'], 30)
        self.assertAlmostEqual(result['actual_minus_expected'], 30 - result['expected_points'])
        incomplete = copy.deepcopy(payload)
        incomplete['scoreChallenges'][0]['match']['shortStatus'] = ''
        with self.assertRaisesRegex(ValueError, 'awaiting final'):
            settle(incomplete, capture, baseline)
        payload['scoreChallenges'][0]['match']['awayTeam']['name'] = 'Different'
        with self.assertRaisesRegex(ValueError, 'differs'):
            settle(payload, capture, baseline)
