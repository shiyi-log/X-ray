#!/usr/bin/env python3
"""Verify pinned upstream files and explicitly reviewed local patches."""
import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import sys

ROOT = Path(__file__).resolve().parents[1]
ACTIVE_SOURCE_ROOTS = ('frontend/src', 'internal', 'scripts', 'tools')
ACTIVE_SOURCE_SUFFIXES = {'.go', '.js', '.jsx', '.mjs', '.py', '.sh', '.ts', '.tsx'}
IGNORED_SOURCE_DIRS = {'.cache', '.git', '.venv', '__pycache__', 'build', 'dist', 'node_modules'}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check(root: Path) -> list[str]:
    errors = []
    try:
        lock = json.loads((root / 'UPSTREAM.json').read_text())
        manifest_path = lock['import_manifest']
        manifest_bytes = (root / manifest_path).read_bytes()
        manifest = json.loads(manifest_bytes)
    except (OSError, ValueError, KeyError) as exc:
        return [f'cannot read upstream lock/manifest: {type(exc).__name__}']

    if sha256(manifest_bytes) != lock.get('import_manifest_sha256'):
        errors.append('import manifest differs from the pinned hash')
    if manifest['upstream']['commit'] != lock.get('commit'):
        errors.append('upstream commit differs from import manifest')

    policy_path = lock.get('customization_policy')
    policy_hash = lock.get('customization_policy_sha256')
    if not policy_path or not policy_hash:
        errors.append('reviewed customization policy is not locked in UPSTREAM.json')
        policy = {'patches': []}
    else:
        try:
            policy_bytes = (root / policy_path).read_bytes()
            policy = json.loads(policy_bytes)
        except (OSError, ValueError) as exc:
            errors.append(f'cannot read customization policy: {type(exc).__name__}')
            policy_bytes = b''
            policy = {'patches': []}
        if policy_bytes and sha256(policy_bytes) != policy_hash:
            errors.append('customization policy differs from the pinned hash')

    if policy.get('schema_version') != 1:
        errors.append('unsupported customization policy schema')
    if policy.get('upstream_commit') != lock.get('commit'):
        errors.append('customization policy upstream commit differs from UPSTREAM.json')

    patches = {}
    for patch in policy.get('patches', []):
        name = patch.get('path')
        if not isinstance(name, str) or name in patches:
            errors.append('customization policy contains an invalid or duplicate path')
            continue
        patches[name] = patch

    imported = manifest['imported']
    excluded_imported = manifest.get('excluded_imported', {})
    excluded_reasons = manifest.get('excluded_imported_reasons', {})
    if not isinstance(excluded_imported, dict) or not isinstance(excluded_reasons, dict):
        errors.append('excluded upstream records must be objects')
        excluded_imported = {}
        excluded_reasons = {}
    for name, upstream_hash in excluded_imported.items():
        if name in imported:
            errors.append(f'excluded upstream file is also imported: {name}')
        if not isinstance(name, str) or not isinstance(upstream_hash, str) or len(upstream_hash) != 64:
            errors.append(f'invalid excluded upstream hash: {name}')
        elif any(character not in '0123456789abcdef' for character in upstream_hash):
            errors.append(f'invalid excluded upstream hash: {name}')
        reason = excluded_reasons.get(name)
        if not isinstance(reason, str) or not reason.strip():
            errors.append(f'excluded upstream reason is missing: {name}')
    for name in excluded_reasons:
        if name not in excluded_imported:
            errors.append(f'excluded upstream reason has no hash record: {name}')
    for name, upstream_hash in imported.items():
        override = manifest.get('local_overrides', {}).get(name)
        patch = patches.pop(name, None)
        expected = upstream_hash
        if override:
            if override['upstream_sha256'] != upstream_hash:
                errors.append(f'override lost its upstream hash: {name}')
            expected = override['local_sha256']
        if patch:
            if patch.get('upstream_sha256') != expected:
                errors.append(f'customization upstream hash differs from import manifest: {name}')
            if not patch.get('reason', '').strip():
                errors.append(f'customization has no review reason: {name}')
            local_hash = patch.get('local_sha256')
            if local_hash is not None and local_hash == expected:
                errors.append(f'customization does not change the upstream file: {name}')
            if local_hash is None:
                if (root / name).exists() or (root / name).is_symlink():
                    errors.append(f'reviewed deletion is present in the worktree: {name}')
                continue
            expected = local_hash
        path = root / name
        if path.is_symlink() or not path.is_file():
            errors.append(f'missing or symbolic upstream file: {name}')
        elif sha256(path.read_bytes()) != expected:
            if patch:
                errors.append(f'reviewed customization hash differs: {name}')
            else:
                errors.append(f'upstream baseline changed and is not covered by customization policy: {name}')

    for name in patches:
        if name not in imported:
            errors.append(f'customization path is not an imported file: {name}')

    additions = {}
    for addition in policy.get('additions', []):
        name = addition.get('path')
        if not isinstance(name, str) or name in additions or name in imported:
            errors.append('customization policy contains an invalid or duplicate addition path')
            continue
        relative = PurePosixPath(name)
        if relative.is_absolute() or not name or any(part in {'', '.', '..'} for part in relative.parts) or '\\' in name:
            errors.append(f'customization policy contains an invalid path: {name}')
            continue
        if not isinstance(addition.get('build_context', False), bool) or not isinstance(addition.get('source_export', False), bool):
            errors.append(f'customization policy has invalid source inclusion flags: {name}')
            continue
        additions[name] = addition
        if not addition.get('reason', '').strip():
            errors.append(f'addition has no review reason: {name}')
        path = root / name
        if path.is_symlink() or not path.is_file():
            errors.append(f'reviewed addition is missing or symbolic: {name}')
        elif sha256(path.read_bytes()) != addition.get('local_sha256'):
            errors.append(f'reviewed addition hash differs: {name}')

    for source_root in ACTIVE_SOURCE_ROOTS:
        scan_root = root / source_root
        if not scan_root.is_dir():
            continue
        for current, dirs, files in os.walk(scan_root):
            dirs[:] = sorted(d for d in dirs if d not in IGNORED_SOURCE_DIRS)
            for filename in files:
                path = Path(current) / filename
                if path.suffix not in ACTIVE_SOURCE_SUFFIXES:
                    continue
                name = path.relative_to(root).as_posix()
                if name not in imported and name not in additions:
                    errors.append(f'unreviewed active source file: {name}')

    for name in manifest['removed']:
        if name not in imported and name not in {'.github/workflows/ci.yml', 'scripts/check-local.sh', 'scripts/check-boundary.sh', 'scripts/check-secrets.sh'}:
            if (root / name).exists():
                errors.append(f'retired source still active: {name}')
    workflows = sorted(p.name for p in (root / '.github/workflows').glob('*.y*ml'))
    if workflows != ['ci.yml']:
        errors.append('only the local verification CI may be active')
    rules = (root / '.dockerignore').read_text().splitlines()
    allowed = {line[1:].replace('\\[', '[').replace('\\]', ']') for line in rules if line.startswith('!') and not line.endswith('/')}
    build_sources = set(imported)
    for name, addition in additions.items():
        if addition.get('build_context', False):
            build_sources.add(name)
    if '**' not in rules or allowed != build_sources:
        errors.append('Docker context differs from explicit imported source allowlist')

    return errors


def main() -> int:
    errors = check(ROOT)
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        return 1
    manifest = json.loads((ROOT / json.loads((ROOT / 'UPSTREAM.json').read_text())['import_manifest']).read_text())
    print(f"baseline passed: {len(manifest['imported'])} upstream files; reviewed patches, retired source and build context checked")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
