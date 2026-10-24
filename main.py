#!/usr/bin/env python3
"""Start the local X-ray backend and frontend; stop owned children on Ctrl+C."""
from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
from typing import Optional
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / '.env'
PREFERRED_BACKEND_PORT = 9527
PREFERRED_FRONTEND_PORT = 9528
MAX_PORT = 65535


def load_env(path: Path) -> dict[str, str]:
    """Read literal dotenv assignments without shell execution or interpolation."""
    result = dict(os.environ)
    for number, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:].strip()
        key, separator, value = line.partition('=')
        if not separator or not key.strip().isidentifier():
            raise ValueError(f'Invalid environment assignment on line {number}')
        tokens = shlex.split(value, comments=True)
        if len(tokens) > 1:
            raise ValueError(f'Quote environment value on line {number}')
        result[key.strip()] = tokens[0] if tokens else ''
    return result


def port_is_available(port: int) -> bool:
    with socket.socket() as listener:
        try:
            listener.bind(('127.0.0.1', port))
        except OSError:
            return False
    return True


def find_available_port(start: int, excluded: Optional[set[int]] = None) -> int:
    excluded = excluded or set()
    for port in range(start, MAX_PORT + 1):
        if port not in excluded and port_is_available(port):
            return port
    raise RuntimeError(f'No available local port from {start} to {MAX_PORT}.')


def select_ports() -> tuple[int, int]:
    """Keep the browser's preferred port when only the backend port is busy."""
    frontend_port = find_available_port(PREFERRED_FRONTEND_PORT)
    backend_port = find_available_port(
        PREFERRED_BACKEND_PORT,
        excluded={frontend_port},
    )
    return backend_port, frontend_port


def frontend_environment(base: dict[str, str], backend_port: int, frontend_port: int) -> dict[str, str]:
    result = dict(base)
    result['XRAY_BACKEND_PORT'] = str(backend_port)
    result['XRAY_FRONTEND_PORT'] = str(frontend_port)
    return result


def stop_children(children: list[subprocess.Popen]) -> None:
    for child in children:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    for child in children:
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()


def main() -> int:
    children: list[subprocess.Popen] = []
    try:
        config = CONFIG_PATH
        if not config.exists():
            raise RuntimeError('Missing root .env; follow docs/development.md first.')
        env = load_env(config)
        if env.get('XRAY_ENV') != 'test' or env.get('DJANGO_SETTINGS_MODULE') != 'config.settings.test':
            raise RuntimeError('This launcher requires the isolated test settings in root .env.')
        # PyCharm may have a smaller PATH than the terminal. Include installed tools.
        paths = [ROOT / '.local-tools/bin', Path('/opt/homebrew/bin'),
                 Path.home() / '.local/bin',
                 Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin']
        env['PATH'] = os.pathsep.join(str(p) for p in paths if p.is_dir()) + os.pathsep + env.get('PATH', '')
        python = ROOT / 'backend/.venv/bin/python'
        pnpm = shutil.which('pnpm', path=env['PATH'])
        if not python.exists() or not pnpm or not (ROOT / 'frontend/node_modules').is_dir():
            raise RuntimeError('Install backend and frontend dependencies first; see docs/development.md.')
        compose = shutil.which('docker-compose', path=env['PATH'])
        docker = shutil.which('docker', path=env['PATH'])
        command = [compose] if compose else [docker, 'compose'] if docker else None
        if command is None:
            raise RuntimeError('Docker Compose is required; start Docker Desktop or Colima first.')
        # Do not pass application secrets to the dependency containers or Vite.
        tool_env = dict(os.environ, PATH=env['PATH'])
        subprocess.run(command + ['-p', 'xray-test', '-f', 'deploy/compose/test.yml',
                                  'up', '-d', '--wait'], cwd=ROOT, env=tool_env, check=True)
        subprocess.run([str(python), 'backend/manage.py', 'migrate', '--check'],
                       cwd=ROOT, env=env, check=True)
        subprocess.run([str(python), 'backend/manage.py', 'sync_env_superadmin'],
                       cwd=ROOT, env=env, check=True)
        backend_port, frontend_port = select_ports()
        # The selected local browser origin must match the backend's CSRF allowlist.
        env['XRAY_CSRF_TRUSTED_ORIGINS'] = f'http://127.0.0.1:{frontend_port}'
        frontend_env = frontend_environment(tool_env, backend_port, frontend_port)
        commands = [
            ([str(python), 'backend/manage.py', 'runserver', f'127.0.0.1:{backend_port}', '--noreload'], env),
            ([pnpm, '--dir', 'frontend', 'dev'], frontend_env),
        ]
        for args, child_env in commands:
            children.append(subprocess.Popen(args, cwd=ROOT, env=child_env, start_new_session=True))
        pending = {
            f'http://127.0.0.1:{backend_port}/health/ready',
            f'http://127.0.0.1:{frontend_port}/api/v1/auth/session',
        }
        deadline = time.monotonic() + 60
        while pending:
            if any(child.poll() is not None for child in children):
                raise RuntimeError('A development server exited during startup.')
            if time.monotonic() >= deadline:
                raise RuntimeError('Development servers did not become ready within 60 seconds.')
            for url in tuple(pending):
                try:
                    with urlopen(url, timeout=1) as response:
                        if response.status == 200:
                            pending.remove(url)
                except (OSError, ValueError):
                    pass
            time.sleep(0.2)
        print(
            f'\nX-ray ready: http://127.0.0.1:{frontend_port}/ '
            f'(backend http://127.0.0.1:{backend_port}/) — Ctrl+C stops both servers.',
            flush=True,
        )
        while all(child.poll() is None for child in children):
            time.sleep(0.5)
        raise RuntimeError('A development server exited; stopping its companion.')
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        # Never echo subprocess output, environment values, or secret-bearing exceptions.
        if isinstance(error, (ValueError, RuntimeError)):
            print(f'Startup failed: {error}', file=sys.stderr)
        else:
            print('Startup failed. Check tool availability, Compose health and pending migrations.', file=sys.stderr)
        return 1
    finally:
        stop_children(children)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    sys.exit(main())
