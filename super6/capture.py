"""Freeze a reviewed pre-deadline record and check research coverage."""
import argparse
import hashlib
import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from .evidence import RESEARCH, ready, timestamp, validate, verified_snapshot


def prematch(item):
    return {
        'id': item['id'], 'deadline': item['deadline'], 'official': item['official'],
        **({'deadline_basis': item['deadline_basis']} if 'deadline_basis' in item else {}),
        'fixtures': [
            {key: fixture[key] for key in ('home', 'away', 'kickoff', 'research') if key in fixture}
            for fixture in item['fixtures']
        ],
    }


def missing(item):
    return [
        {'fixture': f"{f['home']} vs {f['away']}",
         'missing': sorted(set(RESEARCH) - set(f.get('research', {})))}
        for f in item['fixtures'] if not ready(f)
    ]


def payload(item):
    return (json.dumps(prematch(item), sort_keys=True, ensure_ascii=False, allow_nan=False,
                       indent=2) + '\n').encode('utf-8')


def snapshot_path(item, directory):
    return directory / (hashlib.sha256(payload(item)).hexdigest() + '.json')


def validate_capture(item):
    validate(item)
    deadline = timestamp(item['deadline'])
    if not item.get('deadline_basis', '').strip():
        raise ValueError('Record the official entry deadline and its source in deadline_basis')
    verified_snapshot(item['official'], deadline)
    for fixture in item['fixtures']:
        for evidence in fixture.get('research', {}).values():
            verified_snapshot(evidence, deadline)


def freeze(item, directory, evidence_directory=None):
    validate_capture(item)
    if evidence_directory is not None:
        records = [item['official']]
        for fixture in item['fixtures']:
            records.extend(fixture.get('research', {}).values())
        for digest in {record['source_sha256'] for record in records}:
            path = evidence_directory / digest
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError(f'Captured source is missing or has changed: {digest}')
    directory.mkdir(parents=True, exist_ok=True)
    path = snapshot_path(item, directory)
    data = payload(item)
    # Publish the complete file in one step without overwriting an earlier capture.
    with NamedTemporaryFile(dir=directory) as target:
        target.write(data)
        target.flush()
        try:
            path.hardlink_to(target.name)
        except FileExistsError:
            if path.read_bytes() != data:
                raise ValueError(f'Existing snapshot has unexpected contents: {path}')
    return path


def frozen(item, directory):
    path = snapshot_path(item, directory)
    if not path.exists():
        return False
    if path.read_bytes() != payload(item):
        raise ValueError(f'Snapshot digest mismatch: {path}')
    validate_capture(item)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('round', type=Path)
    parser.add_argument('--freeze', action='store_true')
    parser.add_argument('--evidence-directory', type=Path, help='Source files named by SHA-256')
    parser.add_argument('--directory', type=Path, default=Path('data/snapshots'))
    args = parser.parse_args()
    item = json.loads(args.round.read_text())
    validate(item)
    print(json.dumps(missing(item), indent=2))
    if args.freeze:
        if args.evidence_directory is None:
            parser.error('--freeze requires --evidence-directory')
        print(freeze(item, args.directory, args.evidence_directory))


if __name__ == '__main__':
    main()
