"""Refresh Round 19 league evidence and generate separate research forecasts."""
import argparse
import csv
import io
import json
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean

from .archive import load_rounds
from .backtest import FIXED_RATES, adjusted, eligible, fit_rho
from .evidence import timestamp
from .experiments import PROTOCOL, candidate_rates, context
from .live import collect_source, now, publish, sky_capture, source_bytes
from .model import forecast, venue_rates
from .sky import slate
from .sky_history import ARCHIVE
from .venue import UK, attach, load

FEED = 'https://football-data.co.uk/mmz4281/2627/E0.csv'
ALIASES = {'Spurs': 'Tottenham', 'Man Utd': 'Man United'}


def matching_scores(feed, cards, captured):
    scores = {(available.date(), home, away): score
              for available, home, away, score in feed['matches'] if available < captured}
    checked = 0
    for card in cards:
        for fixture in card['fixtures']:
            if fixture.get('competition') != 'Premier League':
                continue
            date = timestamp(fixture['kickoff']).astimezone(UK).date() + timedelta(days=1)
            key = (date, *(ALIASES.get(fixture[side], fixture[side]) for side in ('home', 'away')))
            if key not in scores:
                continue
            if tuple(fixture['score']) != scores[key]:
                raise ValueError(f'League score differs from Sky for {key}')
            checked += 1
    if checked == 0:
        raise ValueError('League score source has no verified overlap with Sky')
    return checked


def build(item, source, directory, market):
    observed = timestamp(source['captured_at'])
    if observed >= timestamp(item['deadline']):
        raise ValueError('Research source was captured after the deadline')
    raw = source_bytes(directory, source['source_sha256'])
    feed = load(directory / source['source_sha256'], source['url'])
    checks = matching_scores(feed, json.loads(ARCHIVE.read_text()), observed)
    feed['matches'] = [match for match in feed['matches'] if match[0] < observed]
    attach(item, [feed], ALIASES)
    csv_rows = list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
    protocol = json.loads(PROTOCOL.read_text())
    params = protocol['candidates']
    names = tuple(params)
    inputs = {name: [] for name in names}
    evidence_rows = []
    for fixture in item['fixtures']:
        details = context(fixture, {source['url']: feed}, observed, source['url'],
                          params['competition_shrinkage']['minimum_competition_matches'])
        if details is None:
            raise ValueError('Incomplete opponent strength or league averages')
        averages, strengths = details
        base = venue_rates(fixture)
        for name, rates in candidate_rates(fixture, base, averages, strengths, params).items():
            inputs[name].append((rates, None))
        inputs['dixon_coles'].append((base, None))
        xg = {}
        for side, prefix, letter in (('home', 'HomeTeam', 'H'), ('away', 'AwayTeam', 'A')):
            team = ALIASES.get(fixture[side], fixture[side])
            goals = [row for row in csv_rows if row.get('FTR') in ('H','D','A') and row[prefix] == team
                     and datetime.strptime(row['Date'], '%d/%m/%Y').date() < observed.date()]
            goals.sort(key=lambda row: datetime.strptime(row['Date'], '%d/%m/%Y'), reverse=True)
            selected = goals[:5]
            against = 'A' if letter == 'H' else 'H'
            xg[side] = {'xg': mean(float(r[letter+'xG']) for r in selected),
                        'xga': mean(float(r[against+'xG']) for r in selected), 'matches': len(selected)}
        quote = market[fixture['id']]
        implied = [1 / price for price in quote['decimal']]
        evidence_rows.append({'fixture': fixture['id'], 'opponent_ppg': strengths, 'venue_xg': xg,
                              'market': {**quote, 'normalized_1x2': [p / sum(implied) for p in implied]},
                              'venue_history': fixture['venue_history']})
    training = []
    for training_round in load_rounds():
        if (training_round.get('source_quality') not in protocol['excluded_source_quality']
                and eligible(training_round, observed) is None
                and all(timestamp(f['result']['available_at']) < observed for f in training_round['fixtures'])):
            training.extend((venue_rates(f), f['result']['score']) for f in training_round['fixtures'])
    if len(training) < params['dixon_coles']['minimum_training_matches']:
        raise ValueError('Insufficient strictly prior Dixon–Coles training data')
    rho = fit_rho(training)
    kicks = [f['kickoff'] for f in item['fixtures']]
    results = {'fixed_poisson': forecast([(FIXED_RATES, None)] * 6, kickoffs=kicks)}
    for name, values in inputs.items():
        distributions = [adjusted(pair, rho) for pair, _ in values] if name == 'dixon_coles' else None
        if distributions is not None and any(scores is None for scores in distributions):
            continue
        results[name] = forecast(values, kickoffs=kicks, score_distributions=distributions)
    return {'round_id': item['id'], 'deadline': item['deadline'], 'official': item['official'],
            'league_source': source, 'sky_scores_cross_checked': checks, 'fixtures': evidence_rows,
            'dixon_coles': {'rho': rho, 'training_matches': len(training)},
            'main_model_blocker': 'Fresh verified availability and complete reviewed market-model evidence required.',
            'models': results, 'timing_note': 'Dixon–Coles Golden Goal timing uses its underlying Poisson rates.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--market-preview', type=Path, default=Path('data/upcoming-sky.json'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--freeze', action='store_true',
                        help='Record the eligible research forecasts separately from production')
    args = parser.parse_args()
    payload, captured = sky_capture(19, args.sources)
    item = slate(payload, captured)
    preview = json.loads(args.market_preview.read_text())
    if (item['id'] != 'Sky 2026-27 Round 19' or item['id'] != preview['id']
            or [(f['id'], f['home'], f['away'], f['kickoff']) for f in item['fixtures']] != [
                (f['id'], f['home'], f['away'], f['kickoff']) for f in preview['fixtures']]):
        parser.error('Round or slate changed since the research preview')
    if payload['status'] not in ('open', 'future'):
        parser.error('Sky must publish a pre-entry slate to generate predictions')
    result = build(item, collect_source(FEED, args.sources), args.sources,
                   {f['id']: f['research_preview']['market'] for f in preview['fixtures']})
    result['status'] = 'frozen' if args.freeze else 'draft'
    result['sky_status_at_capture'] = payload['status']
    if args.freeze:
        result['frozen_at'] = now().isoformat()
    publish(args.output, result, before=timestamp(item['deadline']))
    print(args.output)


if __name__ == '__main__':
    main()
