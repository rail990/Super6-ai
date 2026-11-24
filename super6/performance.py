"""Audit historical strategy differences without fitting or changing forecasts."""
import argparse
import json
from collections import Counter
from itertools import combinations
from pathlib import Path
from random import Random

from .archive import load_rounds
from .backtest import FIXED_RATES, LABELS, mean, study
from .evidence import timestamp
from .model import distribution, outcome, points, result_probabilities, venue_rates

STRATEGIES = ('expected_points', 'threshold_13', 'fixed_poisson')
ACTUAL_METRICS = ('points', 'exact_score_accuracy', 'correct_result_accuracy',
                  'hit_13', 'calibration_gap', 'brier_13_plus')
METRICS = (*ACTUAL_METRICS, 'expected_points', 'probability_13_plus')


def fixture_audit(fixture, entries, index, deadline):
    actual = fixture['result']['score']
    home, away = venue_rates(fixture)
    models = {
        'venue': (home, away),
        'fixed': FIXED_RATES,
    }
    forecasts = {}
    for name, rates in models.items():
        scores = distribution(*rates)
        forecasts[name] = {'rates': rates, 'wdl': result_probabilities(scores)}
    picks = {}
    for name in STRATEGIES:
        pick = entries[name]['picks'][index]
        picks[name] = {'score': pick, 'points': points(pick, actual)}
    history = fixture['venue_history']
    return {
        'id': fixture.get('id'), 'home': fixture['home'], 'away': fixture['away'],
        'actual': actual, 'forecasts': forecasts, 'picks': picks,
        'history': {
            side: {
                'matches': len(matches),
                'latest_age_days': (deadline - max(timestamp(m['available_at'])
                                                   for m in matches)).days,
                'points_per_game': mean([3 if gf > ga else int(gf == ga)
                                         for gf, ga in (m['score'] for m in matches)]),
            } for side, matches in history.items()
        },
    }


def round_metrics(entry):
    actual = entry['hit_13']
    forecast = entry['probability_13_plus']
    return {
        'points': entry['points'],
        'exact_score_accuracy': entry['exact'] / 6,
        'correct_result_accuracy': entry['correct'] / 6,
        'hit_13': int(actual),
        'calibration_gap': forecast - actual,
        'brier_13_plus': (forecast - actual) ** 2,
        'expected_points': entry['expected_points'],
        'probability_13_plus': forecast,
    }


def paired_intervals(differences, draws, seed, metrics=METRICS):
    """Resample entire paired slates and use empirical 2.5% and 97.5% quantiles."""
    rng = Random(seed)
    count = len(differences)
    samples = {name: [] for name in metrics}
    for _ in range(draws):
        indices = rng.choices(range(count), k=count)
        for name in metrics:
            samples[name].append(mean([differences[i][name] for i in indices]))
    for values in samples.values():
        values.sort()
    return {
        name: {
            'difference': mean([row[name] for row in differences]),
            'interval_95': [values[int(0.025 * (draws - 1))],
                            values[int(0.975 * (draws - 1))]],
        } for name, values in samples.items()
    }


def forecast_profile(fixtures, name):
    predictions = [f['forecasts'][name] for f in fixtures]
    actual = [f['actual'] for f in fixtures]
    return {
        'mean_goals': [mean([p['rates'][side] for p in predictions]) for side in range(2)],
        'actual_mean_goals': [mean([score[side] for score in actual]) for side in range(2)],
        'mean_wdl': [mean([p['wdl'][result] for p in predictions]) for result in range(3)],
        'observed_wdl': [mean([outcome(score) == result for score in actual])
                         for result in range(3)],
    }


def fixture_group(fixtures, first, second):
    return {
        'fixtures': len(fixtures),
        'point_difference': sum(f['picks'][first]['points'] - f['picks'][second]['points']
                                for f in fixtures),
    }


def cohort(rows, draws, seed):
    if not rows:
        return {'round_count': 0}
    rounds = []
    for row in rows:
        item, entries = row['round'], row['strategies']
        deadline = timestamp(item['deadline'])
        rounds.append({
            'round': item['id'], 'source_quality': row['source_quality'],
            'deadline': item['deadline'],
            'strategies': {name: round_metrics(entries[name]) for name in STRATEGIES},
            'fixtures': [fixture_audit(f, entries, index, deadline)
                         for index, f in enumerate(item['fixtures'])],
        })
    fixtures = [fixture for row in rounds for fixture in row['fixtures']]
    comparisons = {}
    for first, second in combinations(STRATEGIES, 2):
        differences = [{name: row['strategies'][first][name] - row['strategies'][second][name]
                        for name in METRICS} for row in rounds]
        round_outcomes = Counter((d['points'] > 0) - (d['points'] < 0) for d in differences)
        away_form = [[], [], []]
        for fixture in fixtures:
            ppg = fixture['history']['away']['points_per_game']
            away_form[min(2, int(ppg))].append(fixture)
        comparisons[f'{first}_minus_{second}'] = {
            'paired_metrics': paired_intervals(differences, draws, seed),
            'rounds_ahead_tied_behind': [round_outcomes[sign] for sign in (1, 0, -1)],
            'different_picks': sum(f['picks'][first]['score'] != f['picks'][second]['score']
                                   for f in fixtures),
            'by_actual_wdl': [
                fixture_group([f for f in fixtures if outcome(f['actual']) == result],
                              first, second) for result in range(3)
            ],
            'by_away_form': {
                label: fixture_group(group, first, second) for label, group in zip(
                    ('below_one_ppg', 'one_to_below_two_ppg', 'at_least_two_ppg'), away_form)
            },
            'by_venue_history_recency': {
                label: fixture_group([
                    f for f in fixtures if any(h['latest_age_days'] > 45
                                               for h in f['history'].values()) == stale
                ], first, second)
                for label, stale in (('over_45_days', True), ('within_45_days', False))
            },
        }
    return {
        'round_count': len(rounds),
        'sides_with_latest_result_over_45_days_old': sum(
            h['latest_age_days'] > 45 for f in fixtures for h in f['history'].values()),
        'pick_wdl_counts': {
            name: [sum(outcome(f['picks'][name]['score']) == result for f in fixtures)
                   for result in range(3)] for name in STRATEGIES
        },
        'summary': {name: {metric: mean([r['strategies'][name][metric] for r in rounds])
                           for metric in METRICS} for name in STRATEGIES},
        'profiles': {name: forecast_profile(fixtures, name) for name in ('venue', 'fixed')},
        'comparisons': comparisons,
        'rounds': rounds,
    }


def investigate(rounds, as_of, draws=10_000, seed=7):
    if draws < 1:
        raise ValueError('At least one bootstrap draw is required')
    evaluated = study(rounds, as_of)
    rows = evaluated['rounds']
    strict = [r for r in rows if r['source_quality'] != 'sky_revised_preview']
    return {
        'as_of': evaluated['as_of'], 'labels': {name: LABELS[name] for name in STRATEGIES},
        'bootstrap_draws': draws, 'bootstrap_seed': seed,
        'full': cohort(rows, draws, seed),
        'exclude_revised': cohort(strict, draws, seed),
        'excluded': evaluated['excluded'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rounds', type=Path, default=Path('data/rounds.json'))
    parser.add_argument('--as-of', required=True, help='ISO 8601 evaluation cutoff with offset')
    args = parser.parse_args()
    result = investigate(load_rounds(args.rounds), timestamp(args.as_of))
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
