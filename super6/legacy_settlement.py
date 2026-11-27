"""Compare Round 18's preserved forecasts with the completed Sky scorecard."""
import argparse
import hashlib
import json
from pathlib import Path

from .evidence import timestamp
from .live import encode, publish, sky_capture
from .report import FIXED, FORM, evaluate, report
from .sky_history import historical_record

ROUNDS = Path('data/rounds.json')
EXPECTATIONS = Path('data/stage9/round18-expectations.json')
ROUND_ID = '2026–27 Round 18'
ALIASES = {'Man City': 'Manchester City', 'PSV': 'PSV Eindhoven',
           'Sporting': 'Sporting CP', 'Man Utd': 'Manchester United', 'PSG': 'Paris Saint-Germain'}


def expectations():
    raw = ROUNDS.read_bytes()
    item = next(row for row in json.loads(raw) if row['id'] == ROUND_ID)
    row = report([item], {})['rounds'][0]
    return {'archive_sha256': hashlib.sha256(raw).hexdigest(), 'round_id': ROUND_ID,
            'deadline': item['deadline'], 'fixtures': [
                {key: fixture[key] for key in ('home', 'away', 'kickoff')}
                for fixture in item['fixtures']],
            'models': {key: {name: prediction[name] for name in
                             ('expected_points', 'probability_13_plus', 'probability_all_exact')}
                       | {'golden_goal': {'minute': prediction['golden_goal']['minute']}}
                       | {'fixtures': [{'score': fixture['score']} for fixture in prediction['fixtures']]}
                       for key in (FORM, FIXED) for prediction in [row['benchmarks'][key]['prediction']]}}


def settle(payload, capture, baseline):
    if payload['id'] != 18 or payload['season'] != '2026-27':
        raise ValueError('Expected Sky 2026–27 Round 18')
    if hashlib.sha256(ROUNDS.read_bytes()).hexdigest() != baseline['archive_sha256']:
        raise ValueError('Round 18 source archive has changed')
    card = historical_record(payload, capture)
    if timestamp(card['deadline']) != timestamp(baseline['deadline']):
        raise ValueError('Sky deadline differs from the preserved round')
    def key(fixture):
        return tuple(ALIASES.get(fixture[side], fixture[side]) for side in ('home', 'away')) + (
            timestamp(fixture['kickoff']),)
    actual = {key(f): f['score'] for f in card['fixtures']}
    if set(actual) != {key(f) for f in baseline['fixtures']}:
        raise ValueError('Sky slate differs from the preserved round')
    evaluated = {'fixtures': [{'result': {'score': actual[key(f)]}} for f in baseline['fixtures']],
                 'golden_goal': {'minute': card['golden_goal']}}
    comparisons = {}
    for name, prediction in baseline['models'].items():
        scored = evaluate(evaluated, prediction)
        expected = prediction['expected_points']
        comparisons[name] = {**scored, 'expected_points': expected,
                             'actual_minus_expected': scored['points'] - expected,
                             'forecast_13_plus': prediction['probability_13_plus']}
    return {'scorecard': card, 'expectations_sha256': hashlib.sha256(encode(baseline)).hexdigest(),
            'comparisons': comparisons}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=EXPECTATIONS.with_name('round18-settlement.json'))
    args = parser.parse_args()
    payload, capture = sky_capture(18, args.sources)
    result = settle(payload, capture, json.loads(EXPECTATIONS.read_bytes()))
    publish(args.output, result)
    print(args.output)


if __name__ == '__main__':
    main()
