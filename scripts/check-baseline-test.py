#!/usr/bin/env python3
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


CHECKER_PATH = Path(__file__).with_name('check-baseline.py')
SPEC = importlib.util.spec_from_file_location('check_baseline', CHECKER_PATH)
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class BaselinePolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.imported_content = b'upstream source\n'
        (self.root / 'source.go').write_bytes(self.imported_content)
        (self.root / '.dockerignore').write_text('**\n!source.go\n')
        (self.root / '.github' / 'workflows').mkdir(parents=True)
        (self.root / '.github' / 'workflows' / 'ci.yml').write_text('name: ci\n')
        policy_dir = self.root / 'artifacts' / 'acceptance' / '3x-ui-rebase-20261117'
        policy_dir.mkdir(parents=True)
        manifest = {
            'upstream': {'commit': 'abc123'},
            'imported': {'source.go': sha256(self.imported_content)},
            'local_overrides': {},
            'removed': {},
        }
        (policy_dir / 'replacement-manifest.json').write_text(json.dumps(manifest))
        upstream = {
            'import_manifest': 'artifacts/acceptance/3x-ui-rebase-20261117/replacement-manifest.json',
            'import_manifest_sha256': sha256((policy_dir / 'replacement-manifest.json').read_bytes()),
            'commit': 'abc123',
        }
        (self.root / 'UPSTREAM.json').write_text(json.dumps(upstream))
        policy = {'schema_version': 1, 'upstream_commit': 'abc123', 'patches': []}
        self.write_policy(policy)

    def tearDown(self):
        self.temp.cleanup()

    def write_policy(self, policy):
        policy_path = self.root / 'artifacts/acceptance/3x-ui-rebase-20261117/customization-policy.json'
        policy_bytes = json.dumps(policy).encode()
        policy_path.write_bytes(policy_bytes)
        upstream_path = self.root / 'UPSTREAM.json'
        upstream = json.loads(upstream_path.read_text())
        upstream['customization_policy'] = str(policy_path.relative_to(self.root))
        upstream['customization_policy_sha256'] = sha256(policy_bytes)
        upstream_path.write_text(json.dumps(upstream))

    def test_unchanged_upstream_source_passes_with_empty_patch_policy(self):
        self.assertEqual(CHECKER.check(self.root), [])

    def test_reviewed_patch_passes_when_upstream_and_local_hashes_match(self):
        path = self.root / 'source.go'
        local = b'approved source change\n'
        path.write_bytes(local)
        manifest_path = self.root / 'artifacts/acceptance/3x-ui-rebase-20261117/replacement-manifest.json'
        manifest = json.loads(manifest_path.read_text())
        upstream_hash = manifest['imported']['source.go']
        policy = {
            'schema_version': 1,
            'upstream_commit': 'abc123',
            'patches': [{
                'path': 'source.go',
                'upstream_sha256': upstream_hash,
                'local_sha256': sha256(local),
                'reason': 'test approved behavior change',
            }],
        }
        self.write_policy(policy)
        self.assertEqual(CHECKER.check(self.root), [])

    def test_unlisted_upstream_change_is_rejected(self):
        (self.root / 'source.go').write_bytes(b'unreviewed source change\n')
        errors = CHECKER.check(self.root)
        self.assertTrue(any('source.go' in error and 'not covered' in error for error in errors), errors)

    def test_reviewed_patch_hash_drift_is_rejected(self):
        path = self.root / 'source.go'
        local = b'approved source change\n'
        path.write_bytes(local)
        manifest_path = self.root / 'artifacts/acceptance/3x-ui-rebase-20261117/replacement-manifest.json'
        manifest = json.loads(manifest_path.read_text())
        self.write_policy({
            'schema_version': 1,
            'upstream_commit': 'abc123',
            'patches': [{
                'path': 'source.go',
                'upstream_sha256': manifest['imported']['source.go'],
                'local_sha256': sha256(b'different reviewed source\n'),
                'reason': 'test approved behavior change',
            }],
        })
        errors = CHECKER.check(self.root)
        self.assertTrue(any('source.go' in error and 'hash differs' in error for error in errors), errors)

    def test_policy_cannot_approve_a_non_imported_file(self):
        manifest_path = self.root / 'artifacts/acceptance/3x-ui-rebase-20261117/replacement-manifest.json'
        self.write_policy({
            'schema_version': 1,
            'upstream_commit': 'abc123',
            'patches': [{
                'path': 'extra.go',
                'upstream_sha256': '0' * 64,
                'local_sha256': '1' * 64,
                'reason': 'must be rejected',
            }],
        })
        errors = CHECKER.check(self.root)
        self.assertTrue(any('extra.go' in error and 'not an imported file' in error for error in errors), errors)

    def test_reviewed_deletion_passes_when_source_file_is_absent(self):
        (self.root / 'source.go').unlink()
        self.write_policy({
            'schema_version': 1,
            'upstream_commit': 'abc123',
            'patches': [{
                'path': 'source.go',
                'upstream_sha256': sha256(self.imported_content),
                'local_sha256': None,
                'reason': 'remove a retired network integration',
            }],
        })
        self.assertEqual(CHECKER.check(self.root), [])

    def test_reviewed_deletion_fails_if_file_reappears(self):
        (self.root / 'source.go').unlink()
        self.write_policy({
            'schema_version': 1,
            'upstream_commit': 'abc123',
            'patches': [{
                'path': 'source.go',
                'upstream_sha256': sha256(self.imported_content),
                'local_sha256': None,
                'reason': 'remove a retired network integration',
            }],
        })
        (self.root / 'source.go').write_bytes(b'reintroduced source\n')
        errors = CHECKER.check(self.root)
        self.assertTrue(any('source.go' in error and 'reviewed deletion' in error for error in errors), errors)

    def test_reviewed_addition_passes_when_hash_matches(self):
        added = b'local verification source\n'
        (self.root / 'test.py').write_bytes(added)
        (self.root / '.dockerignore').write_text('**\n!source.go\n!test.py\n')
        self.write_policy({
            'schema_version': 1,
            'upstream_commit': 'abc123',
            'patches': [],
            'additions': [{
                'path': 'test.py',
                'local_sha256': sha256(added),
                'reason': 'verify reviewed baseline customization policy',
                'build_context': True,
            }],
        })
        self.assertEqual(CHECKER.check(self.root), [])

    def test_build_context_requires_exact_policy_allowlist(self):
        added = b'local application source\n'
        (self.root / 'application.go').write_bytes(added)
        self.write_policy({
            'schema_version': 1,
            'upstream_commit': 'abc123',
            'patches': [],
            'additions': [{
                'path': 'application.go',
                'local_sha256': sha256(added),
                'reason': 'ship reviewed local application source',
                'build_context': True,
            }],
        })
        errors = CHECKER.check(self.root)
        self.assertTrue(any('Docker context' in error for error in errors), errors)

    def test_non_build_addition_does_not_enter_docker_context(self):
        added = b'isolated lifecycle writer\n'
        (self.root / 'writer.go').write_bytes(added)
        self.write_policy({
            'schema_version': 1,
            'upstream_commit': 'abc123',
            'patches': [],
            'additions': [{
                'path': 'writer.go',
                'local_sha256': sha256(added),
                'reason': 'isolated pending an explicit write gate',
                'build_context': False,
                'source_export': False,
            }],
        })
        self.assertEqual(CHECKER.check(self.root), [])

    def test_reviewed_addition_cannot_escape_repository_root(self):
        self.write_policy({
            'schema_version': 1,
            'upstream_commit': 'abc123',
            'patches': [],
            'additions': [{
                'path': '../outside.py',
                'local_sha256': '0' * 64,
                'reason': 'invalid path',
            }],
        })
        errors = CHECKER.check(self.root)
        self.assertTrue(any('invalid path' in error for error in errors), errors)

    def test_reviewed_addition_hash_drift_is_rejected(self):
        (self.root / 'test.py').write_bytes(b'local verification source\n')
        self.write_policy({
            'schema_version': 1,
            'upstream_commit': 'abc123',
            'patches': [],
            'additions': [{
                'path': 'test.py',
                'local_sha256': sha256(b'different source\n'),
                'reason': 'verify reviewed baseline customization policy',
            }],
        })
        errors = CHECKER.check(self.root)
        self.assertTrue(any('test.py' in error and 'addition hash differs' in error for error in errors), errors)

    def test_unreviewed_active_source_addition_is_rejected(self):
        script = self.root / 'scripts' / 'new-source.py'
        script.parent.mkdir()
        script.write_bytes(b'print("unreviewed")\n')
        self.write_policy({
            'schema_version': 1,
            'upstream_commit': 'abc123',
            'patches': [],
            'additions': [],
        })
        errors = CHECKER.check(self.root)
        self.assertTrue(any('unreviewed active source file' in error for error in errors), errors)

    def test_excluded_imported_asset_is_hash_locked_but_not_required(self):
        excluded = b'sensitive upstream asset\n'
        manifest_path = self.root / 'artifacts/acceptance/3x-ui-rebase-20261117/replacement-manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['excluded_imported'] = {'media/token.png': sha256(excluded)}
        manifest['excluded_imported_reasons'] = {
            'media/token.png': 'Upstream screenshot contains a credential; retain hash evidence without publishing the asset.',
        }
        manifest_path.write_text(json.dumps(manifest))
        upstream_path = self.root / 'UPSTREAM.json'
        upstream = json.loads(upstream_path.read_text())
        upstream['import_manifest_sha256'] = sha256(manifest_path.read_bytes())
        upstream_path.write_text(json.dumps(upstream))
        self.assertEqual(CHECKER.check(self.root), [])

    def test_excluded_imported_asset_requires_hash_and_reason(self):
        manifest_path = self.root / 'artifacts/acceptance/3x-ui-rebase-20261117/replacement-manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['excluded_imported'] = {'media/token.png': 'not-a-hash'}
        manifest['excluded_imported_reasons'] = {'media/token.png': ''}
        manifest_path.write_text(json.dumps(manifest))
        upstream_path = self.root / 'UPSTREAM.json'
        upstream = json.loads(upstream_path.read_text())
        upstream['import_manifest_sha256'] = sha256(manifest_path.read_bytes())
        upstream_path.write_text(json.dumps(upstream))
        errors = CHECKER.check(self.root)
        self.assertTrue(any('excluded upstream hash' in error for error in errors), errors)
        self.assertTrue(any('excluded upstream reason' in error for error in errors), errors)


if __name__ == '__main__':
    unittest.main()
