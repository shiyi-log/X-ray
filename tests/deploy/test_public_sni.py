from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IMAGE = 'nginx@sha256:30f1c0d78e0ad60901648be663a710bdadf19e4c10ac6782c235200619158284'


def test_public_tls_routes_admin_and_subscription_and_rejects_unknown_names(tmp_path):
    # Missing/swapped targets or forwarding unknown names must fail this test.
    template = ROOT / 'deploy/nginx/public-sni.conf.template'
    assert template.is_file(), 'public SNI entry configuration is missing'
    routing = template.read_text()
    for name, value in [('XRAY_PUBLIC_BIND_IP', '127.0.0.2'),
                        ('XRAY_ADMIN_HOST', 'admin.xray.invalid'),
                        ('XRAY_SUBSCRIPTION_HOST', 'sub.xray.invalid')]:
        routing = routing.replace(chr(36) + '{' + name + '}', value)
    certificate, key = tmp_path / 'cert.pem', tmp_path / 'key.pem'
    subprocess.run([
        'openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
        '-keyout', str(key), '-out', str(certificate), '-days', '1',
        '-subj', '/CN=admin.xray.invalid', '-addext',
        'subjectAltName=DNS:admin.xray.invalid,DNS:sub.xray.invalid,DNS:unknown.xray.invalid',
    ], capture_output=True, check=True)
    config = tmp_path / 'nginx.conf'
    config.write_text(
        'events {}\nstream {\n' + routing + '\n}\nhttp {\n'
        'access_log off; error_log /dev/null;\n'
        'server { listen 8443 ssl; server_name admin.xray.invalid; '
        'ssl_certificate /fixture/cert.pem; ssl_certificate_key /fixture/key.pem; '
        'if ($host != admin.xray.invalid) { return 404; } '
        'location / { return 200 admin; } }\n'
        'server { listen 127.0.0.1:443 ssl; server_name sub.xray.invalid; '
        'ssl_certificate /fixture/cert.pem; ssl_certificate_key /fixture/key.pem; '
        'if ($host != sub.xray.invalid) { return 404; } '
        'location / { return 200 subscription; } }\n}\n'
    )
    script = r'''
set -eu
nginx -t -c /fixture/nginx.conf
nginx -c /fixture/nginx.conf
for name in admin sub; do
  result=$(curl --max-time 3 --noproxy '*' --cacert /fixture/cert.pem \
    --resolve "$name.xray.invalid:443:127.0.0.2" \
    --silent --show-error --write-out '|%{http_code}' "https://$name.xray.invalid/")
  printf '%s=%s\n' "$name" "$result"
done
curl --max-time 3 --noproxy '*' --cacert /fixture/cert.pem \
  --resolve admin.xray.invalid:443:127.0.0.2 -H 'Host: sub.xray.invalid' \
  --silent --output /dev/null --write-out 'mismatch=%{http_code}\n' https://admin.xray.invalid/
if curl --max-time 3 --noproxy '*' --cacert /fixture/cert.pem \
  --resolve unknown.xray.invalid:443:127.0.0.2 --silent --output /dev/null \
  https://unknown.xray.invalid/; then exit 93; fi
printf 'unknown=rejected\n'
'''
    result = subprocess.run([
        'docker', 'run', '--rm', '--network', 'none',
        '--mount', f'type=bind,src={tmp_path},dst=/fixture,readonly',
        '--entrypoint', 'sh', IMAGE, '-ec', script,
    ], capture_output=True, text=True, timeout=25)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'admin=admin|200' in result.stdout.splitlines()
    assert 'sub=subscription|200' in result.stdout.splitlines()
    assert 'mismatch=404' in result.stdout.splitlines()
    assert 'unknown=rejected' in result.stdout.splitlines()
