#!/usr/bin/env python3
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest


class SourceExportTests(unittest.TestCase):
    def test_export_contains_the_locked_customization_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / 'scripts'
            scripts.mkdir()
            (scripts / 'export-source.py').write_bytes(
                (Path(__file__).parent / 'export-source.py').read_bytes()
            )
            (scripts / 'check-baseline.py').write_text('raise SystemExit(0)\n')
            (root / 'source.go').write_text('package source\n')
            (root / 'application.go').write_text('package application\n')
            (root / 'isolated.go').write_text('package isolated\n')
            policy_dir = root / 'artifacts' / 'acceptance' / '3x-ui-rebase-20261117'
            policy_dir.mkdir(parents=True)
            (policy_dir / 'replacement-manifest.json').write_text(
                json.dumps({
                    'imported': {'source.go': 'hash'},
                    'excluded_imported': {'media/token.png': 'sensitive-hash'},
                })
            )
            (policy_dir / 'customization-policy.json').write_text(
                json.dumps({'schema_version': 1})
            )
            (root / 'UPSTREAM.json').write_text(
                json.dumps(
                    {
                        'import_manifest': 'artifacts/acceptance/3x-ui-rebase-20261117/replacement-manifest.json',
                        'customization_policy': 'artifacts/acceptance/3x-ui-rebase-20261117/customization-policy.json',
                    }
                )
            )
            policy_dir = root / 'artifacts' / 'acceptance' / '3x-ui-rebase-20261117'
            (policy_dir / 'customization-policy.json').write_text(
                json.dumps(
                    {
                        'schema_version': 1,
                        'additions': [
                            {'path': 'application.go', 'source_export': True},
                            {'path': 'isolated.go', 'source_export': False},
                        ],
                    }
                )
            )
            for path in (
                '.dockerignore',
                '.gitignore',
                'README.md',
                'THIRD_PARTY_NOTICES.md',
                '.github/workflows/ci.yml',
                'scripts/check-local.sh',
            ):
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('fixture\n')

            output = root.parent / f'{root.name}.tar'
            try:
                subprocess.run(
                    [sys.executable, str(scripts / 'export-source.py'), str(output)],
                    check=True,
                )
                with tarfile.open(output) as archive:
                    names = set(archive.getnames())
                self.assertIn(
                    'artifacts/acceptance/3x-ui-rebase-20261117/customization-policy.json',
                    names,
                )
                self.assertIn('application.go', names)
                self.assertNotIn('isolated.go', names)
                self.assertNotIn('media/token.png', names)
            finally:
                output.unlink(missing_ok=True)


if __name__ == '__main__':
    unittest.main()
