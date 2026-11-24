"""Normalize the public read-only Sky Super 6 round feed used by its website."""
import re

from .evidence import evidence, score_pair, timestamp, validate

ROOT = 'https://api.s6.sbgservices.com/v2/round'


def url_for(round_number):
    if round_number == 'active':
        return f'{ROOT}/active'
    if not re.fullmatch(r'[1-9][0-9]{0,2}', str(round_number)):
        raise ValueError('Use an official Sky round number or active')
    return f'{ROOT}/{round_number}'


def slate(payload, capture):
    round_number = payload['id']
    if capture['url'] not in (url_for(round_number), url_for('active')):
        raise ValueError('Expected the official Sky endpoint for this round')
    if not re.fullmatch(r'[0-9]{4}-[0-9]{2}', payload['season']):
        raise ValueError('Invalid Sky season')
    opened = timestamp(payload['startDateTime'])
    deadline = timestamp(payload['endDateTime'])
    if opened >= deadline or payload['isPaused']:
        raise ValueError('Sky round has an invalid entry window or is paused')
    fixtures = []
    for challenge in payload['scoreChallenges']:
        if challenge['void']:
            raise ValueError('A void Sky fixture requires a reviewed settlement rule')
        match = challenge['match']
        fixtures.append({'id': str(challenge['id']), 'home': match['homeTeam']['name'],
                         'away': match['awayTeam']['name'], 'kickoff': match['kickOffDateTime'],
                         'kickoff_source': capture['url'], 'competition': match['competitionName']})
    item = {'id': f"Sky {payload['season']} Round {round_number}", 'deadline': payload['endDateTime'],
            'opens': payload['startDateTime'], 'sky_season': payload['season'], 'sky_round': round_number,
            'deadline_basis': 'Sky Super 6 round feed endDateTime',
            'official': {**capture, 'note': 'Six score challenges and entry deadline from Sky Super 6.',
                         'available_at': capture['captured_at']},
            'fixtures': fixtures}
    if timestamp(capture['captured_at']) < deadline:
        item['official']['confirmed_at'] = capture['captured_at']
        validate(item)
    return item


def final_scores(payload, capture, frozen_round):
    reviewed = slate(payload, capture)
    if payload['status'] != 'complete':
        raise ValueError('Sky has yet to mark the round complete')
    if reviewed['id'] != frozen_round['id'] or reviewed['deadline'] != frozen_round['deadline']:
        raise ValueError('Sky round identity or deadline differs from the frozen slate')
    keys = ('home', 'away', 'kickoff')
    recorded = {f['id']: tuple(f[key] for key in keys) for f in frozen_round['fixtures']}
    if {f['id']: tuple(f[key] for key in keys) for f in reviewed['fixtures']} != recorded:
        raise ValueError('Sky changed the frozen fixtures or kickoff times')
    results = {}
    for challenge in payload['scoreChallenges']:
        match = challenge['match']
        if match['status'] != 'Match Complete' or match['shortStatus'] != 'MC':
            raise ValueError('A Sky fixture is still awaiting final status')
        score = [match['homeTeam']['score'], match['awayTeam']['score']]
        score_pair(score)
        record = {**capture, 'available_at': capture['captured_at'],
                  'note': 'Final score published in the completed Sky Super 6 round.',
                  'status': 'final', 'score': score}
        evidence(record, official=True)
        results[str(challenge['id'])] = record
    return results


def official_goal(payload, capture):
    challenge = payload['goldenGoalChallenge']
    minute = challenge['time']
    if not challenge['isGoldenGoalScored']:
        minute = None
    elif type(minute) is not int or minute < 1:
        raise ValueError('Unexpected Sky Golden Goal minute')
    return {**capture, 'minute': minute, 'available_at': capture['captured_at'],
            'note': 'Official Golden Goal published in the completed Sky Super 6 round.'}
