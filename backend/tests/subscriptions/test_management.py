from datetime import timedelta
from uuid import uuid4

import pytest
from django.test import Client, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.identity.models import SuperAdmin
from apps.nodes.models import NodeProtocol
from apps.subscriptions.access import AccessService, build_node_config
from apps.subscriptions.credentials import CredentialService
from apps.subscriptions.models import AccessProfile
from apps.subscriptions.policy import UsageService, quota_state, update_policy
from apps.subscriptions.publishing import Publisher
from apps.subscriptions.tokens import TokenService


@pytest.fixture
def authenticated(db):
    admin = SuperAdmin.objects.first() or SuperAdmin.objects.create_superuser(
        "owner", "test-only-password"
    )
    client = APIClient()
    session = client.session
    session.update(
        dict(
            admin_id=str(admin.pk),
            session_version=admin.session_version,
            absolute_expires_at=(timezone.now() + timedelta(hours=1)).isoformat(),
            recent_auth_until=(timezone.now() + timedelta(minutes=5)).isoformat(),
        )
    )
    session.save()
    return client, admin


def write(client, path, body, key=None, method="post"):
    return getattr(client, method)(
        path, body, format="json", HTTP_IDEMPOTENCY_KEY=str(key or uuid4())
    )


@pytest.mark.django_db
def test_profile_creation_accepts_name_only_and_is_unlimited(authenticated):
    client, _ = authenticated
    key = uuid4()
    payload = {"name": "phone"}
    first = write(client, "/api/v1/access-profiles/", payload, key)
    again = write(client, "/api/v1/access-profiles/", payload, key)
    assert first.status_code == again.status_code == 201
    assert first.json()["id"] == again.json()["id"]
    assert first.json()["plan_id"] is None
    assert first.json()["traffic_limit_bytes"] is None
    assert first.json()["expires_at"] is None
    assert first.json()["usage_updated_at"] is None
    assert write(client, "/api/v1/access-profiles/", {"name": "other"}, key).status_code == 409
    path = f"/api/v1/access-profiles/{first.json()['id']}/"
    for unsupported in (
        {"plan_id": "00000000-0000-0000-0000-000000000001"},
        {"traffic_limit_bytes": 1},
        {"expires_at": "2030-01-01T00:00:00+08:00"},
    ):
        assert write(client, path, unsupported, method="patch").status_code == 400
    assert write(client, path, {"upload_bytes": 1}, method="patch").status_code == 400
    renamed = write(client, path, {"name": "phone-renamed"}, method="patch")
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "phone-renamed"


@pytest.mark.django_db
def test_assignment_without_protocol_ids_includes_all_publishable_protocols(
    ready_node, authenticated
):
    client, _admin = authenticated
    profile = AccessProfile.objects.create(name="all-protocols")
    issued = TokenService.issue(profile.pk)
    first = NodeProtocol.objects.create(node=ready_node, protocol="vless", port=18443)
    second = NodeProtocol.objects.create(node=ready_node, protocol="vmess", port=18444)

    response = write(
        client,
        f"/api/v1/subscriptions/{issued.subscription_id}/assign/",
        {},
    )

    assert response.status_code == 202
    assert set(profile.node_credentials.values_list("protocol_id", flat=True)) == {
        first.pk,
        second.pk,
    }


@pytest.mark.django_db
def test_issue_assigns_all_publishable_protocols_without_protocol_ui(ready_node, authenticated):
    client, _admin = authenticated
    first = NodeProtocol.objects.create(node=ready_node, protocol="vless", port=18445)
    second = NodeProtocol.objects.create(node=ready_node, protocol="vmess", port=18446)
    profile = AccessProfile.objects.create(name="issued-all-protocols")

    response = write(
        client,
        f"/api/v1/access-profiles/{profile.pk}/subscription/",
        {},
    )

    assert response.status_code == 201
    profile.refresh_from_db()
    assert set(profile.node_credentials.values_list("protocol_id", flat=True)) == {
        first.pk,
        second.pk,
    }
    assert profile.node_credentials.filter(revoked_at__isnull=True).count() == 2


@pytest.mark.django_db
def test_issue_rolls_back_token_when_default_protocol_assignment_fails(authenticated, monkeypatch):
    from apps.subscriptions.delivery import DeliveryService
    from apps.subscriptions.models import SecretDeliveryReceipt, Subscription, SubscriptionToken
    from common.errors import DomainError

    _client, admin = authenticated
    profile = AccessProfile.objects.create(name="assignment-rollback")

    def fail(_profile_id, *, protocol_ids, **_kwargs):
        assert protocol_ids is None
        raise DomainError("ASSIGNMENT_FAILED", "协议分配失败", status_code=409)

    monkeypatch.setattr(
        "apps.subscriptions.access.AccessService.assign", staticmethod(fail)
    )
    with pytest.raises(DomainError, match="协议分配失败"):
        DeliveryService.issue(profile.pk, admin=admin)

    assert not Subscription.objects.filter(profile=profile).exists()
    assert not SubscriptionToken.objects.filter(subscription__profile=profile).exists()
    assert not SecretDeliveryReceipt.objects.filter(subscription__profile=profile).exists()


@pytest.mark.django_db
def test_legacy_expiry_and_quota_fields_do_not_block_active_profile():
    now = timezone.now()
    profile = AccessProfile(name="expiry", expires_at=now, traffic_limit_bytes=100)
    assert quota_state(profile, now=now - timedelta(microseconds=1)) == "ACTIVE"
    profile.upload_bytes, profile.download_bytes = 40, 60
    assert quota_state(profile, now=now) == "ACTIVE"
    assert quota_state(profile, now=now + timedelta(microseconds=1)) == "ACTIVE"
    profile.status = "REVOKED"
    with pytest.raises(Exception) as exc_info:
        update_policy(profile, {"name": "renamed"})
    assert exc_info.value.code == "PROFILE_NOT_ACTIVE"


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="config.subscription_urls")
def test_legacy_expiry_does_not_block_public_download_but_revoked_stays_410(
    publishable_subscription,
):
    issued, subscription, _, _ = publishable_subscription
    Publisher.publish(subscription.pk)
    profile = subscription.profile
    profile.expires_at = timezone.now()
    profile.save()
    assert Client().get(f"/s/{issued.raw_token}?format=clash").status_code == 200
    TokenService.disable(subscription.pk)
    assert Client().get(f"/s/{issued.raw_token}?format=clash").status_code == 410


@pytest.mark.django_db
def test_usage_retries_resets_stale_samples_and_epoch(publishable_subscription):
    _, subscription, node, _ = publishable_subscription
    profile = subscription.profile
    at = timezone.now()

    def record(epoch, sequence, up, down):
        UsageService.record(
            node,
            epoch=epoch,
            sequence=sequence,
            samples={str(profile.pk): (up, down)},
            sampled_at=at,
        )

    record("boot:1", 1, 30, 70)
    record("boot:1", 1, 30, 70)
    record("boot:1", 2, 40, 80)
    record("boot:1", 1, 1, 1)
    profile.refresh_from_db()
    assert (profile.upload_bytes, profile.download_bytes) == (40, 80)
    with pytest.raises(ValueError):
        record("boot:1", 3, 1, 1)
    record("boot:2", 1, 5, 10)
    profile.refresh_from_db()
    assert (profile.upload_bytes, profile.download_bytes) == (45, 90)
    assert profile.usage_updated_at == at
    outsider = AccessProfile.objects.create(name="outsider")
    with pytest.raises(ValueError):
        UsageService.record(
            node, epoch="x", sequence=1, samples={str(outsider.pk): (1, 1)}, sampled_at=at
        )


@pytest.mark.django_db
def test_assignment_pending_until_apply_and_no_shared_or_foreign_protocols(
    ready_node, authenticated
):
    client, admin = authenticated
    profile = AccessProfile.objects.create(name="assigned")
    issued = TokenService.issue(profile.pk)
    protocol = NodeProtocol.objects.create(node=ready_node, protocol="vless", port=18443)
    payload = {"protocol_ids": [str(protocol.pk)]}
    path = f"/api/v1/subscriptions/{issued.subscription_id}/assign/"
    key = uuid4()
    response = write(client, path, payload, key)
    assert response.status_code == 202
    assert write(client, path, payload, key).json() == response.json()
    with pytest.raises(Exception):
        Publisher.publish(issued.subscription_id)
    captured = []

    class Transport:
        def apply(self, request):
            captured.append(request)
            return {
                "applied_generation": request["generation"],
                "config_test_passed": True,
                "service_restarted": True,
            }

    AccessService.sync(response.json()["operation_ids"][0], transport_factory=lambda _: Transport())
    assert captured[0]["config"]["inbounds"][0]["protocol"] == "vless"
    assert Publisher.publish(issued.subscription_id).usable
    details = client.get(f"/api/v1/subscriptions/{issued.subscription_id}/").json()
    assert details["assignments"][0]["ready"]
    assert "encrypted_material" not in str(details)
    assert "token_digest" not in str(details)
    assert write(client, path, {"protocol_ids": [str(uuid4())]}).status_code == 409


@pytest.mark.django_db
def test_remove_assignment_invalidates_revision_and_applies_empty_access(ready_node, authenticated):
    client, _ = authenticated
    p = AccessProfile.objects.create(name="remove")
    issued = TokenService.issue(p.pk)
    protocol = NodeProtocol.objects.create(node=ready_node, protocol="vmess", port=18443)
    CredentialService.rotate(ready_node.pk, profile_ids=[p.pk], protocol_ids=[protocol.pk])
    response = write(
        client, f"/api/v1/subscriptions/{issued.subscription_id}/assign/", {"protocol_ids": []}
    )
    assert response.status_code == 202
    assert p.node_credentials.filter(revoked_at__isnull=True).count() == 0
    assert len(build_node_config(ready_node)["inbounds"]) == 1  # private stats only


@pytest.mark.django_db
def test_yaml_transport_matches_generated_websocket_and_grpc():
    import yaml

    from apps.subscriptions.renderers import render_subscription

    from .test_formats import endpoint

    for transport in ("ws", "grpc"):
        value = yaml.safe_load(
            render_subscription(
                "mihomo", endpoints=[endpoint("vmess", transport=transport)], public_version="x"
            )
        )["proxies"][0]
        assert value["network"] == transport
        assert value.get("ws-opts") or value.get("grpc-opts")


@pytest.mark.django_db
def test_generated_config_passes_pinned_xray_for_four_non_tls_protocols(ready_node):
    import json
    import subprocess
    import tempfile
    from pathlib import Path

    binary = Path(__file__).resolve().parents[3] / "runtime/xray/v26.3.27/xray"
    if not binary.exists():
        pytest.skip("pinned local Xray binary absent")
    profile = AccessProfile.objects.create(name="runtime-config")
    protocols = [
        NodeProtocol.objects.create(node=ready_node, protocol=name, port=21000 + i)
        for i, name in enumerate(("shadowsocks", "socks5", "vmess", "vless"))
    ]
    CredentialService.rotate(
        ready_node.pk, profile_ids=[profile.pk], protocol_ids=[p.pk for p in protocols]
    )
    config = build_node_config(ready_node)
    with tempfile.TemporaryDirectory() as directory:
        file = Path(directory) / "config.json"
        file.write_text(json.dumps(config))
        file.chmod(0o600)
        checked = subprocess.run(
            [str(binary), "run", "-test", "-config", str(file)], capture_output=True
        )
        assert checked.returncode == 0, "generated config rejected by pinned runtime"


@pytest.mark.django_db
def test_metering_snapshot_rejects_wrong_generation_and_counts_trusted_values(
    publishable_subscription,
):
    from apps.subscriptions.metering import ingest_snapshot

    _, subscription, node, _ = publishable_subscription
    snapshot = {
        "generation": node.applied_generation,
        "boot_id": "boot",
        "process_id": "123",
        "sequence": 1,
        "sampled_at": timezone.now().isoformat(),
        "stat": [
            {
                "name": f"user>>>profile-{subscription.profile_id}>>>traffic>>>uplink",
                "value": "100",
            },
            {
                "name": f"user>>>profile-{subscription.profile_id}>>>traffic>>>downlink",
                "value": "200",
            },
        ],
    }
    assert ingest_snapshot(node, snapshot) == 1
    ingest_snapshot(node, snapshot)
    subscription.profile.refresh_from_db()
    assert subscription.profile.upload_bytes == 100
    assert subscription.profile.download_bytes == 200
    snapshot["generation"] += 1
    with pytest.raises(ValueError):
        ingest_snapshot(node, snapshot)


@pytest.mark.django_db
def test_enforce_limits_ignores_legacy_expiry(ready_node, authenticated):
    from apps.subscriptions.tasks import enforce_limits

    _client, _admin = authenticated
    p = AccessProfile.objects.create(
        name="expired-node", expires_at=timezone.now() - timedelta(seconds=1)
    )
    protocol = NodeProtocol.objects.create(node=ready_node, protocol="vless", port=21001)
    CredentialService.rotate(ready_node.pk, profile_ids=[p.pk], protocol_ids=[protocol.pk])
    ready_node.refresh_from_db()
    ready_node.applied_generation = ready_node.desired_generation
    ready_node.save()
    assert enforce_limits() == []


@pytest.mark.django_db
def test_socks5_assignment_is_allowed_without_limits(ready_node, authenticated):
    _client, admin = authenticated
    p = AccessProfile.objects.create(name="limited", traffic_limit_bytes=100)
    protocol = NodeProtocol.objects.create(node=ready_node, protocol="socks5", port=21002)
    AccessService.assign(p.pk, protocol_ids=[protocol.pk], admin=admin)
    assert p.node_credentials.filter(protocol=protocol, revoked_at__isnull=True).exists()


@pytest.mark.django_db
def test_one_time_delivery_requires_idempotency_never_replays_secret(authenticated):
    client, _ = authenticated
    p = AccessProfile.objects.create(name="safe-delivery")
    key = uuid4()
    path = f"/api/v1/access-profiles/{p.pk}/subscription/"
    assert client.post(path, {}, format="json").status_code == 400
    issued = write(client, path, {}, key)
    assert issued.status_code == 201
    assert issued["Cache-Control"] == "no-store"
    assert write(client, path, {}, key).status_code == 409
    details = client.get(f"/api/v1/subscriptions/{issued.json()['subscription_id']}/").json()
    assert issued.json()["token"] not in str(details)


@pytest.mark.django_db
def test_real_stats_from_generated_vless_config(ready_node, tmp_path):
    import json
    import os
    import socket
    import subprocess
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from pathlib import Path

    from apps.subscriptions.credentials import decrypt_material
    from apps.subscriptions.metering import ingest_snapshot

    binary = Path(__file__).resolve().parents[3] / "runtime/xray/v26.3.27/xray"
    if not binary.exists():
        pytest.skip("pinned local binary absent")

    def port():
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"actual-metering" * 100)

        def log_message(self, *args):
            pass

    profile = AccessProfile.objects.create(name="actual-metering")
    protocol = NodeProtocol.objects.create(
        node=ready_node, protocol="vless", listen_address="127.0.0.1", port=port()
    )
    credential = CredentialService.rotate(
        ready_node.pk, profile_ids=[profile.pk], protocol_ids=[protocol.pk]
    )[0]
    api_port, client_port = port(), port()
    server = build_node_config(ready_node)
    server["inbounds"][-1]["port"] = api_port
    client = {
        "inbounds": [
            {
                "listen": "127.0.0.1",
                "port": client_port,
                "protocol": "socks",
                "settings": {"auth": "noauth"},
            }
        ],
        "outbounds": [
            {
                "protocol": "vless",
                "settings": {
                    "vnext": [
                        {
                            "address": "127.0.0.1",
                            "port": protocol.port,
                            "users": [
                                {"id": decrypt_material(credential)["id"], "encryption": "none"}
                            ],
                        }
                    ]
                },
            }
        ],
    }
    processes = []
    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    env = {
        k: v
        for k, v in os.environ.items()
        if k.lower() not in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}
    }
    try:
        for name, config in [("server", server), ("client", client)]:
            file = tmp_path / f"{name}.json"
            file.write_text(json.dumps(config))
            file.chmod(0o600)
            processes.append(
                subprocess.Popen(
                    [str(binary), "run", "-config", str(file)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", client_port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.05)
        r = subprocess.run(
            [
                "curl",
                "--disable",
                "--silent",
                "--fail",
                "--max-time",
                "5",
                "--socks5-hostname",
                f"127.0.0.1:{client_port}",
                f"http://127.0.0.1:{http.server_port}/",
            ],
            capture_output=True,
            env=env,
        )
        assert r.returncode == 0 and r.stdout == b"actual-metering" * 100
        stats = subprocess.run(
            [
                str(binary),
                "api",
                "statsquery",
                f"--server=127.0.0.1:{api_port}",
                "-pattern",
                "user>>>",
            ],
            capture_output=True,
        )
        assert stats.returncode == 0
        snapshot = json.loads(stats.stdout)
        snapshot.update(
            generation=ready_node.applied_generation,
            boot_id="local-test",
            process_id="1",
            sequence=1,
            sampled_at=timezone.now().isoformat(),
        )
        assert ingest_snapshot(ready_node, snapshot) == 1
        profile.refresh_from_db()
        assert profile.upload_bytes > 0 and profile.download_bytes >= 1400
    finally:
        for process in processes:
            process.terminate()
            process.wait(timeout=5)
        http.shutdown()
        http.server_close()


@pytest.mark.django_db
def test_protocol_catalog_creation_and_tls_validation(ready_node, authenticated):
    client, _ = authenticated
    path = "/api/v1/subscriptions/catalog/"
    payload = {
        "node_id": str(ready_node.pk),
        "protocol": "vless",
        "port": 21111,
        "transport": "grpc",
    }
    response = write(client, path, payload)
    assert response.status_code == 201
    assert client.get(path).json()["items"][0]["id"] == response.json()["id"]
    assert write(client, path, payload).status_code == 400
    assert write(client, path, {**payload, "port": 21112, "protocol": "trojan"}).status_code == 400
    assert write(client, path, {**payload, "port": 10085}).status_code == 400


@pytest.mark.django_db
def test_protocol_catalog_defaults_vless_to_websocket_and_preserves_explicit_tcp(
    ready_node, authenticated
):
    client, _ = authenticated
    path = "/api/v1/subscriptions/catalog/"

    defaulted = write(
        client,
        path,
        {"node_id": str(ready_node.pk), "protocol": "vless", "port": 21113},
    )
    assert defaulted.status_code == 201
    assert (
        client.get(path).json()["items"][0]["transport"]
        == "ws"
    )

    explicit = write(
        client,
        path,
        {
            "node_id": str(ready_node.pk),
            "protocol": "vless",
            "port": 21114,
            "transport": "tcp",
        },
    )
    assert explicit.status_code == 201
    transports = {
        item["id"]: item["transport"] for item in client.get(path).json()["items"]
    }
    assert transports[defaulted.json()["id"]] == "ws"
    assert transports[explicit.json()["id"]] == "tcp"


@pytest.mark.django_db
def test_multiple_protocol_revision_keeps_all_credential_references(publishable_subscription):
    _, subscription, node, old = publishable_subscription
    protocol = NodeProtocol.objects.create(node=node, protocol="vmess", port=21115)
    credential = CredentialService.rotate(
        node.pk, profile_ids=[subscription.profile_id], protocol_ids=[protocol.pk]
    )[0]
    node.refresh_from_db()
    node.applied_generation = node.desired_generation
    node.save()
    subscription.profile.node_credentials.update(
        desired_generation=node.applied_generation, applied_generation=node.applied_generation
    )
    revision = Publisher.publish(subscription.pk)
    assert {v["credential_ref"] for v in revision.node_versions.values()} == {
        str(old.pk),
        str(credential.pk),
    }
    batch = Publisher.invalidate_node(node.pk)
    assert str(subscription.pk) in batch.subscription_ids
