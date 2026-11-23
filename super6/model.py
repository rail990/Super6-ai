"""Independent goal Poisson model and Super 6 scoring."""
from datetime import timedelta
from itertools import product
from math import ceil, exp, log, prod
from random import Random

from .evidence import ready, timestamp, validate

TRIALS = 100_000


def poisson(rate):
    mass = [exp(-rate)]
    while sum(mass) < 1 - 1e-12:
        mass.append(mass[-1] * rate / len(mass))
    total = sum(mass)
    return [value / total for value in mass]


def outcome(score):
    home, away = score
    return (home < away) - (home > away) + 1


def points(pick, result):
    if tuple(pick) == tuple(result):
        return 5
    return 2 if outcome(pick) == outcome(result) else 0


def distribution(home, away):
    return {(h, a): hp * ap
            for (h, hp), (a, ap) in product(enumerate(poisson(home)), enumerate(poisson(away)))}


def result_probabilities(scores):
    probabilities = [0.0] * 3
    for score, probability in scores.items():
        probabilities[outcome(score)] += probability
    return probabilities


def fit(fixture):
    research = fixture['research']
    # Venue-specific recent expected goals combined with opposing expected goals against.
    prior = (
        (research['xg']['home'] + research['xga']['away']) / 2,
        (research['xg']['away'] + research['xga']['home']) / 2,
    )
    implied = [1 / price for price in research['odds']['decimal']]
    market = [p / sum(implied) for p in implied]

    def loss(rates):
        fitted = result_probabilities(distribution(*rates))
        return sum((a-b)**2 for a, b in zip(fitted, market)) + 0.05 * sum(
            (a-b)**2 for a, b in zip(rates, prior)
        )

    rates = tuple(min(12, max(0.05, value)) for value in prior)
    for step in (0.5, 0.2, 0.05, 0.01):
        while True:
            candidates = {rates}
            for dh, da in product((-step, 0, step), repeat=2):
                candidates.add(tuple(round(min(12, max(0.05, rate + delta)), 4)
                                     for rate, delta in zip(rates, (dh, da))))
            improved = min(candidates, key=lambda pair: (loss(pair), pair))
            if loss(improved) >= loss(rates) - 1e-12:
                break
            rates = improved
    return rates, market


def golden_goal(rates):
    # Take the earliest goal on the match clock across all six fixtures.
    combined = sum(sum(pair) for pair in rates)
    survival = [exp(-combined * minute / 90) for minute in range(91)]
    probabilities = [a - b for a, b in zip(survival, survival[1:])]
    # The conditional median minimizes absolute error in minutes.
    median = next(i for i, p in enumerate(survival[1:], 1)
                  if p <= (1 + survival[-1]) / 2)
    return {'minute': median, 'minute_probabilities': probabilities, 'no_goal': survival[-1]}


def chronological_goal(rates, kickoffs):
    first = min(kickoffs)
    offsets = [(value - first).total_seconds() / 60 for value in kickoffs]
    intensity = [sum(pair) / 90 for pair in rates]
    boundaries = sorted({point for offset in offsets for point in (offset, offset + 90)})
    remaining = 1.0
    median = None
    active_start = None
    halfway = (1 + exp(-sum(sum(r) for r in rates))) / 2
    windows = []
    for start, end in zip(boundaries, boundaries[1:]):
        rate = sum(rate for rate, offset in zip(intensity, offsets) if offset <= start < offset + 90)
        after = remaining * exp(-rate * (end - start))
        if rate:
            windows.append({'start': start, 'end': end, 'probability': remaining - after})
            if median is None and after <= halfway:
                median = start + log(remaining / halfway) / rate
                active_start = min(offset for offset in offsets if offset <= start < offset + 90)
        remaining = after
    opening_group = [pair for pair, offset in zip(rates, offsets) if offset == 0]
    return {'first_kickoff': first.isoformat(), 'elapsed_minute': ceil(median),
            'kickoff_for_recommendation': (first + timedelta(minutes=active_start)).isoformat(),
            'recommended_minute': ceil(median - active_start),
            'first_window_goal_probability': 1 - exp(-sum(sum(pair) for pair in opening_group)),
            'windows': windows}


def predict(round_data, seed=6):
    validate(round_data)
    fixtures = round_data['fixtures']
    if not all(map(ready, fixtures)):
        raise ValueError('Every fixture needs pre-deadline research')
    return forecast([fit(fixture) for fixture in fixtures], seed, [f['kickoff'] for f in fixtures])


def forecast(inputs, seed=6, kickoffs=None):
    rates, predictions, weights, modal_weights = [], [], [], []
    for pair, market in inputs:
        rates.append(pair)
        scores = distribution(*pair)
        outcomes = result_probabilities(scores)
        pick = max(scores, key=lambda score: 2 * outcomes[outcome(score)] + 3 * scores[score])
        exact = scores[pick]
        correct = outcomes[outcome(pick)]
        weights.append((exact, correct))
        modal = max(scores, key=scores.get)
        modal_weights.append((scores[modal], outcomes[outcome(modal)]))
        predictions.append({'score': pick, 'modal_score': modal, 'rates': pair, 'exact_probability': exact,
                            'result_probabilities': outcomes, 'market_probabilities': market,
                            'expected_points': 2 * correct + 3 * exact,
                            'top_scores': sorted(scores.items(), key=lambda item: -item[1])[:5]})
    rng = Random(seed)
    counts = [0] * 31
    for _ in range(TRIALS):
        total = 0
        for exact, correct in weights:
            draw = rng.random()
            total += 5 if draw < exact else 2 if draw < correct else 0
        counts[total] += 1
    pmf = exact_points(weights)
    modal_pmf = exact_points(modal_weights)
    goal = golden_goal(rates)
    if kickoffs:
        goal['schedule'] = chronological_goal(rates, list(map(timestamp, kickoffs)))
    return {'fixtures': predictions, 'trials': TRIALS, 'seed': seed, 'points_counts': counts,
            'expected_points': sum(i * n for i, n in enumerate(counts)) / TRIALS,
            'probability_13_plus': sum(pmf[13:]),
            'simulated_probability_13_plus': sum(counts[13:]) / TRIALS,
            'probability_all_exact': prod(exact for exact, _ in weights),
            'simulated_probability_all_exact': counts[30] / TRIALS,
            'modal_combination': {
                'scores': [p['modal_score'] for p in predictions],
                'expected_points': sum(i * value for i, value in enumerate(modal_pmf)),
                'probability_13_plus': sum(modal_pmf[13:]),
                'probability_all_exact': prod(exact for exact, _ in modal_weights),
            },
            'golden_goal': goal}


def exact_points(weights):
    pmf = [1.0]
    for exact, correct in weights:
        updated = [0.0] * (len(pmf) + 5)
        for score, mass in enumerate(pmf):
            updated[score] += mass * (1 - correct)
            updated[score + 2] += mass * (correct - exact)
            updated[score + 5] += mass * exact
        pmf = updated
    return pmf


def venue_rates(fixture):
    home, away = (fixture['venue_history'][side] for side in ('home', 'away'))
    # Pool goals for with the opponent's goals against. Two prior match equivalents shrink small samples.
    return tuple(
        (sum(match['score'][0] for match in own)
         + sum(match['score'][1] for match in opponent) + 2 * prior)
        / (len(own) + len(opponent) + 2)
        for own, opponent, prior in ((home, away, 1.5), (away, home, 1.1))
    )



def form_rates(fixture):
    home, away = (fixture['stats'][side] for side in ('home', 'away'))

    def rate(own, other, prior, attack='goals_for', defence='goals_against'):
        own_all, other_all = own['recent'], other['recent']
        own_venue, other_venue = own['venue'], other['venue']
        # Recent games each have weight 1, venue matches receive one extra weight.
        goals = own_all[attack] + other_all[defence] + own_venue[attack] + other_venue[defence]
        sample = sum(group['matches'] for group in (own_all, other_all, own_venue, other_venue))
        return (goals + 6 * prior) / (sample + 6)

    research = fixture.get('research', {})
    if 'xg' in research and 'xga' in research:
        xg, xga = research['xg'], research['xga']
        return ((max(0.05, (xg['home'] + xga['away']) / 2),
                 max(0.05, (xg['away'] + xga['home']) / 2)), None)
    return ((rate(home, away, 1.5), rate(away, home, 1.1)), None)
