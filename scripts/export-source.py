#!/usr/bin/env python3
"""Export only verified public source, never local environments or dependencies."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tarfile

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('output', type=Path, help='new .tar file outside the source tree')
args = parser.parse_args()
destination = args.output.resolve()
if destination == root or root in destination.parents:
    parser.error('output must be outside the source tree')
subprocess.run([sys.executable, str(root / 'scripts/check-baseline.py')], check=True)
lock = json.loads((root / 'UPSTREAM.json').read_text())
manifest = json.loads((root / lock['import_manifest']).read_text())
policy = json.loads((root / lock['customization_policy']).read_text())
paths = set(manifest['imported'])
paths.update(
    addition['path']
    for addition in policy.get('additions', [])
    if addition.get('source_export', False)
)
paths.update(['.dockerignore', '.gitignore', 'README.md', 'UPSTREAM.json',
              'THIRD_PARTY_NOTICES.md', lock['import_manifest'],
              lock['customization_policy'],
              '.github/workflows/ci.yml', 'scripts/check-baseline.py',
              'scripts/check-local.sh', 'scripts/export-source.py'])
with destination.open('xb') as output:
    with tarfile.open(fileobj=output, mode='w') as archive:
        for name in sorted(paths):
            path = root / name
            if path.is_symlink() or not path.is_file():
                raise RuntimeError(f'export requires a regular source file: {name}')
            archive.add(path, arcname=name, recursive=False)
print(f'exported {len(paths)} source files to {destination}')
