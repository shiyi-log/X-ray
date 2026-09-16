from __future__ import annotations

from datetime import UTC, datetime

from common.errors import DomainError
from providers.base import (
    Address,
    FirewallSnapshot,
    Instance,
    MutationResult,
    ResourceRef,
)


class FakeCloudProvider:
    def __init__(self, account, region, *, authorizer):
        self.account = account
        self.region = region
        self.authorizer = authorizer
        self.instances = {}
        self.firewalls = {}
        self.create_calls = 0
        self.lookup_calls = 0
        self.fail_after_create = False
        self.firewall_ack = True

    def _instance(self, name, tags, state="running"):
        ref = ResourceRef(self.account, self.region, name)
        return Instance(
            ref=ref,
            name=name,
            state=state,
            raw_state=state,
            addresses=(Address("192.0.2.10", 4, "dynamic", name),),
            tags=tags,
            observed_at=datetime.now(UTC),
        )

    def find_instance_by_request(self, request, operation_key):
        self.lookup_calls += 1
        return tuple(
            instance
            for instance in self.instances.values()
            if instance.name == request.name
            and instance.tags.get("xray-operation") == operation_key
        )

    def create_instance(self, request, *, permit):
        self.authorizer.assert_allowed(
            permit, action="create", account=self.account, resource_id=None
        )
        self.create_calls += 1
        self.instances[request.name] = self._instance(request.name, dict(request.tags))
        if self.fail_after_create:
            raise DomainError(
                "CLOUD_WRITE_OUTCOME_UNKNOWN",
                "cloud write outcome unknown",
                details={"provider": self.account.provider, "request_id": "fake-timeout"},
            )
        return MutationResult("accepted", "fake-create", request.name, "pending", None)

    def get_instance(self, resource):
        try:
            return self.instances[resource.resource_id]
        except KeyError as exc:
            raise DomainError("RESOURCE_NOT_FOUND", "resource not found", status_code=404) from exc

    def get_firewall(self, resource):
        return FirewallSnapshot(
            tuple(self.firewalls.get(resource.resource_id, ())),
            datetime.now(UTC),
            "fake-firewall-read",
        )

    def configure_firewall(self, resource, rules, *, permit):
        self.authorizer.assert_allowed(
            permit,
            action="firewall",
            account=self.account,
            resource_id=resource.resource_id,
        )
        self.firewalls[resource.resource_id] = tuple(rules)
        outcome = "accepted" if self.firewall_ack else "unknown"
        return MutationResult(outcome, "fake-firewall", resource.resource_id, None, None)

    def _simple(self, action, resource, permit, state):
        self.authorizer.assert_allowed(
            permit, action=action, account=self.account, resource_id=resource.resource_id
        )
        current = self.get_instance(resource)
        self.instances[resource.resource_id] = self._instance(
            current.name, dict(current.tags), state
        )
        return MutationResult("accepted", f"fake-{action}", resource.resource_id, state, None)

    def start_instance(self, resource, *, permit):
        return self._simple("start", resource, permit, "running")

    def stop_instance(self, resource, *, permit):
        return self._simple("stop", resource, permit, "stopped")

    def reboot_instance(self, resource, *, permit):
        return self._simple("reboot", resource, permit, "running")

    def delete_instance(self, resource, *, permit):
        self.authorizer.assert_allowed(
            permit, action="delete", account=self.account, resource_id=resource.resource_id
        )
        self.instances.pop(resource.resource_id, None)
        return MutationResult("accepted", "fake-delete", resource.resource_id, "deleted", None)
