"""Validation for manually reviewed round and research records."""
import re
from datetime import datetime, timedelta
from math import isfinite
from urllib.parse import urlparse

RESEARCH = ('form', 'venue_form', 'xg', 'xga', 'injuries', 'suspensions',
            'team_news', 'opposition', 'rest', 'odds')
OPTIONAL = {'lineups'}
OFFICIAL = {'super6.skysports.com', 'www.skysports.com', 'skysports.com', 'api.s6.sbgservices.com'}


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
    url = record['url']
    source = urlparse(url)
    if (source.scheme != 'https' or not source.hostname or source.username is not None
            or source.port not in (None, 443) or '\\' in url
            or any(character.isspace() for character in url)
            or (official and source.hostname not in OFFICIAL)
            or (official and source.hostname == 'api.s6.sbgservices.com'
                and not re.fullmatch(r'/v2/round(?:/(?:active|[1-9][0-9]{0,2}))?', source.path))):
        raise ValueError('Evidence requires a valid HTTPS source on the appropriate domain')
    if not record['note'].strip():
        raise ValueError('Evidence requires a source excerpt or review note')
    available = timestamp(record['available_at'])
    if 'captured_at' in record and timestamp(record['captured_at']) < available:
        raise ValueError('Evidence capture cannot precede availability')
    return available


def score_pair(score):
    if not isinstance(score, (list, tuple)) or len(score) != 2 or any(
        type(goals) is not int or not 0 <= goals <= 99 for goals in score
    ):
        raise ValueError('Expected a pair of nonnegative integer scores')


def ready(fixture):
    return set(RESEARCH) <= set(fixture.get('research', {}))


def verified_snapshot(record, deadline):
    if not re.fullmatch(r'[a-f0-9]{64}', record.get('source_sha256', '')):
        raise ValueError('Snapshot requires the SHA-256 of captured source bytes')
    if 'captured_at' not in record:
        raise ValueError('Snapshot requires a capture time')
    captured = timestamp(record['captured_at'])
    if captured >= deadline:
        archive = record.get('archive_url', '')
        evidence({'url': archive, 'available_at': record['available_at'], 'note': record['note']})
        if archive == record['url']:
            raise ValueError('Late capture requires a distinct point-in-time source')
        if ('archived_at' not in record
                or not timestamp(record['available_at']) <= timestamp(record['archived_at']) < deadline):
            raise ValueError('Archive timestamp must prove pre-deadline availability')
    if captured > datetime.now(captured.tzinfo):
        raise ValueError('Evidence capture cannot be in the future')


def validate(round_data):
    fixtures = round_data['fixtures']
    deadline = timestamp(round_data['deadline'])
    if not round_data['id'].strip() or len(fixtures) != 6:
        raise ValueError('A named round requires exactly six fixtures')
    if evidence(round_data['official'], official=True) >= deadline:
        raise ValueError('The official slate must have been available by the deadline')
    if 'confirmed_at' in round_data['official']:
        confirmed = timestamp(round_data['official']['confirmed_at'])
        if (not timestamp(round_data['official']['available_at']) <= confirmed < deadline
                or confirmed > datetime.now(confirmed.tzinfo)):
            raise ValueError('Sky confirmation must be before the deadline')
    ids = [fixture.get('id') for fixture in fixtures]
    if any(identity is not None for identity in ids) and (
        any(type(identity) is not str or not identity.strip() for identity in ids) or len(set(ids)) != 6
    ):
        raise ValueError('Provide six distinct fixture identifiers')
    seen = set()
    for fixture in fixtures:
        kickoff = timestamp(fixture['kickoff'])
        if 'kickoff_source' in fixture:
            evidence({'url': fixture['kickoff_source'], 'available_at': round_data['official']['available_at'],
                      'note': 'Kickoff cross-check'})
        teams = {fixture[name].strip().casefold() for name in ('home', 'away')}
        if '' in teams or len(teams) != 2 or teams & seen or deadline > kickoff:
            raise ValueError('Invalid fixture, repeated team, or late deadline')
        seen.update(teams)
        research = fixture.get('research')
        if research is not None:
            if set(research) - set(RESEARCH) - OPTIONAL:
                raise ValueError('Unknown research category')
            for category, record in research.items():
                available = evidence(record)
                if available >= deadline:
                    raise ValueError(f'Late evidence: {category}')
                if 'captured_at' in record and timestamp(record['captured_at']) >= deadline:
                    verified_snapshot(record, deadline)
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
        if 'stats' in fixture:
            validate_stats(fixture['stats'], deadline)
        if 'venue_history' in fixture:
            history = fixture['venue_history']
            if set(history) != {'home', 'away'}:
                raise ValueError('Venue history needs home and away records')
            for matches in history.values():
                if len(matches) != 5:
                    raise ValueError('Venue history requires five matches per side')
                seen_matches = set()
                for match in matches:
                    available = evidence(match)
                    if available >= deadline:
                        raise ValueError('Venue history includes a result unavailable at the deadline')
                    if not re.fullmatch(r'[a-f0-9]{64}', match['sha256']):
                        raise ValueError('Venue history requires a source-file SHA-256')
                    key = available, match['opponent'].strip().casefold()
                    if not key[1] or key in seen_matches:
                        raise ValueError('Invalid or repeated venue history opponent')
                    seen_matches.add(key)
                    score_pair(match['score'])
        if 'result' in fixture:
            result = fixture['result']
            if result.get('status') != 'final':
                raise ValueError('A scored result requires confirmed final status')
            if evidence(result) < kickoff + timedelta(minutes=90):
                raise ValueError('Final result timestamp is too early')
            score_pair(result['score'])
            if 'first_goal' in result:
                goal = result['first_goal']
                if (not sum(result['score']) or type(goal['minute']) is not int
                        or not 1 <= goal['minute'] <= 90 or evidence(goal, official=True) < kickoff):
                    raise ValueError('Invalid first-goal evidence')
    if 'golden_goal' in round_data:
        result = round_data['golden_goal']
        if evidence(result, official=True) <= min(timestamp(f['kickoff']) for f in fixtures):
            raise ValueError('Golden Goal must be published after the round starts')
        scores = [f['result']['score'] for f in fixtures if 'result' in f]
        any_goals = any(sum(score) for score in scores)
        if result['minute'] is None and (len(scores) != 6 or any_goals):
            raise ValueError('No Golden Goal requires six confirmed goalless results')
        if result['minute'] is not None and len(scores) == 6 and not any_goals:
            raise ValueError('A Golden Goal requires a scored goal')
        if result['minute'] is not None and (type(result['minute']) is not int or not 1 <= result['minute'] <= 90):
            raise ValueError('Expected a Golden Goal minute from 1 to 90, or null for no goal')
    return round_data


def validate_stats(stats, deadline):
    observed = evidence(stats)
    if observed >= deadline or observed > datetime.now(observed.tzinfo):
        raise ValueError('Statistical snapshot must be captured before the deadline')
    if not re.fullmatch(r'[a-f0-9]{64}', stats['sha256']):
        raise ValueError('Statistical snapshot needs a source SHA-256')
    for source in stats.get('sources', []):
        if evidence(source) > observed or not re.fullmatch(r'[a-f0-9]{64}', source['sha256']):
            raise ValueError('Invalid statistical input source')
    for side in ('home', 'away'):
        profile = stats[side]
        recent = profile['recent']['matches']
        for group in ('recent', 'venue'):
            row = profile[group]
            if any(type(row[key]) is not int or row[key] < 0 for key in
                   ('matches', 'won', 'drawn', 'lost', 'goals_for', 'goals_against', 'clean_sheets')):
                raise ValueError('Form statistics must be nonnegative integers')
            if (row['won'] + row['drawn'] + row['lost'] != row['matches']
                    or row['clean_sheets'] > row['matches'] or row['matches'] > recent
                    or row['goals_for'] > 99 * row['matches']
                    or row['goals_against'] > 99 * row['matches']):
                raise ValueError('Form totals are inconsistent')
        ids = profile['match_ids']
        if len(ids) != recent or len(set(ids)) != recent or recent > 6:
            raise ValueError('Invalid recent match coverage')
        if recent:
            if timestamp(profile['latest_available_at']) > observed:
                raise ValueError('Recent result was unavailable at capture')
            number(profile['opposition_ppg'], 0, 3)
        elif profile['latest_available_at'] is not None or profile['opposition_ppg'] is not None:
            raise ValueError('Missing matches cannot support recency or opposition figures')
