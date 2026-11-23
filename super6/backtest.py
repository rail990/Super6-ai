"""Reconstruct historical venue forecasts and evaluate strategies chronologically."""
import argparse
import json
from itertools import product
from math import log, prod
from pathlib import Path

from .evidence import evidence, timestamp, validate
from .model import distribution, exact_points, outcome, points, result_probabilities, venue_rates

STRATEGIES = ('modal', 'expected_points', 'threshold_13')
BENCHMARKS = ('fixed_poisson', 'fixed_draw')
LABELS = {
    'modal': 'Most likely exact scores', 'expected_points': 'Maximum expected points',
    'threshold_13': 'Maximum chance of 13+', 'fixed_poisson': 'Fixed-rate Poisson',
    'fixed_draw': 'Always 1–1',
}
RHO_GRID = [i / 1000 for i in range(-120, 121)]
MIN_TRAINING_MATCHES = 6


def choice_metrics(scores, outcomes, picks):
    weights = [(model.get(tuple(pick), 0.0), chances[outcome(pick)])
               for model, chances, pick in zip(scores, outcomes, picks, strict=True)]
    return {
        'expected_points': sum(3 * exact + 2 * correct for exact, correct in weights),
        'probability_13_plus': sum(exact_points(weights)[13:]),
        'probability_all_exact': prod(exact for exact, _ in weights),
    }


def strategies(scores):
    outcomes = list(map(result_probabilities, scores))
    choices = [
        [max((score for score in model if outcome(score) == result), key=model.get)
         for result in range(3)] for model in scores
    ]
    modal = [max(model, key=model.get) for model in scores]
    expected = [max(picks, key=lambda score: 3 * model[score] + 2 * chances[outcome(score)])
                for model, chances, picks in zip(scores, outcomes, choices)]
    # For a given result category a more likely exact pick shifts mass from 2 to 5.
    # Therefore only the best score of each category can be needed for the threshold.
    threshold = max(product(*choices), key=lambda picks: (
        (metrics := choice_metrics(scores, outcomes, picks))['probability_13_plus'],
        metrics['expected_points'], metrics['probability_all_exact'],
    ))
    return {name: (list(picks), choice_metrics(scores, outcomes, picks))
            for name, picks in zip(STRATEGIES, (modal, expected, threshold))}


def adjusted(rates, rho):
    home, away = rates
    factors = {(0, 0): 1 - home * away * rho, (0, 1): 1 + home * rho,
               (1, 0): 1 + away * rho, (1, 1): 1 - rho}
    if min(factors.values()) <= 0:
        return None
    original = distribution(home, away)
    values = {score: p * factors.get(score, 1) for score, p in original.items()}
    total = sum(values.values())
    return {score: p / total for score, p in values.items()}


def fit_rho(training):
    if len(training) < MIN_TRAINING_MATCHES:
        return None
    best = (float('inf'), 0.0, 0.0)
    precomputed = [(rates, score) for rates, score in training]
    # Independent-Poisson factors are constant across rho. Minimize the
    # contribution of the four affected outcomes on prior completed matches.
    for rho in RHO_GRID:
        likelihood = 0.0
        for (home, away), score in precomputed:
            factors = {(0, 0): 1 - home * away * rho, (0, 1): 1 + home * rho,
                       (1, 0): 1 + away * rho, (1, 1): 1 - rho}
            if min(factors.values()) <= 0:
                break
            likelihood -= log(factors.get(tuple(score), 1))
        else:
            best = min(best, (likelihood, abs(rho), rho))
    return best[2]


def score_entry(picks, actual, probabilities):
    scores = [points(pick, result) for pick, result in zip(picks, actual, strict=True)]
    return {
        **probabilities, 'picks': picks, 'points': sum(scores), 'exact': scores.count(5),
        'correct': scores.count(5) + scores.count(2), 'hit_13': sum(scores) >= 13,
    }


def mean(values):
    return sum(values) / len(values)


def summarize(rows):
    if not rows:
        return {'rounds': 0}
    bins = [[] for _ in range(5)]
    for row in rows:
        p = row['probability_13_plus']
        bins[min(4, int(p * 5))].append(row)
    return {
        'rounds': len(rows), 'average_points': mean([r['points'] for r in rows]),
        'exact_score_accuracy': mean([r['exact'] / 6 for r in rows]),
        'correct_result_accuracy': mean([r['correct'] / 6 for r in rows]),
        'observed_13_plus': mean([r['hit_13'] for r in rows]),
        'predicted_13_plus': mean([r['probability_13_plus'] for r in rows]),
        'brier_13_plus': mean([(r['probability_13_plus'] - r['hit_13']) ** 2 for r in rows]),
        'calibration': [
            {'lower': i / 5, 'upper': (i + 1) / 5, 'rounds': len(bucket),
             'predicted': mean([r['probability_13_plus'] for r in bucket]),
             'observed': mean([r['hit_13'] for r in bucket])}
            for i, bucket in enumerate(bins) if bucket
        ],
    }


def eligible(item, as_of):
    deadline = timestamp(item['deadline'])
    if deadline >= as_of:
        return 'Round has not reached its deadline'
    if 'deadline_evidence' not in item:
        return 'Official entry deadline source missing'
    if evidence(item['deadline_evidence'], official=True) >= deadline:
        raise ValueError('Deadline source must predate the official deadline')
    for fixture in item['fixtures']:
        result = fixture.get('result')
        if not result or evidence(result, official=True) > as_of:
            return 'All six dated final results are required'
        if 'venue_history' not in fixture:
            return 'Pre-deadline venue results missing for one or more fixtures'
    return None


def study(rounds, as_of):
    rows = []
    excluded = []
    prior = []
    cohorts = {name: [] for name in (*STRATEGIES, *BENCHMARKS)}
    comparisons = []
    seen = set()
    for item in sorted(rounds, key=lambda r: (timestamp(r['deadline']), r['id'])):
        validate(item)
        if item['id'] in seen:
            raise ValueError(f"Duplicate historical round: {item['id']}")
        seen.add(item['id'])
        if reason := eligible(item, as_of):
            excluded.append({'round': item['id'], 'reason': reason})
            continue
        fixtures = item['fixtures']
        actual = [f['result']['score'] for f in fixtures]
        rates = [venue_rates(f) for f in fixtures]
        base = [distribution(*pair) for pair in rates]
        entries = strategies(base)
        fixed = [distribution(1.5, 1.1)] * 6
        entries['fixed_poisson'] = strategies(fixed)['expected_points']
        draw = [(1, 1)] * 6
        entries['fixed_draw'] = (draw, choice_metrics(base, list(map(result_probabilities, base)), draw))
        results = {name: score_entry(picks, actual, metrics) for name, (picks, metrics) in entries.items()}
        for name, entry in results.items():
            cohorts[name].append(entry)

        deadline = timestamp(item['deadline'])
        training = [match for available, matches in prior if available < deadline for match in matches]
        rho = fit_rho(training)
        if rho is not None:
            models = [adjusted(pair, rho) for pair in rates]
            if all(model is not None for model in models):
                tuned_picks, tuned_metrics = strategies(models)['expected_points']
                adjusted_result = score_entry(tuned_picks, actual, tuned_metrics)
                original_result = results['expected_points']

                def log_loss(distributions):
                    return -mean([log(max(model.get(tuple(score), 0.0), 1e-15))
                                  for model, score in zip(distributions, actual)])

                comparisons.append({
                    'round': item['id'], 'training_matches': len(training), 'rho': rho,
                    'grid_boundary': abs(rho) == RHO_GRID[-1],
                    'original_log_loss': log_loss(base), 'adjusted_log_loss': log_loss(models),
                    'original_points': original_result['points'], 'adjusted_points': adjusted_result['points'],
                    'original_brier': (original_result['probability_13_plus'] - original_result['hit_13']) ** 2,
                    'adjusted_brier': (adjusted_result['probability_13_plus'] - adjusted_result['hit_13']) ** 2,
                })
        prior.append((max(timestamp(f['result']['available_at']) for f in fixtures),
                      list(zip(rates, actual, strict=True))))
        rows.append({'round': item, 'strategies': results})
    return {
        'protocol': 'venue-results-reconstruction-v1', 'as_of': as_of.isoformat(),
        'rounds': rows, 'excluded': excluded, 'labels': LABELS,
        'summary': {name: summarize(entries) for name, entries in cohorts.items()},
        'dixon_coles': comparisons,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rounds', type=Path, default=Path('data/rounds.json'))
    parser.add_argument('--as-of', required=True, help='ISO 8601 evaluation cutoff with offset')
    args = parser.parse_args()
    print(json.dumps(study(json.loads(args.rounds.read_text()), timestamp(args.as_of)),
                     indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
