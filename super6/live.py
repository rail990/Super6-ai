"""Freeze and score prospective Super 6 forecasts from reviewed Sky records."""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

from .archive import load_rounds
from .backtest import FIXED_RATES
from .capture import missing, prematch, validate_capture
from .evidence import RESEARCH, evidence, ready, timestamp, validate, verified_snapshot
from .model import forecast, form_rates, outcome, points, predict
from .report import FIXED, FORM, MODEL, quality, stale
from .research import MIN_MATCHES
from .sky import ROOT as SKY_ROOT, final_scores, match_stats, official_goal, slate, url_for

DIRECTORY = Path('data/prospective')
GOAL_RULE = ('Sky awarded Round 17’s Golden Goal to a match that kicked off a day after earlier '
             'fixtures had already produced goals. The match-clock estimate reflects that observation. '
             'The elapsed-time estimate uses the scheduled kickoffs. Stoppage-time and amended-fixture rules need confirmation.')
GOAL_RULE_SOURCE = f'{SKY_ROOT}/17'


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
    raw = path.read_bytes() if path.is_file() else None
    if raw is None or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError(f'Missing or changed source bytes: {digest}')
    return raw


def collect_source(url, directory):
    # curl bounds total transfer time, including slow response bodies.
    evidence({'url': url, 'available_at': now().isoformat(), 'note': 'Source capture'})
    result = subprocess.run(
        ['curl', '--disable', '--silent', '--show-error', '--fail', '--proto', '=https',
         '--connect-timeout', '4', '--max-time', '10', '--retry', '1',
         '--retry-max-time', '12', '--max-filesize', '8000000',
         '--write-out', '\n%{http_code}', '--url', url],
        capture_output=True, check=True, timeout=22,
    )
    body, _, status = result.stdout.rpartition(b'\n')
    if status != b'200' or not body:
        raise ValueError(f"Source did not return a usable HTTP 200 response ({status.decode('ascii')})")
    captured = now().isoformat()
    digest = hashlib.sha256(body).hexdigest()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / digest
    with NamedTemporaryFile(dir=directory) as pending:
        pending.write(body)
        pending.flush()
        try:
            path.hardlink_to(pending.name)
        except FileExistsError:
            source_bytes(directory, digest)
    return {'url': url, 'captured_at': captured, 'source_sha256': digest}


def sky_capture(round_number, sources):
    capture = collect_source(url_for(round_number), sources)
    raw = source_bytes(sources, capture['source_sha256'])
    return json.loads(raw), capture


def prepare_round(payload, capture, sources, plan=()):
    """Collect Sky form plus candidate public research sources for human review."""
    item = slate(payload, capture)
    by_id = {fixture['id']: fixture for fixture in item['fixtures']}
    api = SKY_ROOT.removesuffix('/round')
    jobs = []
    for challenge in payload['scoreChallenges']:
        match = challenge['match']
        if type(match['id']) is not int or match['id'] < 1:
            raise ValueError('Sky match identifier must be positive')
        jobs.append((str(challenge['id']), 'stats', f"{api}/match/{match['id']}/stats", match))
    if len(plan) > 60:
        raise ValueError('Research plan supports at most 60 source URLs per round')
    for entry in plan:
        fixture_id = str(entry['fixture_id'])
        if fixture_id not in by_id or entry['category'] not in (*RESEARCH, 'lineups'):
            raise ValueError('Research plan needs a current fixture ID and a recognized category')
        jobs.append((fixture_id, entry['category'], entry['url'], None))

    failures = (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError)

    def fetch(url):
        try:
            captured = collect_source(url, sources)
            if timestamp(captured['captured_at']) >= timestamp(item['deadline']):
                raise ValueError('Capture reached or passed the Sky deadline')
            return captured, None
        except failures as exc:
            return None, type(exc).__name__

    urls = list(dict.fromkeys(url for _, _, url, _ in jobs))
    with ThreadPoolExecutor(max_workers=4) as executor:
        fetched = dict(zip(urls, executor.map(fetch, urls), strict=True))

    gaps = []
    for fixture_id, category, url, match in jobs:
        entry = {'fixture_id': fixture_id, 'category': category, 'url': url}
        collected, error = fetched[url]
        if error:
            gaps.append({**entry, 'status': 'unavailable', 'error': error})
            continue
        if match is None:
            gaps.append({**entry, **collected, 'status': 'pending_review'})
            continue
        try:
            raw = source_bytes(sources, collected['source_sha256'])
            by_id[fixture_id]['stats'] = match_stats(json.loads(raw), match, collected)
        except failures as exc:
            gaps.append({**entry, 'status': 'unavailable', 'error': type(exc).__name__})
    return validate(item), gaps


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
    if official['url'].startswith(f'{SKY_ROOT}/'):
        payload = json.loads(source_bytes(sources, official['source_sha256']))
        reviewed = slate(payload, official)
        fields = ('id', 'home', 'away', 'kickoff', 'kickoff_source', 'competition')
        if (item['id'] != reviewed['id'] or item['deadline'] != reviewed['deadline']
                or [{key: f[key] for key in fields} for f in item['fixtures']] != reviewed['fixtures']):
            raise ValueError('Round manifest differs from the captured Sky fixture slate or deadline')
        if payload['status'] != 'open' or timestamp(reviewed['opens']) > timestamp(official['captured_at']):
            raise ValueError('Capture a fresh Sky slate after entries open before freezing')
        api = SKY_ROOT.removesuffix('/round')
        challenges = {str(c['id']): c['match'] for c in payload['scoreChallenges']}
        for fixture in item['fixtures']:
            stats = fixture.get('stats', {})
            if stats.get('provider') != 'Sky Sports Super 6':
                continue
            match = challenges[fixture['id']]
            raw = source_bytes(sources, stats['sha256'])
            reference = {'url': f"{api}/match/{match['id']}/stats",
                         'captured_at': stats['available_at'], 'source_sha256': stats['sha256']}
            if stats != match_stats(json.loads(raw), match, reference):
                raise ValueError('Structured form statistics differ from captured Sky history')
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
        prediction['golden_goal']['recommended_minute'] = prediction['golden_goal']['minute']
        prediction['simulated_expected_points'] = prediction['expected_points']
        prediction['expected_points'] = sum(pick['expected_points'] for pick in prediction['fixtures'])
    recommended = next(name for name in (MODEL, FORM, FIXED) if name in predictions)
    missing_research = missing(item)
    for fixture in fixtures:
        stats = fixture.get('stats')
        if stats and all(stats[side]['recent']['matches'] > 0 for side in ('home', 'away')):
            label = f"{fixture['home']} vs {fixture['away']}"
            for entry in missing_research:
                if entry['fixture'] == label:
                    derived = {'form'}
                    if all(stats[side]['venue']['matches'] > 0 for side in ('home', 'away')):
                        derived.add('venue_form')
                    entry['missing'] = sorted(set(entry['missing']) - derived)
    stored_round = prematch(item)
    if 'sky_round' in item:
        stored_round['sky_round'] = item['sky_round']
        stored_round['sky_season'] = item['sky_season']
    publish(path, {
        'protocol': 'prospective-v1', 'frozen_at': now().isoformat(), 'round': stored_round,
        'recommended_model': recommended, 'predictions': predictions,
        'quality_flags': quality(item), 'missing_research': [row for row in missing_research if row['missing']],
        'golden_goal_rule': GOAL_RULE, 'golden_goal_rule_source': GOAL_RULE_SOURCE,
        'collection_gaps': item.get('collection_gaps', []),
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
    sky_results = {}
    goal = None
    for fixture in item['fixtures']:
        result = results[fixture['id']]
        if (evidence(result, official=True) > observed
                or timestamp(result['captured_at']) > observed):
            raise ValueError('Final result evidence cannot be dated in the future')
        verified_snapshot(result, observed)
        digest = result['source_sha256']
        raw_source = source_bytes(sources, digest)
        if result['url'].startswith(f'{SKY_ROOT}/'):
            if digest not in sky_results:
                capture = {key: result[key] for key in ('url', 'captured_at', 'source_sha256')}
                payload = json.loads(raw_source)
                sky_results[digest] = final_scores(payload, capture, item)
                goal = official_goal(payload, capture)
            if result != sky_results[digest][fixture['id']]:
                raise ValueError('Result differs from the captured Sky final score')
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
                          'results': results, 'evaluations': evaluations,
                          **({'golden_goal': goal} if goal is not None else {})})
    return destination


def freeze_new(item, directory, sources):
    legacy = {r['id'] for r in load_rounds()}
    display_id = item['id'].removeprefix('Sky ').replace('-', '–', 1)
    if item['id'] in legacy or display_id in legacy:
        raise ValueError('The round already exists in the legacy archive')
    return freeze_round(item, directory, sources)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('collect', 'preview', 'prepare', 'forecast-sky', 'freeze', 'settle', 'settle-sky'))
    parser.add_argument('input', help='HTTPS source URL, Sky round number, frozen round ID or JSON path, depending on action')
    parser.add_argument('--round-id', help='Frozen round identifier when settling')
    parser.add_argument('--directory', type=Path, default=DIRECTORY)
    parser.add_argument('--sources', type=Path, required=True, help='Evidence bytes named by SHA-256')
    parser.add_argument('--plan', type=Path, help='Optional JSON list of fixture research URLs to collect')
    parser.add_argument('--reviewed', type=Path, help='Fixture ID to reviewed research mapping for forecast-sky')
    args = parser.parse_args()
    try:
        if args.action == 'collect':
            print(json.dumps(collect_source(args.input, args.sources), indent=2))
            return
        if args.action in ('preview', 'prepare', 'forecast-sky'):
            payload, capture = sky_capture(args.input, args.sources)
            if payload['status'] not in ('open', 'future') or timestamp(payload['endDateTime']) <= now():
                raise ValueError('Sky does not have an upcoming slate for this round')
            if args.action in ('prepare', 'forecast-sky'):
                plan = json.loads(args.plan.read_text()) if args.plan else []
                item, gaps = prepare_round(payload, capture, args.sources, plan)
                item['collection_gaps'] = gaps
                for entry in gaps:
                    print(json.dumps(entry, ensure_ascii=False), file=sys.stderr)
            else:
                item = slate(payload, capture)
            if args.action == 'forecast-sky':
                reviewed = json.loads(args.reviewed.read_text()) if args.reviewed else {}
                if set(reviewed) - {fixture['id'] for fixture in item['fixtures']}:
                    raise ValueError('Reviewed evidence references an unknown fixture ID')
                for fixture in item['fixtures']:
                    if fixture['id'] in reviewed:
                        fixture['research'] = reviewed[fixture['id']]
                path = freeze_new(item, args.directory, args.sources)
                print(path)
                return
            print(json.dumps(item, indent=2, ensure_ascii=False))
            return
        if args.action == 'settle-sky':
            frozen = json.loads(path_for(args.directory, args.input, 'forecast').read_bytes())
            payload, capture = sky_capture(frozen['round']['sky_round'], args.sources)
            path = settle_round(args.input, final_scores(payload, capture, frozen['round']),
                                args.directory, args.sources)
            print(path)
            return
        data = json.loads(Path(args.input).read_text())
        if args.action == 'freeze':
            path = freeze_new(data, args.directory, args.sources)
        else:
            if not args.round_id:
                parser.error('--round-id is required when settling')
            path = settle_round(args.round_id, data, args.directory, args.sources)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        parser.exit(1, f'{exc}\n')
    print(path)


if __name__ == '__main__':
    main()
