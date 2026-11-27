"""Capture free provider results and derive point-in-time team research."""
import argparse
import csv
import hashlib
import io
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

from .evidence import evidence, score_pair, timestamp, validate

FOOTBALL_DATA = 'https://api.football-data.org/v4'
OPEN_MATCHDAY = 'https://raw.githubusercontent.com/oladeeayo/open-matchday/'
WINDOW = 6
MIN_MATCHES = 3


def completed(provider, raw):
    if provider == 'football-data.org':
        for row in json.loads(raw)['matches']:
            if row['status'] != 'FINISHED':
                continue
            scores = row['score']['fullTime']
            if row['score']['duration'] != 'REGULAR' or None in (scores['home'], scores['away']):
                continue
            yield (str(row['id']), row['competition']['code'], timestamp(row['utcDate']) + timedelta(hours=3),
                   row['homeTeam']['name'], row['awayTeam']['name'], [scores['home'], scores['away']])
    elif provider == 'open-matchday':
        for row in csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))):
            if row['ft_result'] not in ('H', 'D', 'A'):
                continue
            # Exclude the whole match date if source publication timing is uncertain.
            local = datetime.fromisoformat(row['date']).replace(tzinfo=ZoneInfo('Europe/Paris'))
            safe_date = local + timedelta(days=1)
            yield (f"{row['date']}:{row['home']}:{row['away']}", None, safe_date,
                   row['home'], row['away'], [int(row['ft_home']), int(row['ft_away'])])
    else:
        raise ValueError('Unknown source provider')


def capture(provider, raw, url, observed_at, competition=None):
    observed = timestamp(observed_at)
    reference = {'url': url, 'available_at': observed_at, 'note': 'Captured completed match results'}
    evidence(reference)
    if observed > datetime.now(timezone.utc):
        raise ValueError('Capture time cannot be in the future')
    matches = []
    seen = set()
    for match_id, league, available, home, away, score in completed(provider, raw):
        score_pair(score)
        if available > observed:
            continue
        key = (league or competition, match_id)
        if not key[0]:
            raise ValueError('A competition code is required for CSV data')
        if key in seen:
            raise ValueError(f'Duplicate provider match: {key}')
        seen.add(key)
        matches.append({'id': match_id, 'competition': key[0], 'available_at': available.isoformat(),
                        'home': home, 'away': away, 'score': score})
    return {**reference, 'provider': provider, 'sha256': hashlib.sha256(raw).hexdigest(),
            'matches': matches}


def summary(rows):
    scores = [(goals, conceded) for _, goals, conceded, _ in rows]
    return {'matches': len(rows), 'won': sum(g > c for g, c in scores),
            'drawn': sum(g == c for g, c in scores), 'lost': sum(g < c for g, c in scores),
            'goals_for': sum(g for g, _ in scores), 'goals_against': sum(c for _, c in scores),
            'clean_sheets': sum(c == 0 for _, c in scores)}


def enrich(item, datasets, aliases=None):
    validate(item)
    aliases = aliases or {}
    cutoff = timestamp(item['deadline'])
    if isinstance(datasets, dict):
        datasets = [datasets]
    if not datasets or len({d['provider'] for d in datasets}) != 1:
        raise ValueError('Use captures from a single provider per round')
    observed = max(evidence(dataset) for dataset in datasets)
    if observed >= cutoff or observed > datetime.now(timezone.utc):
        raise ValueError('Results feed must have been captured before the round deadline')
    references = [{key: dataset[key] for key in ('url', 'available_at', 'note', 'provider', 'sha256')}
                  for dataset in datasets]
    teams = defaultdict(list)
    standings = defaultdict(list)
    matches = {}
    for dataset in datasets:
        for match in dataset['matches']:
            if timestamp(match['available_at']) > timestamp(dataset['available_at']):
                raise ValueError('Results feed contains a match unavailable at capture')
            score_pair(match['score'])
            key = (match['competition'], match['id'])
            if key in matches and matches[key] != match:
                raise ValueError('Two captures disagree about a match')
            matches[key] = match
    for match in matches.values():
        for side, other, index in (('home', 'away', 0), ('away', 'home', 1)):
            goals, conceded = match['score'][index], match['score'][1-index]
            team = match[side]
            teams[team].append((match, goals, conceded, side))
            standings[match['competition'], team].append((goals, conceded))
    for fixture in item['fixtures']:
        profiles = {}
        for side in ('home', 'away'):
            team = aliases.get(fixture[side], fixture[side])
            recent = sorted(teams[team], key=lambda row: timestamp(row[0]['available_at']),
                            reverse=True)[:WINDOW]
            venues = [row for row in recent if row[3] == side]
            strengths = []
            for match, _, _, venue in recent:
                opponent = match['away' if venue == 'home' else 'home']
                games = standings[match['competition'], opponent]
                strengths.append(sum(3 if g > c else 1 if g == c else 0 for g, c in games) / len(games))
            profiles[side] = {'recent': summary(recent), 'venue': summary(venues),
                              'opposition_ppg': sum(strengths) / len(strengths) if strengths else None,
                              'match_ids': [row[0]['id'] for row in recent],
                              'latest_available_at': recent[0][0]['available_at'] if recent else None}
        fixture['stats'] = {**references[0], 'available_at': observed.isoformat(), **profiles}
        if len(references) > 1:
            fixture['stats']['sources'] = references
    return validate(item)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        return None


def api_data(competition, start, end, fixtures=False):
    if not competition.isascii() or not competition.isalnum():
        raise ValueError('Use a football-data.org competition code')
    token = os.environ.get('FOOTBALL_DATA_TOKEN')
    if not token:
        raise ValueError('Set FOOTBALL_DATA_TOKEN to the registered free-tier API key')
    datetime.strptime(start, '%Y-%m-%d')
    datetime.strptime(end, '%Y-%m-%d')
    query = {'dateFrom': start, 'dateTo': end}
    if not fixtures:
        query['status'] = 'FINISHED'
    url = f'{FOOTBALL_DATA}/competitions/{competition}/matches?' + urlencode(query)
    opener = build_opener(NoRedirect())
    with opener.open(Request(url, headers={'X-Auth-Token': token}), timeout=30) as response:
        raw = response.read()
    observed = datetime.now(timezone.utc).isoformat()
    if fixtures:
        return {'url': url, 'available_at': observed,
                'note': 'General schedule for cross-checking only. Sky selects the Super 6 fixtures.',
                'matches': [
                    {'id': str(row['id']), 'kickoff': row['utcDate'], 'status': row['status'],
                     'home': row['homeTeam']['name'], 'away': row['awayTeam']['name']}
                    for row in json.loads(raw)['matches']
                ]}
    return capture('football-data.org', raw, url, observed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    api = sub.add_parser('api', help='One authenticated request to the official free API')
    api.add_argument('competition')
    api.add_argument('start')
    api.add_argument('end')
    api.add_argument('--fixtures', action='store_true', help='General fixture cross-check only')
    csv_parser = sub.add_parser('csv', help='Normalize a downloaded published open-matchday results CSV')
    csv_parser.add_argument('file', type=Path)
    csv_parser.add_argument('url')
    csv_parser.add_argument('competition')
    csv_parser.add_argument('--observed-at', required=True, help='Actual download time in ISO 8601')
    summary_parser = sub.add_parser('enrich', help='Attach available form and venue evidence to a Sky slate')
    summary_parser.add_argument('round', type=Path)
    summary_parser.add_argument('datasets', type=Path, nargs='+')
    summary_parser.add_argument('--aliases', type=Path)
    args = parser.parse_args()
    if args.command == 'api':
        result = api_data(args.competition, args.start, args.end, args.fixtures)
    elif args.command == 'csv':
        if not args.url.startswith(OPEN_MATCHDAY):
            parser.error('Use the canonical open-matchday published CSV URL')
        result = capture('open-matchday', args.file.read_bytes(), args.url, args.observed_at, args.competition)
    else:
        result = enrich(json.loads(args.round.read_text()), [json.loads(path.read_text()) for path in args.datasets],
                        json.loads(args.aliases.read_text()) if args.aliases else None)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
