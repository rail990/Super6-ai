import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from super6.live import freeze_round, settle_round


class LiveTest(TestCase):
    def test_freeze_once_and_score_only_frozen_picks(self):
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        deadline = start + timedelta(days=1)
        digest = hashlib.sha256(b'reviewed evidence').hexdigest()
        source = {'url': 'https://super6.skysports.com/', 'note': 'Reviewed fixture card',
                  'available_at': start.isoformat(), 'captured_at': start.isoformat(),
                  'source_sha256': digest}
        round_data = {'id': 'test', 'deadline': deadline.isoformat(), 'deadline_basis': 'Sky card',
                      'official': {**source, 'confirmed_at': start.isoformat()},
                      'fixtures': [{'id': str(i), 'home': f'H{i}', 'away': f'A{i}',
                                    'kickoff': (deadline + timedelta(minutes=i*10)).isoformat(),
                                    'kickoff_source': source['url']} for i in range(6)]}
        with TemporaryDirectory() as temp:
            directory = Path(temp)
            with patch('super6.live.now', return_value=start):
                with self.assertRaisesRegex(ValueError, 'Missing or changed'):
                    freeze_round(round_data, directory, directory)
                (directory / digest).write_bytes(b'reviewed evidence')
                path = freeze_round(round_data, directory, directory)
                before = path.read_bytes()
                with self.assertRaises(FileExistsError):
                    freeze_round(round_data, directory, directory)
            forecast = json.loads(before)['predictions']['fixed_poisson']
            self.assertEqual(forecast['trials'], 100_000)
            self.assertEqual(len(forecast['fixtures'][0]['top_scores']), 5)
            end = deadline + timedelta(hours=3)
            results = {str(i): {**source, 'available_at': end.isoformat(), 'captured_at': end.isoformat(),
                                'status': 'final', 'score': pick['score']}
                       for i, pick in enumerate(forecast['fixtures'])}
            with patch('super6.live.now', return_value=end + timedelta(seconds=1)):
                late = copy.deepcopy(round_data)
                late['id'] = 'late'
                with self.assertRaisesRegex(ValueError, 'deadline has passed'):
                    freeze_round(late, directory, directory)
                with self.assertRaisesRegex(ValueError, 'all six'):
                    settle_round('test', {}, directory, directory)
                result = settle_round('test', results, directory, directory)
                with self.assertRaises(FileExistsError):
                    settle_round('test', results, directory, directory)
            self.assertEqual(json.loads(result.read_bytes())['evaluations']['fixed_poisson']['points'], 30)
            self.assertEqual(path.read_bytes(), before)
