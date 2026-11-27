"""Build venue-form evidence from local Football-Data results CSV files."""
import argparse
import csv
import hashlib
import io
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .evidence import timestamp, validate

UK = ZoneInfo('Europe/London')
WINDOW = 5


def load(path, url):
    raw = path.read_bytes()
    matches = []
    for row in csv.DictReader(io.StringIO(raw.decode('utf-8-sig', errors='replace'))):
        if row.get('FTR') not in ('H', 'D', 'A'):
            continue
        played = datetime.strptime(row['Date'], '%d/%m/%Y').date()
        # A date alone cannot establish that a match had finished on cutoff day.
        available = datetime.combine(played + timedelta(days=1), datetime.min.time(), UK)
        score = (int(row['FTHG']), int(row['FTAG']))
        matches.append((available, row['HomeTeam'], row['AwayTeam'], score))
    return {'url': url, 'sha256': hashlib.sha256(raw).hexdigest(), 'matches': matches}


def attach(item, sources, aliases):
    cutoff = timestamp(item['deadline'])
    for fixture in item['fixtures']:
        history = {}
        for side, other in (('home', 'away'), ('away', 'home')):
            team = aliases.get(fixture[side], fixture[side])
            score_index = 0 if side == 'home' else 1
            matches = {}
            for source in sources:
                for available, home, away, score in source['matches']:
                    teams = {'home': home, 'away': away}
                    if available >= cutoff or teams[side] != team:
                        continue
                    key = (available, home, away)
                    record = (score[score_index], score[1-score_index], source)
                    if key in matches and matches[key][:2] != record[:2]:
                        raise ValueError(f'Conflicting scores for {key}')
                    matches[key] = record
            recent = sorted(matches.items(), reverse=True)[:WINDOW]
            if len(recent) < WINDOW:
                raise ValueError(f'Need {WINDOW} prior {side} results for {team}')
            history[side] = []
            for (available, home, away), (goals, conceded, source) in recent:
                history[side].append({
                    'available_at': available.isoformat(), 'url': source['url'],
                    'sha256': source['sha256'], 'opponent': {'home': home, 'away': away}[other],
                    'score': [goals, conceded],
                    'note': 'Full-time league result. Availability conservatively set to the next local midnight.',
                })
        fixture['venue_history'] = history
    return validate(item)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('round', type=Path)
    parser.add_argument('--source', nargs=2, metavar=('CSV', 'URL'), required=True, action='append')
    parser.add_argument('--aliases', type=Path, help='JSON mapping from official names to CSV names')
    args = parser.parse_args()
    item = json.loads(args.round.read_text())
    aliases = json.loads(args.aliases.read_text()) if args.aliases else {}
    results = attach(item, [load(Path(path), url) for path, url in args.source], aliases)
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
