"""Load prospective ledger records and aggregate settled performance."""
import hashlib
import json

from .backtest import summarize
from .evidence import timestamp
from .live import path_for


def cumulative(rows):
    actual, expected = 0, 0.0
    trend = []
    for round_id, entry in rows:
        actual += entry['points']
        expected += entry['expected_points']
        trend.append({'round_id': round_id, 'points': actual, 'expected_points': expected})
    return trend


def report(directory, as_of):
    rows = []
    for path in directory.glob('*.forecast.json'):
        raw = path.read_bytes()
        record = json.loads(raw)
        round_id = record['round']['id']
        frozen_at = timestamp(record['frozen_at'])
        if (path != path_for(directory, round_id, 'forecast')
                or frozen_at >= timestamp(record['round']['deadline'])):
            raise ValueError(f'Invalid forecast ledger record: {path.name}')
        if frozen_at > as_of:
            continue
        result_path = path_for(directory, round_id, 'result')
        if result_path.exists():
            settlement = json.loads(result_path.read_text())
            if settlement['round_id'] != round_id or settlement['forecast_sha256'] != hashlib.sha256(raw).hexdigest():
                raise ValueError(f'Settlement does not match frozen forecast: {round_id}')
            if timestamp(settlement['settled_at']) <= as_of:
                record['settlement'] = settlement
        rows.append(record)
    rows.sort(key=lambda record: (timestamp(record['round']['deadline']), record['round']['id']))

    models = {}
    for record in rows:
        if 'settlement' not in record:
            continue
        for name, evaluation in record['settlement']['evaluations'].items():
            prediction = record['predictions'][name]
            entry = {**evaluation, 'expected_points': prediction['expected_points'],
                     'probability_13_plus': prediction['probability_13_plus']}
            models.setdefault(name, []).append((record['round']['id'], entry))
    summary = {}
    for name, scores in models.items():
        entries = [entry for _, entry in scores]
        summary[name] = {**summarize(entries), 'trend': cumulative(scores),
                         'mean_expected_points': sum(r['expected_points'] for r in entries) / len(entries),
                         'result_brier': sum(r['result_brier'] for r in entries) / len(entries)}
    return {'rounds': rows, 'summary': summary}
