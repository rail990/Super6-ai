"""Generate a portable dashboard and run point-in-time evaluation."""
import argparse
import json
import shutil
from pathlib import Path
from datetime import datetime, timezone

from .archive import ROUNDS, candidate_index, load_rounds
from .backtest import study
from .capture import frozen, missing, prematch
from .evidence import ready, timestamp, validate
from .model import forecast, form_rates, points, predict, venue_rates
from .research import MIN_MATCHES

MODEL = 'xg_market'
FIXED = 'fixed_poisson'
VENUE = 'venue_goals'
FORM = 'recent_form'
SNAPSHOTS = Path('data/snapshots')


def first_goal(item):
    if 'golden_goal' in item:
        return item['golden_goal']['minute'], True
    results = [fixture.get('result') for fixture in item['fixtures']]
    if any(not result or (sum(result['score']) and 'first_goal' not in result) for result in results):
        return None, False
    minutes = [result['first_goal']['minute'] for result in results if sum(result['score'])]
    return min(minutes, default=None), True


def evaluate(item, prediction):
    if not all('result' in fixture for fixture in item['fixtures']):
        return None
    values = [points(pick['score'], fixture['result']['score'])
              for pick, fixture in zip(prediction['fixtures'], item['fixtures'])]
    actual, observed = first_goal(item)
    return {
        'points': sum(values), 'exact': values.count(5), 'result_only': values.count(2),
        'hit_13_plus': sum(values) >= 13,
        'golden_goal_error': abs(prediction['golden_goal']['minute'] - actual)
        if actual is not None else None,
        'no_goal_actual': actual is None if observed else None,
    }


def mean(values):
    return sum(values) / len(values)


def summarize(scored):
    if not scored:
        return {'rounds': 0}
    errors = [e['golden_goal_error'] for _, e in scored if e['golden_goal_error'] is not None]
    goal_cases = [(p, e) for p, e in scored if e['no_goal_actual'] is not None]
    forecast_13 = [p['probability_13_plus'] for p, _ in scored]
    bins = [[] for _ in range(5)]
    for probability, (_, evaluation) in zip(forecast_13, scored):
        bins[min(4, int(probability * 5))].append((probability, evaluation['hit_13_plus']))
    return {
        'rounds': len(scored),
        'mean_points': mean([e['points'] for _, e in scored]),
        'exact_score_accuracy': mean([e['exact'] / 6 for _, e in scored]),
        'mean_expected_points': mean([p['expected_points'] for p, _ in scored]),
        'mean_probability_13_plus': mean(forecast_13),
        'hit_rate_13_plus': mean([e['hit_13_plus'] for _, e in scored]),
        'brier_13_plus': mean([(p - e['hit_13_plus'])**2 for p, (_, e) in zip(forecast_13, scored)]),
        'calibration_13_plus': [
            {'lower': index / 5, 'upper': (index + 1) / 5, 'rounds': len(entries),
             'forecast': mean([p for p, _ in entries]), 'observed': mean([hit for _, hit in entries])}
            for index, entries in enumerate(bins) if entries
        ],
        'golden_goal_mae': mean(errors) if errors else None,
        'golden_goal_minute_rounds': len(errors),
        'no_goal_brier': mean([(p['golden_goal']['no_goal'] - e['no_goal_actual'])**2
                               for p, e in goal_cases]) if goal_cases else None,
    }


def stale(key, record, cutoff):
    days = 2 if key == 'odds' else 7 if key in ('injuries', 'lineups', 'team_news', 'suspensions') else 45
    return (cutoff - timestamp(record['available_at'])).days >= days


def quality(item):
    cutoff = timestamp(item['deadline'])
    flags = []
    for fixture in item['fixtures']:
        stats = fixture.get('stats')
        for side in ('home', 'away'):
            profile = stats[side] if stats else None
            if not profile or profile['recent']['matches'] < MIN_MATCHES:
                flags.append(f"{fixture[side]} has fewer than {MIN_MATCHES} recent results.")
            elif (cutoff - timestamp(profile['latest_available_at'])).days >= 45:
                flags.append(f"{fixture[side]} has no result in the last 45 days.")
        for key, record in fixture.get('research', {}).items():
            if stale(key, record, cutoff):
                flags.append(f"{fixture['home']} vs {fixture['away']} has stale {key} evidence.")
    return flags


def report(rounds, baseline, snapshots=SNAPSHOTS, as_of=None):
    rows = []
    scored = {name: [] for name in (MODEL, FIXED, VENUE, FORM)}
    comparison_models = (MODEL, FIXED, VENUE)
    paired = {name: [] for name in scored}
    seen = set()
    for item in sorted(rounds, key=lambda row: timestamp(row['deadline'])):
        validate(item)
        if item['id'] in seen:
            raise ValueError(f"Duplicate round: {item['id']}")
        seen.add(item['id'])
        fixtures = item['fixtures']
        cutoff = timestamp(item['deadline'])
        has_snapshot = frozen(item, snapshots)
        archived = has_snapshot and all(
            ready(f) and not any(stale(key, record, cutoff) for key, record in f['research'].items())
            for f in fixtures
        )
        kickoffs = [f['kickoff'] for f in fixtures]
        predictions = {FIXED: forecast([((1.5, 1.1), None)] * 6, kickoffs=kickoffs)}
        if all('venue_history' in fixture for fixture in fixtures):
            predictions[VENUE] = forecast([(venue_rates(fixture), None) for fixture in fixtures],
                                          kickoffs=kickoffs)
        flags = quality(item)
        can_use_form = 'confirmed_at' in item['official'] and all(
            f.get('id') and 'stats' in f and all(
                f['stats'][side]['recent']['matches'] >= MIN_MATCHES
                and (timestamp(item['deadline']) - timestamp(f['stats'][side]['latest_available_at'])).days < 45
                for side in ('home', 'away'))
            for f in fixtures
        )
        if can_use_form:
            inputs = [form_rates({
                'stats': f['stats'],
                'research': {key: record for key, record in f.get('research', {}).items()
                             if has_snapshot and not stale(key, record, cutoff)},
            }) for f in fixtures]
            predictions[FORM] = forecast(inputs, kickoffs=kickoffs)
        if archived:
            predictions[MODEL] = predict(prematch(item))
        evaluations = {name: evaluate(item, pred) for name, pred in predictions.items()}
        comparison_round = all(evaluations.get(name) is not None for name in comparison_models)
        for name, evaluation in evaluations.items():
            if evaluation is not None:
                scored[name].append((predictions[name], evaluation))
                if comparison_round:
                    paired[name].append((predictions[name], evaluation))
        rows.append({
            'round': item, 'prediction': predictions.get(MODEL), 'evaluation': evaluations.get(MODEL),
            'benchmarks': {name: {'prediction': predictions[name], 'evaluation': evaluations[name]}
                           for name in (FORM, FIXED, VENUE) if name in predictions},
            'recommended_model': MODEL if archived else FORM if can_use_form else None,
            'quality_flags': flags, 'missing_research': missing(item), 'snapshot_frozen': has_snapshot,
            'derived_goal': first_goal(item)[0] if 'golden_goal' not in item else None,
        })
    return {'baseline': baseline, 'rounds': rows, 'backtest': summarize(scored[MODEL]),
            'strategy_backtest': study(rounds, as_of or datetime.now(timezone.utc)),
            'historical': {name: summarize(entries) for name, entries in scored.items()},
            'matched_backtest': {name: summarize(entries) for name, entries in paired.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rounds', type=Path, default=Path('data/rounds.json'))
    parser.add_argument('--output', type=Path, default=Path('dist'))
    parser.add_argument('--snapshots', type=Path, default=SNAPSHOTS)
    parser.add_argument('--backtest-as-of', type=timestamp, help='Optional ISO 8601 evaluation cutoff')
    args = parser.parse_args()
    data = report(load_rounds(args.rounds), json.loads(Path('data/baseline.json').read_text()),
                  args.snapshots, args.backtest_as_of)
    if args.rounds.resolve() == ROUNDS.resolve():
        data['archive_candidates'] = candidate_index()
    args.output.mkdir(parents=True, exist_ok=True)
    for path in Path('dashboard').iterdir():
        shutil.copy2(path, args.output)
    (args.output / 'report.json').write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')
    print(f"Built {len(data['rounds'])} rounds, including "
          f"{len(data['strategy_backtest']['rounds'])} goals-only historical reconstructions. "
          f"Scored xG-and-market rounds: {data['backtest']['rounds']}.")


if __name__ == '__main__':
    main()
