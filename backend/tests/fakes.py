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
        self.provider = account.provider
        self.region = region
        self.authorizer = authorizer
        self.instances = {}
        self.firewalls = {}
        self.create_calls = 0
        self.lookup_calls = 0
        self.fail_after_create = False
        self.firewall_ack = True
        self.retain_after_delete = False
        self.fail_delete_readback = False
        self.deleted = False
        self.fail_lifecycle_readback_after_write = False
        self.lifecycle_write_unknown = False
        self.lifecycle_state_after_write = None
        self.addresses_after_lifecycle_write = None
        self.defer_reboot_address_until_operation_complete = False
        self.defer_start_address_until_operation_complete = False
        self.lifecycle_readback_addresses = []
        self.start_operation_statuses = ["SUCCEEDED"]
        self.start_operation_status_calls = []
        self.reboot_operation_statuses = ["SUCCEEDED"]
        self.reboot_operation_status_calls = []
        self.omit_lifecycle_operation_id = False
        self.lifecycle_operation_ids = {"start": [], "reboot": []}
        self.lifecycle_operation_snapshot_calls = []
        self.get_instance_calls = []
        self.action_calls = []

    def _instance(self, name, tags, state="running", addresses=None):
        ref = ResourceRef(self.account, self.region, name)
        return Instance(
            ref=ref,
            name=name,
            state=state,
            raw_state=state,
            addresses=tuple(
                (Address("192.0.2.10", 4, "dynamic", name),)
                if addresses is None
                else addresses
            ),
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
        self.get_instance_calls.append(resource)
        if self.fail_lifecycle_readback_after_write and self.get_instance_calls:
            if len(self.get_instance_calls) > 1:
                raise DomainError(
                    "CLOUD_READ_FAILED", "fake lifecycle read-back failure", status_code=502
                )
        if self.deleted and self.fail_delete_readback:
            raise DomainError("CLOUD_READ_FAILED", "fake read-back failure", status_code=502)
        try:
            instance = self.instances[resource.resource_id]
            if self.action_calls and self.lifecycle_readback_addresses:
                addresses = self.lifecycle_readback_addresses.pop(0)
                instance = self._instance(
                    instance.name,
                    dict(instance.tags),
                    instance.state,
                    addresses,
                )
                self.instances[resource.resource_id] = instance
            return instance
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
        self.action_calls.append(action)
        addresses = self.addresses_after_lifecycle_write or current.addresses
        if action == "reboot" and self.defer_reboot_address_until_operation_complete:
            addresses = current.addresses
        if action == "start" and self.defer_start_address_until_operation_complete:
            addresses = current.addresses
        self.instances[resource.resource_id] = self._instance(
            current.name,
            dict(current.tags),
            self.lifecycle_state_after_write or state,
            addresses,
        )
        if self.lifecycle_write_unknown:
            raise DomainError(
                "CLOUD_WRITE_OUTCOME_UNKNOWN",
                "fake lifecycle write outcome unknown",
                status_code=502,
            )
        if action in self.lifecycle_operation_ids:
            self.lifecycle_operation_ids[action].append(f"fake-{action}-operation")
        return MutationResult(
            "accepted",
            f"fake-{action}",
            resource.resource_id,
            state,
            None,
            (
                f"fake-{action}-operation"
                if action in {"start", "reboot"} and not self.omit_lifecycle_operation_id
                else None
            ),
        )

    def start_instance(self, resource, *, permit):
        return self._simple("start", resource, permit, "running")

    def stop_instance(self, resource, *, permit):
        return self._simple("stop", resource, permit, "stopped")

    def reboot_instance(self, resource, *, permit):
        return self._simple("reboot", resource, permit, "running")

    def list_operation_ids(self, resource, *, action):
        self.lifecycle_operation_snapshot_calls.append((resource, action))
        return list(self.lifecycle_operation_ids.get(action, ()))

    def get_operation_status(self, operation_id, resource, *, action):
        if action not in {"start", "reboot"} or operation_id != f"fake-{action}-operation":
            raise DomainError("CLOUD_OPERATION_TARGET_MISMATCH", "fake operation mismatch")
        statuses = (
            self.start_operation_statuses if action == "start" else self.reboot_operation_statuses
        )
        calls = (
            self.start_operation_status_calls
            if action == "start"
            else self.reboot_operation_status_calls
        )
        calls.append(operation_id)
        index = min(len(calls) - 1, len(statuses) - 1)
        status = statuses[index]
        defer_address = (
            self.defer_start_address_until_operation_complete
            if action == "start"
            else self.defer_reboot_address_until_operation_complete
        )
        if status == "SUCCEEDED" and defer_address:
            current = self.instances[resource.resource_id]
            self.instances[resource.resource_id] = self._instance(
                current.name,
                dict(current.tags),
                current.state,
                self.addresses_after_lifecycle_write or current.addresses,
            )
        return status

    def delete_instance(self, resource, *, permit):
        self.authorizer.assert_allowed(
            permit, action="delete", account=self.account, resource_id=resource.resource_id
        )
        if not self.retain_after_delete:
            self.instances.pop(resource.resource_id, None)
        self.deleted = True
        return MutationResult("accepted", "fake-delete", resource.resource_id, "deleted", None)
