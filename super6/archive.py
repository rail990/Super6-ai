"""Build the goals-only archive from reviewed Sky slates and free score files."""
import argparse
import csv
import hashlib
import io
import json
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from .evidence import evidence, timestamp
from .venue import UK, attach

ROUNDS = Path('data/rounds.json')
EXPANSION = Path('data/archive-rounds.json')
REVIEW = Path('data/archive-review.json')
CANDIDATES = Path('data/archive-candidates.json')
QUALITY_LABELS = {
    'sky_advertised': 'Sky advertised deadline',
    'sky_first_kickoff_rule': 'Sky first-kickoff rule',
    'sky_revised_preview': 'Sky revised preview',
}
RESULTS_ROOT = 'https://www.football-data.co.uk/mmz4281/'


def load_rounds(path=ROUNDS):
    rounds = json.loads(path.read_text())
    if path.resolve() == ROUNDS.resolve() and EXPANSION.exists():
        rounds += json.loads(EXPANSION.read_text())
    return rounds


def archive_source(record, official=False):
    published = evidence(record, official=official)
    captured = timestamp(record['captured_at'])
    fingerprint = record.get('sha256', '')
    if captured < published or len(fingerprint) != 64 or any(
        c not in '0123456789abcdef' for c in fingerprint
    ):
        raise ValueError('Archive evidence needs a valid capture time and SHA-256')
    if 'modified_at' in record and timestamp(record['modified_at']) > captured:
        raise ValueError('Invalid publisher modification time')
    return published


def candidate_index(path=CANDIDATES):
    if not path.exists():
        return []
    value = json.loads(path.read_text())
    archive_source(value['index'])
    seen = set()
    for item in value['rounds']:
        if item['status'] != 'incomplete' or item['quality'] not in ('secondary_lead', 'primary_partial'):
            raise ValueError('Candidate index accepts incomplete evidence only')
        if item['url'] in seen or not item['reason'].strip():
            raise ValueError('Invalid or repeated archival lead')
        seen.add(item['url'])
        evidence({'url': item['url'], 'available_at': value['index']['available_at'], 'note': item['reason']})
        if item['quality'] == 'primary_partial':
            archive_source(item['source'], official=True)
    return value['rounds']


def score_feed(path, relative):
    raw = path.read_bytes()
    result = {'url': RESULTS_ROOT + relative, 'sha256': hashlib.sha256(raw).hexdigest(),
              'matches': [], 'fixtures': []}
    for row in csv.DictReader(io.StringIO(raw.decode('utf-8-sig', errors='replace'))):
        if row.get('FTR') not in ('H', 'D', 'A'):
            continue
        date = row['Date'].strip()
        played = datetime.strptime(date, '%d/%m/%y' if len(date.split('/')[-1]) == 2
                                   else '%d/%m/%Y').date()
        available = datetime.combine(played + timedelta(days=1), datetime.min.time(), UK)
        home, away = row['HomeTeam'].strip(), row['AwayTeam'].strip()
        score = [int(row['FTHG']), int(row['FTAG'])]
        result['matches'].append((available, home, away, score))
        result['fixtures'].append((played, home, away, row.get('Time'), score))
    return result


def assemble(review, sources):
    official = review['official']
    archive_source(official, official=True)
    timing = review.get('kickoff_evidence')
    deadline_claim = review.get('deadline_evidence')
    if deadline_claim:
        archive_source(deadline_claim, official=True)
    if timing:
        archive_source(timing)
    fixtures = []
    for entry in review['fixtures']:
        fixture_timing = entry.get('kickoff_evidence', timing)
        if 'kickoff_evidence' in entry:
            archive_source(fixture_timing)
        home, away = entry['home'], entry['away']
        start, end = review['match_window']
        found = [(source, row) for source in sources for row in source['fixtures']
                 if start <= row[0].isoformat() <= end and (home, away) == row[1:3]]
        if len(found) != 1:
            raise ValueError(f'Expected one archived fixture for {home} vs {away}, found {len(found)}')
        source, (played, _, _, clock, score) = found[0]
        if 'kickoff' in entry and not fixture_timing:
            raise ValueError('Manual kickoff requires a reviewed source')
        if 'kickoff' in entry and clock and clock != entry['kickoff']:
            raise ValueError(f'Conflicting kickoff for {home} vs {away}')
        clock = entry.get('kickoff', clock)
        if not clock:
            raise ValueError(f'Kickoff time unavailable for {home} vs {away}')
        kickoff = datetime.fromisoformat(f'{played}T{clock}').replace(tzinfo=UK)
        available = datetime.combine(played + timedelta(days=1), datetime.min.time(), UK)
        fixtures.append({
            'home': home, 'away': away, 'kickoff': kickoff.isoformat(),
            'kickoff_source': fixture_timing['url'] if 'kickoff' in entry else source['url'],
            **({'kickoff_evidence': fixture_timing} if 'kickoff' in entry else {}),
            'result': {'score': score, 'status': 'final', 'url': source['url'],
                       'available_at': available.isoformat(), 'sha256': source['sha256'],
                       'note': 'Final league score. Availability bounded by the next UK midnight.'},
        })
    if len(fixtures) != 6:
        raise ValueError('Exactly six reviewed Sky fixtures are required')
    earliest = min(timestamp(f['kickoff']) for f in fixtures)
    if 'advertised_deadline' in review and deadline_claim:
        deadline = timestamp(review['advertised_deadline'])
        quality = 'sky_advertised'
        basis = 'Deadline explicitly advertised by Sky.'
    elif deadline_claim and deadline_claim.get('rule') == 'first_kickoff':
        deadline = earliest
        quality = 'sky_first_kickoff_rule'
        basis = 'Cutoff follows Sky’s published first-kickoff rule and the verified kickoff records.'
    else:
        raise ValueError('Verified deadline or applicable Sky rule is missing')
    if any(archive_source(record, official=True) >= deadline for record in (official, deadline_claim)):
        raise ValueError('Publisher’s original date must predate the cutoff')
    if any(timestamp(record.get('modified_at', record['available_at'])) >= deadline
           for record in (official, deadline_claim)):
        if quality != 'sky_advertised':
            raise ValueError('First-kickoff rule cohort requires pre-cutoff slate and rule versions')
        quality = 'sky_revised_preview'
        basis = ('Deadline stated in Sky’s revised preview. The source verifies the historical slate '
                 'and cutoff. Model inputs come from separately dated prior results.')
    return attach({
        'id': review['id'], 'deadline': deadline.isoformat(), 'deadline_basis': basis,
        'source_quality': quality, 'official': official, 'deadline_evidence': deadline_claim,
        **({'kickoff_evidence': timing} if timing else {}),
        'fixtures': fixtures,
    }, sources, {})


def verified_result(record):
    if urlparse(record['url']).hostname == 'www.football-data.co.uk':
        if not record['url'].startswith(RESULTS_ROOT) or not record['url'].endswith('.csv'):
            raise ValueError('Historical final result needs a recognized score archive')
        digest = record.get('sha256', '')
        if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('Historical final result needs a score-file SHA-256')
        return evidence(record)
    return evidence(record, official=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('feeds', type=Path, help='Directory of season/division.csv files')
    parser.add_argument('--review', type=Path, default=REVIEW)
    args = parser.parse_args()
    manifest = json.loads(args.review.read_text())
    for key in manifest['feeds']:
        season, division = key.split('/', 1)
        if len(season) != 4 or not season.isascii() or not season.isdigit() or division not in (
            'E0.csv', 'E1.csv', 'E2.csv', 'E3.csv', 'EC.csv'
        ):
            raise ValueError('Expected a Football-Data season/division.csv key')
    feeds = {key: score_feed(args.feeds / key, key) for key in manifest['feeds']}
    for key, record in manifest['feeds'].items():
        timestamp(record['captured_at'])
        if feeds[key]['sha256'] != record['sha256']:
            raise ValueError(f'CSV digest mismatch: {key}')
    records = []
    for review in manifest['rounds']:
        selected = [feeds[key] for key in review['feeds']]
        records.append(assemble(review, selected))
    print('[\n' + ',\n'.join(json.dumps(r, ensure_ascii=False, separators=(',', ':'))
                               for r in records) + '\n]')


if __name__ == '__main__':
    main()
