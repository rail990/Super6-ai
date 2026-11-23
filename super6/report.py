"""Generate a portable dashboard and run point-in-time evaluation."""
import argparse
import json
import shutil
from pathlib import Path

from .evidence import ready, validate
from .model import points, predict


def report(rounds, baseline):
    rows = []
    scored = []
    seen = set()
    for item in rounds:
        validate(item)
        if item['id'] in seen:
            raise ValueError(f"Duplicate round: {item['id']}")
        seen.add(item['id'])
        fixtures = item['fixtures']
        prediction = predict(item) if all(map(ready, fixtures)) else None
        evaluation = None
        if prediction and all('result' in f for f in fixtures):
            values = [points(p['score'], f['result']['score'])
                      for p, f in zip(prediction['fixtures'], fixtures)]
            actual = item.get('golden_goal', {}).get('minute')
            evaluation = {
                'points': sum(values), 'exact': values.count(5), 'result_only': values.count(2),
                'hit_13_plus': sum(values) >= 13,
                'golden_goal_error': abs(prediction['golden_goal']['minute'] - actual)
                if actual is not None else None,
            }
            scored.append((prediction, evaluation))
        rows.append({'round': item, 'prediction': prediction, 'evaluation': evaluation})

    count = len(scored)
    errors = [e['golden_goal_error'] for _, e in scored if e['golden_goal_error'] is not None]
    summary = {'rounds': count}
    if count:
        summary.update({
            'mean_points': sum(e['points'] for _, e in scored) / count,
            'mean_expected_points': sum(p['expected_points'] for p, _ in scored) / count,
            'hit_rate_13_plus': sum(e['hit_13_plus'] for _, e in scored) / count,
            'brier_13_plus': sum((p['probability_13_plus'] - e['hit_13_plus'])**2
                                for p, e in scored) / count,
            'golden_goal_mae': sum(errors) / len(errors) if errors else None,
        })
    return {'baseline': baseline, 'rounds': rows, 'backtest': summary}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rounds', type=Path, default=Path('data/rounds.json'))
    parser.add_argument('--output', type=Path, default=Path('dist'))
    args = parser.parse_args()
    data = report(json.loads(args.rounds.read_text()), json.loads(Path('data/baseline.json').read_text()))
    args.output.mkdir(parents=True, exist_ok=True)
    for path in Path('dashboard').iterdir():
        shutil.copy2(path, args.output)
    (args.output / 'report.json').write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')
    print(f"Built {len(data['rounds'])} rounds with {data['backtest']['rounds']} scored backtests")


if __name__ == '__main__':
    main()
