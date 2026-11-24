"""Freeze and score prospective Super 6 forecasts from reviewed Sky records."""
import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

from .archive import load_rounds
from .backtest import FIXED_RATES
from .capture import missing, prematch, validate_capture
from .evidence import evidence, ready, timestamp, validate, verified_snapshot
from .model import forecast, form_rates, outcome, points, predict
from .report import FIXED, FORM, MODEL, quality, stale
from .research import MIN_MATCHES

DIRECTORY = Path('data/prospective')
GOAL_RULE = ('Estimate uses first goal in elapsed time across scheduled kickoffs. '
             'Confirm Sky’s treatment of staggered kickoffs, stoppage time and amended fixtures.')


def now():
    return datetime.now(timezone.utc)


def encode(record):
    return (json.dumps(record, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode()


def path_for(directory, round_id, kind):
    key = hashlib.sha256(round_id.encode()).hexdigest()
    return directory / f'{key}.{kind}.json'


def publish(path, record, before=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent) as pending:
        pending.write(encode(record))
        pending.flush()
        if before is not None and now() >= before:
            raise ValueError('The entry deadline has passed')
        path.hardlink_to(pending.name)


def source_bytes(directory, digest):
    if not re.fullmatch(r'[a-f0-9]{64}', digest):
        raise ValueError('Invalid source digest')
    path = directory / digest
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError(f'Missing or changed source bytes: {digest}')


def collect_source(url, directory):
    # curl bounds total transfer time, including slow response bodies.
    evidence({'url': url, 'available_at': now().isoformat(), 'note': 'Source capture'})
    result = subprocess.run(
        ['curl', '--disable', '--silent', '--show-error', '--fail', '--proto', '=https',
         '--connect-timeout', '4', '--max-time', '10', '--retry', '1',
         '--retry-max-time', '12', '--max-filesize', '8000000', '--url', url],
        capture_output=True, check=True, timeout=22,
    )
    if not result.stdout:
        raise ValueError('Source returned an empty response')
    captured = now().isoformat()
    digest = hashlib.sha256(result.stdout).hexdigest()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / digest
    with NamedTemporaryFile(dir=directory) as pending:
        pending.write(result.stdout)
        pending.flush()
        try:
            path.hardlink_to(pending.name)
        except FileExistsError:
            source_bytes(directory, digest)
    return {'url': url, 'captured_at': captured, 'source_sha256': digest}


def freeze_round(item, directory, sources):
    cutoff = timestamp(item['deadline'])
    path = path_for(directory, item['id'], 'forecast')
    if path.exists():
        raise FileExistsError(path)
    if now() >= cutoff:
        raise ValueError('The entry deadline has passed')
    if 'golden_goal' in item or any('result' in f for f in item['fixtures']):
        raise ValueError('Forecast input cannot contain results')
    validate_capture(item)
    official = item['official']
    if 'confirmed_at' not in official or timestamp(official['confirmed_at']) < timestamp(official['captured_at']):
        raise ValueError('Record human confirmation of the six Sky fixtures and explicit Sky deadline after capture')
    records = [official]
    for fixture in item['fixtures']:
        if not fixture.get('id') or not fixture.get('kickoff_source'):
            raise ValueError('Each fixture needs an identifier and kickoff source')
        records.extend(fixture.get('research', {}).values())
        if stats := fixture.get('stats'):
            for record in [stats, *stats.get('sources', [])]:
                source_bytes(sources, record['sha256'])
    for record in records:
        source_bytes(sources, record['source_sha256'])
    fixtures = item['fixtures']
    kickoffs = [f['kickoff'] for f in fixtures]
    predictions = {FIXED: forecast([(FIXED_RATES, None)] * 6, kickoffs=kickoffs)}
    fresh = [{key: record for key, record in f.get('research', {}).items()
              if not stale(key, record, cutoff)} for f in fixtures]
    if all(ready({'research': research}) for research in fresh):
        predictions[MODEL] = predict(prematch(item))
    elif all('stats' in f and all(f['stats'][side]['recent']['matches'] >= MIN_MATCHES
                                 and not stale('form', {'available_at': f['stats'][side]['latest_available_at']}, cutoff)
                                 for side in ('home', 'away')) for f in fixtures):
        predictions[FORM] = forecast([form_rates({'stats': f['stats'], 'research': research})
                                      for f, research in zip(fixtures, fresh, strict=True)], kickoffs=kickoffs)
    for prediction in predictions.values():
        prediction['simulated_expected_points'] = prediction['expected_points']
        prediction['expected_points'] = sum(pick['expected_points'] for pick in prediction['fixtures'])
    recommended = next(name for name in (MODEL, FORM, FIXED) if name in predictions)
    publish(path, {
        'protocol': 'prospective-v1', 'frozen_at': now().isoformat(), 'round': prematch(item),
        'recommended_model': recommended, 'predictions': predictions,
        'quality_flags': quality(item), 'missing_research': missing(item),
        'golden_goal_rule': GOAL_RULE,
    }, before=cutoff)
    return path


def settle_round(round_id, results, directory, sources):
    path = path_for(directory, round_id, 'forecast')
    raw = path.read_bytes()
    frozen = json.loads(raw)
    item = frozen['round']
    if item['id'] != round_id or timestamp(frozen['frozen_at']) >= timestamp(item['deadline']):
        raise ValueError('A valid pre-deadline forecast is required')
    if not isinstance(results, dict) or set(results) != {f['id'] for f in item['fixtures']}:
        raise ValueError('Provide results for all six frozen fixture identifiers')
    observed = now()
    for fixture in item['fixtures']:
        result = results[fixture['id']]
        if (evidence(result, official=True) > observed
                or timestamp(result['captured_at']) > observed):
            raise ValueError('Final result evidence cannot be dated in the future')
        verified_snapshot(result, observed)
        source_bytes(sources, result['source_sha256'])
        fixture['result'] = result
    validate(item)
    actual = [f['result']['score'] for f in item['fixtures']]
    evaluations = {}
    for name, prediction in frozen['predictions'].items():
        picks = prediction['fixtures']
        values = [points(pick['score'], score) for pick, score in zip(picks, actual, strict=True)]
        evaluations[name] = {
            'points': sum(values), 'exact': values.count(5), 'correct': sum(value > 0 for value in values),
            'hit_13': sum(values) >= 13, 'fixture_points': values,
            'result_brier': sum(sum((p - (i == outcome(score))) ** 2 for i, p in
                                    enumerate(pick['result_probabilities']))
                                for pick, score in zip(picks, actual, strict=True)) / 6,
        }
    destination = path_for(directory, round_id, 'result')
    publish(destination, {'round_id': round_id, 'settled_at': observed.isoformat(),
                          'forecast_sha256': hashlib.sha256(raw).hexdigest(),
                          'results': results, 'evaluations': evaluations})
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('collect', 'freeze', 'settle'))
    parser.add_argument('input', help='HTTPS URL to collect or JSON file to freeze or settle')
    parser.add_argument('--round-id', help='Frozen round identifier when settling')
    parser.add_argument('--directory', type=Path, default=DIRECTORY)
    parser.add_argument('--sources', type=Path, required=True, help='Evidence bytes named by SHA-256')
    args = parser.parse_args()
    try:
        if args.action == 'collect':
            print(json.dumps(collect_source(args.input, args.sources), indent=2))
            return
        data = json.loads(Path(args.input).read_text())
        if args.action == 'freeze':
            if any(round_data['id'] == data['id'] for round_data in load_rounds()):
                raise ValueError('The round already exists in the legacy archive')
            path = freeze_round(data, args.directory, args.sources)
        else:
            if not args.round_id:
                parser.error('--round-id is required when settling')
            path = settle_round(args.round_id, data, args.directory, args.sources)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        parser.exit(1, f'{exc}\n')
    print(path)


if __name__ == '__main__':
    main()
