"""Launcher safety checks; no database or containers required."""
import importlib.util
from pathlib import Path
import socket
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('launcher', Path(__file__).resolve().parents[2] / 'main.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class LauncherTests(unittest.TestCase):
    def test_launcher_config_is_in_repository_root(self):
        self.assertEqual(launcher.CONFIG_PATH, launcher.ROOT / '.env')
        self.assertNotEqual(launcher.CONFIG_PATH, launcher.ROOT / 'backend/.env')

    def test_dotenv_is_literal_and_handles_quotes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            path.write_text('export SAMPLE="space value"\nLITERAL=$(echo_secret)\nEMPTY=\n')
            env = launcher.load_env(path)
            self.assertEqual(env['SAMPLE'], 'space value')
            self.assertEqual(env['LITERAL'], '$(echo_secret)')
            self.assertEqual(env['EMPTY'], '')

    def test_invalid_dotenv_does_not_expose_value(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            path.write_text('VALUE=private unquoted value\n')
            with self.assertRaisesRegex(ValueError, '^Quote environment value on line 1$'):
                launcher.load_env(path)

    def test_prefers_configured_ports_when_available(self):
        backend, frontend = self.available_port_block()
        with (
            mock.patch.object(launcher, 'PREFERRED_BACKEND_PORT', backend),
            mock.patch.object(launcher, 'PREFERRED_FRONTEND_PORT', frontend),
        ):
            self.assertEqual(launcher.select_ports(), (backend, frontend))

    def test_occupied_backend_uses_fallback_and_preserves_listener(self):
        backend, frontend = self.available_port_block()
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', backend))
            listener.listen()
            with (
                mock.patch.object(launcher, 'PREFERRED_BACKEND_PORT', backend),
                mock.patch.object(launcher, 'PREFERRED_FRONTEND_PORT', frontend),
            ):
                selected_backend, selected_frontend = launcher.select_ports()
            self.assertNotEqual(selected_backend, backend)
            self.assertEqual(selected_frontend, frontend)
            self.assertNotEqual(selected_backend, selected_frontend)
            with socket.create_connection(('127.0.0.1', backend), timeout=1):
                self.assertEqual(listener.getsockname()[1], backend)

    def test_occupied_frontend_uses_fallback_and_preserves_listener(self):
        backend, frontend = self.available_port_block()
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', frontend))
            listener.listen()
            with (
                mock.patch.object(launcher, 'PREFERRED_BACKEND_PORT', backend),
                mock.patch.object(launcher, 'PREFERRED_FRONTEND_PORT', frontend),
            ):
                selected_backend, selected_frontend = launcher.select_ports()
            self.assertEqual(selected_backend, backend)
            self.assertNotEqual(selected_frontend, frontend)
            with socket.create_connection(('127.0.0.1', frontend), timeout=1):
                self.assertEqual(listener.getsockname()[1], frontend)

    def test_both_occupied_ports_get_distinct_fallbacks(self):
        backend, frontend = self.available_port_block()
        with socket.socket() as backend_listener, socket.socket() as frontend_listener:
            backend_listener.bind(('127.0.0.1', backend))
            frontend_listener.bind(('127.0.0.1', frontend))
            with (
                mock.patch.object(launcher, 'PREFERRED_BACKEND_PORT', backend),
                mock.patch.object(launcher, 'PREFERRED_FRONTEND_PORT', frontend),
            ):
                selected_backend, selected_frontend = launcher.select_ports()
            self.assertNotIn(selected_backend, (backend, frontend))
            self.assertNotIn(selected_frontend, (backend, frontend))
            self.assertNotEqual(selected_backend, selected_frontend)

    def test_frontend_environment_receives_selected_ports(self):
        base = {'PATH': '/bin'}
        env = launcher.frontend_environment(base, 19527, 19528)
        self.assertEqual(env['XRAY_BACKEND_PORT'], '19527')
        self.assertEqual(env['XRAY_FRONTEND_PORT'], '19528')
        self.assertEqual(base, {'PATH': '/bin'})

    def test_port_search_exhaustion_is_clear(self):
        with (
            mock.patch.object(launcher, 'MAX_PORT', 19530),
            mock.patch.object(launcher, 'port_is_available', return_value=False),
        ):
            with self.assertRaisesRegex(RuntimeError, 'No available local port from 19527 to 19530'):
                launcher.find_available_port(19527)

    @staticmethod
    def available_port_block(size=4):
        for start in range(20000, 60000 - size):
            listeners = []
            try:
                for port in range(start, start + size):
                    listener = socket.socket()
                    listener.bind(('127.0.0.1', port))
                    listeners.append(listener)
            except OSError:
                continue
            finally:
                for listener in listeners:
                    listener.close()
            if len(listeners) == size:
                return start, start + 1
        raise RuntimeError('Could not find a free local port block for launcher tests.')


if __name__ == '__main__':
    unittest.main()
