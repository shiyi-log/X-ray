from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Protocol
from uuid import UUID

ProviderKind = Literal["aws_lightsail", "aliyun_swas"]
Action = Literal[
    "create",
    "start",
    "stop",
    "reboot",
    "delete",
    "rotate_ip",
    "firewall",
    "release_ip",
    "reinstall",
]


@dataclass(frozen=True, slots=True, repr=False)
class SecretInput:
    provider: ProviderKind
    fields: Mapping[str, str]

    def __repr__(self) -> str:
        return f"SecretInput(provider={self.provider!r}, fields=<redacted>)"


@dataclass(frozen=True, slots=True)
class AccountIdentity:
    provider: ProviderKind
    external_account_id: str
    principal_id: str
    verified_at: datetime


@dataclass(frozen=True, slots=True)
class AccountRef:
    id: UUID
    provider: ProviderKind
    external_account_id: str
    credential_version: int


@dataclass(frozen=True, slots=True)
class Region:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class Plan:
    id: str
    region: str
    price: Decimal | None
    currency: str | None
    period: str | None
    captured_at: datetime
    exclusions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Image:
    id: str
    region: str
    name: str
    architecture: str
    os_family: str


@dataclass(frozen=True, slots=True)
class Address:
    value: str
    family: Literal[4, 6]
    kind: Literal["dynamic", "static", "unknown"]
    resource_id: str | None = None


@dataclass(frozen=True, slots=True)
class ResourceRef:
    account: AccountRef
    region: str
    resource_id: str


@dataclass(frozen=True, slots=True)
class Instance:
    ref: ResourceRef
    name: str
    state: str
    raw_state: str
    addresses: tuple[Address, ...]
    tags: Mapping[str, str]
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class CreateRequest:
    name: str
    region: str
    plan_id: str
    image_id: str
    tags: Mapping[str, str]
    term: str | None = None


@dataclass(frozen=True, slots=True)
class FirewallRule:
    protocol: Literal["tcp", "udp", "icmp", "all"]
    port_from: int | None
    port_to: int | None
    source: str
    source_kind: Literal["cidr", "provider_alias"]
    family: Literal[4, 6]


@dataclass(frozen=True, slots=True)
class FirewallSnapshot:
    rules: tuple[FirewallRule, ...]
    observed_at: datetime
    request_id: str | None = None


@dataclass(frozen=True, slots=True)
class Capability:
    name: str
    status: Literal["SUPPORTED", "UNSUPPORTED", "UNVERIFIED"]
    regions: tuple[str, ...]
    plans: tuple[str, ...]
    evidence_url: str
    checked_at: date
    document_verified: bool
    stub_verified: bool
    live_verified: bool
    reason: str


@dataclass(frozen=True, slots=True)
class MutationPermit:
    operation_id: UUID
    operation_key: str
    action: Action
    account_id: UUID
    external_account_id: str
    region: str
    resource_id: str | None
    expires_at: datetime
    fence: int


@dataclass(frozen=True, slots=True)
class MutationResult:
    outcome: Literal["accepted", "completed", "unknown"]
    request_id: str | None
    resource_id: str | None
    raw_state: str | None
    provider_code: str | None
    operation_id: str | None = None


class WriteAuthorizer(Protocol):
    def assert_allowed(
        self,
        permit: MutationPermit,
        *,
        action: Action,
        account: AccountRef,
        resource_id: str | None,
    ) -> None: ...


class CloudReader(Protocol):
    def validate_credentials(self) -> AccountIdentity: ...
    def list_regions(self) -> tuple[Region, ...]: ...
    def list_plans(self, region: str) -> tuple[Plan, ...]: ...
    def list_images(self, region: str) -> tuple[Image, ...]: ...
    def list_instances(self, region: str) -> tuple[Instance, ...]: ...
    def find_instance_by_request(
        self, request: CreateRequest, operation_key: str
    ) -> tuple[Instance, ...]: ...
    def get_instance(self, resource: ResourceRef) -> Instance: ...
    def get_public_ip(self, resource: ResourceRef) -> tuple[Address, ...]: ...
    def get_firewall(self, resource: ResourceRef) -> FirewallSnapshot: ...
    def get_capabilities(self, region: str) -> tuple[Capability, ...]: ...


class CloudProvider(CloudReader, Protocol):
    def create_instance(
        self, request: CreateRequest, *, permit: MutationPermit
    ) -> MutationResult: ...
    def start_instance(
        self, resource: ResourceRef, *, permit: MutationPermit
    ) -> MutationResult: ...
    def stop_instance(self, resource: ResourceRef, *, permit: MutationPermit) -> MutationResult: ...
    def reboot_instance(
        self, resource: ResourceRef, *, permit: MutationPermit
    ) -> MutationResult: ...
    def delete_instance(
        self, resource: ResourceRef, *, permit: MutationPermit
    ) -> MutationResult: ...
    def rotate_public_ip(
        self, resource: ResourceRef, *, permit: MutationPermit
    ) -> MutationResult: ...
    def configure_firewall(
        self,
        resource: ResourceRef,
        rules: tuple[FirewallRule, ...],
        *,
        permit: MutationPermit,
    ) -> MutationResult: ...
