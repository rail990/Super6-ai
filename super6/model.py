"""Independent goal Poisson model and Super 6 scoring."""
from itertools import product
from math import exp
from random import Random

from .evidence import ready, validate

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


def predict(round_data, seed=6):
    validate(round_data)
    fixtures = round_data['fixtures']
    if not all(map(ready, fixtures)):
        raise ValueError('Every fixture needs pre-deadline research')
    return forecast([fit(fixture) for fixture in fixtures], seed)


def forecast(inputs, seed=6):
    rates, predictions, weights = [], [], []
    for pair, market in inputs:
        rates.append(pair)
        scores = distribution(*pair)
        outcomes = result_probabilities(scores)
        pick = max(scores, key=lambda score: 2 * outcomes[outcome(score)] + 3 * scores[score])
        exact = scores[pick]
        correct = outcomes[outcome(pick)]
        weights.append((exact, correct))
        predictions.append({'score': pick, 'rates': pair, 'exact_probability': exact,
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
    return {'fixtures': predictions, 'trials': TRIALS, 'seed': seed, 'points_counts': counts,
            'expected_points': sum(i * n for i, n in enumerate(counts)) / TRIALS,
            'probability_13_plus': sum(pmf[13:]),
            'simulated_probability_13_plus': sum(counts[13:]) / TRIALS,
            'golden_goal': golden_goal(rates)}


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
