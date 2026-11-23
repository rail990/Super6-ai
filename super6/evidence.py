"""Validation for manually reviewed round and research records."""
from datetime import datetime
from math import isfinite
from urllib.parse import urlparse

RESEARCH = ('form', 'venue_form', 'xg', 'xga', 'injuries', 'suspensions',
            'opposition', 'rest', 'odds')
OFFICIAL = {'super6.skysports.com', 'www.skysports.com', 'skysports.com'}


def timestamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError('Timestamps require a timezone')
    return parsed


def number(value, minimum, maximum):
    if type(value) not in (int, float) or not isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f'Expected a number between {minimum} and {maximum}')
    return value


def evidence(record, official=False):
    source = urlparse(record['url'])
    if source.scheme != 'https' or not source.hostname or (official and source.hostname not in OFFICIAL):
        raise ValueError('Evidence requires a valid HTTPS source on the appropriate domain')
    if not record['note'].strip():
        raise ValueError('Evidence requires a source excerpt or review note')
    return timestamp(record['available_at'])


def ready(fixture):
    return set(fixture.get('research', {})) == set(RESEARCH)


def validate(round_data):
    fixtures = round_data['fixtures']
    deadline = timestamp(round_data['deadline'])
    if not round_data['id'].strip() or len(fixtures) != 6:
        raise ValueError('A named round requires exactly six fixtures')
    if evidence(round_data['official'], official=True) > deadline:
        raise ValueError('The official slate must have been available by the deadline')
    seen = set()
    for fixture in fixtures:
        kickoff = timestamp(fixture['kickoff'])
        teams = {fixture[name].strip().casefold() for name in ('home', 'away')}
        if '' in teams or len(teams) != 2 or teams & seen or deadline > kickoff:
            raise ValueError('Invalid fixture, repeated team, or late deadline')
        seen.update(teams)
        research = fixture.get('research')
        if research is not None:
            if set(research) - set(RESEARCH):
                raise ValueError('Unknown research category')
            for category, record in research.items():
                available = evidence(record)
                if available > deadline or available >= kickoff:
                    raise ValueError(f'Late evidence: {category}')
            for category in ('xg', 'xga'):
                if category not in research:
                    continue
                record = research[category]
                for team in ('home', 'away'):
                    number(record[team], 0, 12)
            if 'odds' in research:
                odds = research['odds']['decimal']
                if len(odds) != 3:
                    raise ValueError('Decimal odds must list home win, draw, away win')
                for value in odds:
                    number(value, 1.000001, 10000)
        if 'result' in fixture:
            result = fixture['result']
            if evidence(result) <= kickoff:
                raise ValueError('Result must be published after kickoff')
            score = result['score']
            if len(score) != 2 or any(type(goals) is not int or goals < 0 for goals in score):
                raise ValueError('Expected a verified pair of nonnegative integer scores')
    if 'golden_goal' in round_data:
        result = round_data['golden_goal']
        if evidence(result, official=True) <= min(timestamp(f['kickoff']) for f in fixtures):
            raise ValueError('Golden Goal must be published after the round starts')
        if result['minute'] is not None and (type(result['minute']) is not int or not 1 <= result['minute'] <= 90):
            raise ValueError('Expected a Golden Goal minute from 1 to 90, or null for no goal')
    return round_data
