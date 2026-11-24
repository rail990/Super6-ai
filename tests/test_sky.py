from tempfile import TemporaryDirectory
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from super6.live import prepare_round
from super6.sky import final_scores, match_stats, official_goal, slate, url_for


class SkyFeedTest(TestCase):
    def setUp(self):
        self.capture = {'url': url_for(19), 'captured_at': '2025-11-24T13:00:00Z',
                        'source_sha256': '1' * 64}
        self.payload = {'id': 19, 'season': '2025-26', 'isPaused': False, 'status': 'open',
                        'startDateTime': '2025-11-23T12:30:00Z', 'endDateTime': '2025-11-25T12:30:00Z',
                        'goldenGoalChallenge': {'isGoldenGoalScored': True, 'time': 7},
                        'scoreChallenges': [
                            {'id': i, 'void': False, 'match': {
                                'id': i+1, 'kickOffDateTime': f'2025-11-{25+i%2}T14:00:00Z',
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


    def test_match_form_excludes_unavailable_scores_and_marks_missing_strength(self):
        match = {'homeTeam': {'name': 'Home', 'id': 1}, 'awayTeam': {'name': 'Away', 'id': 2}}
        previous = {'home': {'teamId': 1, 'score': 3}, 'away': {'teamId': 3, 'score': 1},
                    'outcome': 'w', 'matchDateTime': '2025-11-24T09:00:00Z'}
        future = {**previous, 'matchDateTime': '2025-11-24T12:00:00Z'}
        payload = {'home': {'name': 'Home', 'matchHistory': [future, previous, previous]},
                   'away': {'name': 'Away', 'matchHistory': []}}
        stats = match_stats(payload, match, self.capture)
        self.assertEqual(stats['home']['recent']['matches'], 1)
        self.assertEqual(stats['home']['venue']['goals_for'], 3)
        self.assertIsNone(stats['home']['opposition_ppg'])
        self.assertEqual(stats['away']['recent']['matches'], 0)

    def test_failed_sources_leave_the_verified_slate_available(self):
        plan = [{'fixture_id': 1, 'category': 'team_news', 'url': 'https://example.invalid/team-news'}]
        with TemporaryDirectory() as temp, patch('super6.live.collect_source', side_effect=OSError):
            item, gaps = prepare_round(self.payload, self.capture, Path(temp), plan)
        self.assertEqual(len(item['fixtures']), 6)
        self.assertTrue(all('stats' not in fixture for fixture in item['fixtures']))
        self.assertEqual(len(gaps), 7)
        self.assertEqual({gap['status'] for gap in gaps}, {'unavailable'})
