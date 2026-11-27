"""Run the preregistered venue-model experiments on later, paired rounds."""
import argparse
import json
from collections import defaultdict
from math import exp, log
from pathlib import Path

from .archive import REVIEW, load_rounds, score_feed, verified_result
from .backtest import FIXED_RATES, adjusted, choice_metrics, eligible, fit_rho, score_entry, summarize
from .evidence import timestamp, validate
from .model import distribution, outcome, result_probabilities, venue_rates
from .performance import paired_intervals

PROTOCOL = Path('data/experiment-protocol.json')
BASE = 'venue_goals'
FIXED = 'fixed_poisson'


def context(fixture, sources, cutoff, competition, minimum):
    """Use the reviewed local score feeds, with the archive's availability bounds."""
    feed = sources.get(competition)
    if feed is None:
        return None
    prior = [row for row in feed['matches'] if row[0] < cutoff]
    if len(prior) < minimum:
        return None
    averages = tuple(sum(row[3][i] for row in prior) / len(prior) for i in range(2))
    strengths = {}
    for side, history in fixture['venue_history'].items():
        ppg = []
        for match in history:
            original = sources.get(match['url'])
            if original is None or original['sha256'] != match['sha256']:
                return None
            team = match['opponent']
            scores = [score if home == team else score[::-1]
                      for available, home, away, score in original['matches']
                      if available < cutoff and team in (home, away)]
            if not scores:
                return None
            ppg.append(sum(3 if a > b else int(a == b) for a, b in scores) / len(scores))
        strengths[side] = sum(ppg) / len(ppg)
    return averages, strengths


def candidate_rates(fixture, rates, averages, strengths, params):
    home, away = rates
    midpoint = (home + away) / 2
    retained = params['reduced_home_advantage']['retained_home_rate_gap']
    adjustment = params['opponent_adjusted_form']
    shift = adjustment['log_rate_per_ppg']
    center = adjustment['opponent_ppg_center']
    # Tougher prior opponents imply stronger attack and defence at equal observed form.
    strength_gap = (strengths['home'] - center) - (strengths['away'] - center)
    equivalents = params['competition_shrinkage']['prior_match_equivalents']
    own, other = (fixture['venue_history'][side] for side in ('home', 'away'))
    sample = len(own) + len(other)
    goals = (
        sum(match['score'][0] for match in own) + sum(match['score'][1] for match in other),
        sum(match['score'][0] for match in other) + sum(match['score'][1] for match in own),
    )
    return {
        'reduced_home_advantage': tuple(midpoint + retained * (rate - midpoint) for rate in rates),
        'away_goal_lift': (home, away * params['away_goal_lift']['away_rate_multiplier']),
        'opponent_adjusted_form': (home * exp(shift * strength_gap), away * exp(-shift * strength_gap)),
        'competition_shrinkage': tuple((count + equivalents * prior) / (sample + equivalents)
                                       for count, prior in zip(goals, averages, strict=True)),
    }


def score_models(models, actual):
    outcomes = list(map(result_probabilities, models))
    picks = [max(model, key=lambda pick: 3 * model[pick] + 2 * chances[outcome(pick)])
             for model, chances in zip(models, outcomes, strict=True)]
    row = score_entry(picks, actual, choice_metrics(models, outcomes, picks))
    row['log_loss'] = -sum(log(max(model.get(tuple(score), 0.0), 1e-15))
                           for model, score in zip(models, actual, strict=True)) / 6
    return row


def study(rounds, as_of, sources=None, competitions=None, protocol=None):
    if protocol is None:
        protocol = json.loads(PROTOCOL.read_text())
    sources, competitions = sources or {}, competitions or {}
    params = protocol['candidates']
    start = timestamp(protocol['holdout_deadline_from'])
    minimum = protocol['minimum_holdout_rounds']
    required_matches = params['competition_shrinkage']['minimum_competition_matches']
    prior, rows, excluded = [], [], []
    for item in sorted(rounds, key=lambda row: (timestamp(row['deadline']), row['id'])):
        validate(item)
        if eligible(item, as_of) or item.get('source_quality') in protocol['excluded_source_quality']:
            continue
        cutoff = timestamp(item['deadline'])
        fixtures = item['fixtures']
        rates = [venue_rates(fixture) for fixture in fixtures]
        actual = [fixture['result']['score'] for fixture in fixtures]
        training = [game for available, games in prior if available < cutoff for game in games]
        prior.append((max(verified_result(f['result']) for f in fixtures), list(zip(rates, actual, strict=True))))
        if cutoff < start:
            continue
        round_sources = competitions.get(item['id'], {})
        contexts = [context(fixture, sources, cutoff, round_sources.get(fixture['home']), required_matches)
                    for fixture in fixtures]
        if any(entry is None for entry in contexts) or len(training) < params['dixon_coles']['minimum_training_matches']:
            excluded.append(item['id'])
            continue
        rho = fit_rho(training)
        models = defaultdict(list)
        for fixture, pair, (averages, strengths) in zip(fixtures, rates, contexts, strict=True):
            models[BASE].append(distribution(*pair))
            models[FIXED].append(distribution(*FIXED_RATES))
            for name, candidate in candidate_rates(fixture, pair, averages, strengths, params).items():
                models[name].append(distribution(*candidate))
            models['dixon_coles'].append(adjusted(pair, rho))
        if any(model is None for model in models['dixon_coles']):
            excluded.append(item['id'])
            continue
        rows.append({'round_id': item['id'], 'rho': rho,
                     'models': {name: score_models(values, actual) for name, values in models.items()}})

    summary = {}
    if len(rows) >= minimum:
        baseline = [row['models'][BASE] for row in rows]
        for name in (BASE, FIXED, *params):
            entries = [row['models'][name] for row in rows]
            metrics = ('log_loss', 'points')
            differences = [{key: right[key] - left[key] for key in metrics}
                           for left, right in zip(baseline, entries, strict=True)]
            summary[name] = {
                **summarize(entries),
                'mean_expected_points': sum(row['expected_points'] for row in entries) / len(entries),
                'mean_log_loss': sum(row['log_loss'] for row in entries) / len(entries),
                'paired_intervals_vs_venue': paired_intervals(differences, 10_000, 8, metrics),
            }
    return {'protocol': protocol, 'as_of': as_of.isoformat(), 'eligible_holdouts': len(rows),
            'excluded_holdouts': excluded, 'summary': summary, 'rounds': rows if summary else []}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rounds', type=Path, default=Path('data/rounds.json'))
    parser.add_argument('--as-of', type=timestamp, required=True)
    parser.add_argument('--feeds', type=Path)
    parser.add_argument('--review', type=Path, default=REVIEW)
    parser.add_argument('--competitions', type=Path,
                        help='JSON mapping from round IDs to home-team names to verified score-feed URLs')
    args = parser.parse_args()
    sources = {}
    if args.feeds:
        manifest = json.loads(args.review.read_text())
        for relative, reference in manifest['feeds'].items():
            path = (args.feeds / relative).resolve()
            if not path.is_relative_to(args.feeds.resolve()):
                parser.error('Invalid feed path')
            feed = score_feed(path, relative)
            if feed['sha256'] != reference['sha256']:
                parser.error(f'Feed digest mismatch for {relative}')
            sources[feed['url']] = feed
    competitions = json.loads(args.competitions.read_text()) if args.competitions else {}
    print(json.dumps(study(load_rounds(args.rounds), args.as_of, sources, competitions),
                     indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
