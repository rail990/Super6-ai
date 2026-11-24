from unittest import TestCase

from super6.sky import final_scores, official_goal, slate, url_for


class SkyFeedTest(TestCase):
    def setUp(self):
        self.capture = {'url': url_for(19), 'captured_at': '2025-11-24T13:00:00Z',
                        'source_sha256': '1' * 64}
        self.payload = {'id': 19, 'season': '2025-26', 'isPaused': False, 'status': 'open',
                        'startDateTime': '2025-11-23T12:30:00Z', 'endDateTime': '2025-11-25T12:30:00Z',
                        'goldenGoalChallenge': {'isGoldenGoalScored': True, 'time': 7},
                        'scoreChallenges': [
                            {'id': i, 'void': False, 'match': {
                                'kickOffDateTime': f'2025-11-{25+i%2}T14:00:00Z',
                                'homeTeam': {'name': f'H{i}', 'score': 3},
                                'awayTeam': {'name': f'A{i}', 'score': 1},
                                'status': 'Match Complete', 'shortStatus': 'MC',
                                'competitionName': 'UEFA Champions League'}}
                            for i in range(6)]}

    def test_scheduled_slate_and_verified_settlement(self):
        item = slate(self.payload, self.capture)
        self.assertEqual(item['deadline'], '2025-11-25T12:30:00Z')
        self.assertEqual(item['fixtures'][1]['kickoff'], '2025-11-26T14:00:00Z')
        later = {**self.capture, 'captured_at': '2025-11-26T16:00:00Z'}
        with self.assertRaisesRegex(ValueError, 'yet to mark'):
            final_scores(self.payload, later, item)
        self.payload['status'] = 'complete'
        scores = final_scores(self.payload, later, item)
        self.assertEqual(len(scores), 6)
        self.assertEqual(scores['0']['score'], [3, 1])
        self.assertEqual(official_goal(self.payload, later)['minute'], 7)
        self.payload['scoreChallenges'][0]['match']['awayTeam']['name'] = 'Different'
        with self.assertRaisesRegex(ValueError, 'changed'):
            final_scores(self.payload, later, item)

    def test_rejects_void_and_mismatched_source(self):
        with self.assertRaisesRegex(ValueError, 'official Sky endpoint'):
            slate(self.payload, {**self.capture, 'url': url_for(17)})
        self.payload['scoreChallenges'][0]['void'] = True
        with self.assertRaisesRegex(ValueError, 'void'):
            slate(self.payload, self.capture)
