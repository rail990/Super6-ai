"""Build a populated synthetic dashboard beside the verified historical round."""
import json
from copy import deepcopy
from datetime import datetime, timezone
import sys
from pathlib import Path

from test_system import example

from super6.archive import candidate_index, load_rounds
from super6.capture import freeze
from super6.experiments import study as experiment_study
from super6.prospective import cumulative
from super6.report import report
from super6.sky_history import ARCHIVE, UPCOMING, unresolved_candidates

output = Path(sys.argv[1])
item = example()
for fixture in item['fixtures']:
    base = fixture['research']['form']
    fixture['venue_history'] = {
        side: [dict(base, opponent=f'Synthetic opponent {i}', score=[1, 0],
                    sha256='0' * 64) for i in range(5)]
        for side in ('home', 'away')
    }
    fixture['result']['first_goal'] = dict(fixture['result'], minute=8, url=item['official']['url'])
freeze(item, output / 'snapshots')
archive = load_rounds()
baseline = json.loads(Path('data/baseline.json').read_text())
report_data = report(archive + [item], baseline, output / 'snapshots')
report_data['sky_history'] = json.loads(ARCHIVE.read_text())
report_data['archive_candidates'] = unresolved_candidates(candidate_index(), report_data['sky_history'])
report_data['sky_upcoming'] = json.loads(UPCOMING.read_text())
# Exercise the prospective rendering path with synthetic data only.

synthetic = next(row for row in report_data['rounds'] if row['round']['id'] == 'Synthetic test only')
live_round = deepcopy(synthetic['round'])
live_round['id'] = 'Synthetic prospective round'
live_round['deadline'] = '2026-11-25T20:00:00Z'
for i, fixture in enumerate(live_round['fixtures']):
    fixture['id'] = str(i)
    fixture['kickoff'] = live_round['deadline']
    fixture.pop('result')
report_data['prospective'] = {
    'rounds': [{'round': live_round, 'frozen_at': '2026-11-23T20:00:00Z',
                'predictions': {'fixed_poisson': synthetic['benchmarks']['fixed_poisson']['prediction']},
                'recommended_model': 'fixed_poisson', 'quality_flags': [],
                'missing_research': [], 'golden_goal_rule': 'Confirm staggered kickoff treatment with Sky.'}],
    'summary': {},
}
report_data['experiments'] = experiment_study(archive, datetime(2026, 11, 24, tzinfo=timezone.utc))
historical = report_data['strategy_backtest']
historical['trends'] = {'fixed_poisson': cumulative([
    (row['round']['id'], row['strategies']['fixed_poisson']) for row in historical['rounds']
])}
(output / 'report.json').write_text(json.dumps(report_data))
