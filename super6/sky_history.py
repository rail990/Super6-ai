"""Capture verified Sky scorecards for the historical archive."""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from .evidence import timestamp
from .live import sky_capture
from .sky import final_scores, official_goal, slate

ARCHIVE = Path('data/sky-history.json')
UPCOMING = Path('data/upcoming-sky.json')


def historical_record(payload, capture):
    item = slate(payload, capture)
    if len(item['fixtures']) != 6 or timestamp(capture['captured_at']) <= timestamp(item['deadline']):
        raise ValueError('Historical archive requires a completed six-fixture Sky round')
    results = final_scores(payload, capture, item)
    goal = official_goal(payload, capture)
    fixtures = [{**fixture, 'score': results[fixture['id']]['score']} for fixture in item['fixtures']]
    return {'id': item['id'], 'deadline': item['deadline'], 'source': item['official'],
            'fixtures': fixtures, 'golden_goal': goal['minute']}


def unresolved_candidates(candidates, scorecards):
    verified = {card['id'] for card in scorecards}
    unresolved = []
    for lead in candidates:
        match = re.match(r'Round ([0-9]+) Results \(([0-9]{4}-[0-9]{2})\)', lead['id'])
        if match is None or f'Sky {match[2]} Round {match[1]}' not in verified:
            unresolved.append(lead)
    return unresolved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rounds', type=int, nargs='+')
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--season', required=True)
    args = parser.parse_args()
    records = []
    for number in dict.fromkeys(args.rounds):
        try:
            payload, capture = sky_capture(number, args.sources)
            if payload['season'] != args.season:
                raise ValueError('Sky now resolves this round number to a different season')
            records.append(historical_record(payload, capture))
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
            parser.exit(1, f'Round {number}: {exc}\n')
    stream = ',\n'.join(json.dumps(r, ensure_ascii=False, separators=(',', ':')) for r in records)
    sys.stdout.write(f'[\n{stream}\n]\n')


if __name__ == '__main__':
    main()
