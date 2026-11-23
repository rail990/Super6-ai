"""Validate and store a reviewed round JSON record."""
import argparse
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from .evidence import validate


def save(item, archive, replace=False):
    validate(item)
    items = json.loads(archive.read_text()) if archive.exists() else []
    matches = [i for i, row in enumerate(items) if row['id'] == item['id']]
    if len(matches) > 1 or (matches and not replace):
        raise ValueError('Round already exists. Use --replace to update a single reviewed record.')
    if matches:
        items[matches[0]] = item
    else:
        items.append(item)
    # A failed write leaves the existing archive intact.
    temporary = None
    try:
        with NamedTemporaryFile(mode='w', encoding='utf-8', dir=archive.parent,
                                delete=False) as target:
            temporary = Path(target.name)
            json.dump(items, target, indent=2, ensure_ascii=False, allow_nan=False)
            target.write('\n')
        os.replace(temporary, archive)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('round', type=Path)
    parser.add_argument('--archive', type=Path, default=Path('data/rounds.json'))
    parser.add_argument('--replace', action='store_true')
    args = parser.parse_args()
    save(json.loads(args.round.read_text()), args.archive, args.replace)


if __name__ == '__main__':
    main()
