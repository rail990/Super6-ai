"""Build a populated synthetic dashboard beside the verified historical round."""
import json
import sys
from pathlib import Path

from test_system import example

from super6.capture import freeze
from super6.report import report

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
archive = json.loads(Path('data/rounds.json').read_text())
baseline = json.loads(Path('data/baseline.json').read_text())
report_data = report(archive + [item], baseline, output / 'snapshots')
(output / 'report.json').write_text(json.dumps(report_data))
