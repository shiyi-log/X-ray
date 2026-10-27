from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from common.errors import DomainError

from .authorization import DenyWrites
from .base import (
    AccountIdentity,
    AccountRef,
    Address,
    Capability,
    CreateRequest,
    FirewallRule,
    FirewallSnapshot,
    Image,
    Instance,
    MutationPermit,
    MutationResult,
    Plan,
    Region,
    ResourceRef,
)
from .capabilities import capabilities_for
from .errors import map_provider_error


class AwsLightsailProvider:
    provider = "aws_lightsail"

    def __init__(
        self,
        account: AccountRef,
        region: str,
        *,
        lightsail_client: object,
        sts_client: object,
        authorizer=None,
    ):
        self.account = account
        self.region = region
        self.lightsail = lightsail_client
        self.sts = sts_client
        self.authorizer = authorizer or DenyWrites()

    @classmethod
    def from_credentials(cls, account, region: str, fields: dict[str, str], *, authorizer):
        if not fields.get("access_key_id") or not fields.get("secret_access_key"):
            raise DomainError("CLOUD_CREDENTIALS_INVALID", "AWS 凭据字段不完整", status_code=400)
        import boto3
        from botocore.config import Config

        config = Config(retries={"total_max_attempts": 1}, region_name=region)
        kwargs = {
            "region_name": region,
            "aws_access_key_id": fields["access_key_id"],
            "aws_secret_access_key": fields["secret_access_key"],
            "config": config,
        }
        if fields.get("session_token"):
            kwargs["aws_session_token"] = fields["session_token"]
        return cls(
            account,
            region,
            lightsail_client=boto3.client("lightsail", **kwargs),
            sts_client=boto3.client("sts", **kwargs),
            authorizer=authorizer,
        )

    def _assert_region(self, resource: ResourceRef):
        if resource.account != self.account or resource.region != self.region:
            raise DomainError(
                "RESOURCE_OWNERSHIP_MISMATCH", "资源不属于当前云账号或区域", status_code=409
            )

    @staticmethod
    def _request_id(response: dict[str, Any]) -> str | None:
        return str(response.get("ResponseMetadata", {}).get("RequestId") or "")[:120] or None

    def validate_credentials(self) -> AccountIdentity:
        try:
            result = self.sts.get_caller_identity()
        except Exception as exc:
            raise map_provider_error(self.provider, exc, write_started=False) from exc
        account_id = str(result.get("Account") or "")
        principal = str(result.get("Arn") or result.get("UserId") or "")
        if not account_id or not principal:
            raise DomainError("CLOUD_IDENTITY_INVALID", "AWS 身份响应缺少必要字段", status_code=502)
        return AccountIdentity(self.provider, account_id, principal, datetime.now(UTC))

    def list_regions(self) -> tuple[Region, ...]:
        try:
            response = self.lightsail.get_regions(includeAvailabilityZones=False)
        except Exception as exc:
            raise map_provider_error(self.provider, exc, write_started=False) from exc
        return tuple(
            Region(str(item.get("name") or ""), str(item.get("name") or ""))
            for item in response.get("regions", [])
            if item.get("name")
        )

    def list_plans(self, region: str) -> tuple[Plan, ...]:
        if region != self.region:
            raise DomainError("REGION_MISMATCH", "适配器已绑定其他区域", status_code=400)
        values = []
        token = None
        while True:
            kwargs = {}
            if token:
                kwargs["pageToken"] = token
            try:
                response = self.lightsail.get_bundles(**kwargs)
            except Exception as exc:
                raise map_provider_error(self.provider, exc, write_started=False) from exc
            for item in response.get("bundles", []):
                price = item.get("price")
                values.append(
                    Plan(
                        id=str(item.get("bundleId") or ""),
                        region=self.region,
                        price=Decimal(str(price)) if price is not None else None,
                        currency="USD" if price is not None else None,
                        period=str(item.get("transferPerMonthGb") or "") or None,
                        captured_at=datetime.now(UTC),
                        exclusions=tuple(["price unavailable"] if price is None else []),
                    )
                )
            token = response.get("nextPageToken")
            if not token:
                break
        return tuple(values)

    def list_images(self, region: str) -> tuple[Image, ...]:
        if region != self.region:
            raise DomainError("REGION_MISMATCH", "适配器已绑定其他区域", status_code=400)
        try:
            response = self.lightsail.get_blueprints()
        except Exception as exc:
            raise map_provider_error(self.provider, exc, write_started=False) from exc
        return tuple(
            Image(
                id=str(item.get("blueprintId") or ""),
                region=self.region,
                name=str(item.get("name") or item.get("blueprintId") or ""),
                architecture=str(item.get("platform") or "unknown"),
                os_family=str(item.get("os") or "unknown"),
            )
            for item in response.get("blueprints", [])
        )

    def _map_instance(self, item: dict[str, Any]) -> Instance:
        resource_id = str(item.get("name") or item.get("instanceName") or "")
        addresses = []
        if item.get("publicIpAddress"):
            addresses.append(Address(str(item["publicIpAddress"]), 4, "dynamic", resource_id))
        if item.get("ipv6Addresses"):
            addresses.extend(
                Address(str(value), 6, "dynamic", resource_id) for value in item["ipv6Addresses"]
            )
        tags = {
            str(tag.get("key")): str(tag.get("value"))
            for tag in item.get("tags", [])
            if tag.get("key") is not None
        }
        ref = ResourceRef(self.account, self.region, resource_id)
        return Instance(
            ref=ref,
            name=resource_id,
            state=str(item.get("state") or item.get("instanceState") or "UNKNOWN"),
            raw_state=str(item.get("state") or item.get("instanceState") or "UNKNOWN"),
            addresses=tuple(addresses),
            tags=tags,
            observed_at=datetime.now(UTC),
        )

    def find_instance_by_request(
        self, request: CreateRequest, operation_key: str
    ) -> tuple[Instance, ...]:
        try:
            response = self.lightsail.get_instances()
        except Exception as exc:
            raise map_provider_error(self.provider, exc, write_started=False) from exc
        matches = []
        for item in response.get("instances", []):
            instance = self._map_instance(item)
            if (
                instance.name == request.name
                and instance.tags.get("xray-operation") == operation_key
            ):
                matches.append(instance)
        return tuple(matches)

    def get_instance(self, resource: ResourceRef) -> Instance:
        self._assert_region(resource)
        try:
            response = self.lightsail.get_instance(instanceName=resource.resource_id)
        except Exception as exc:
            raise map_provider_error(self.provider, exc, write_started=False) from exc
        item = response.get("instance")
        if not item:
            raise DomainError("RESOURCE_NOT_FOUND", "云实例不存在", status_code=404)
        instance = self._map_instance(item)
        if instance.ref != resource:
            raise DomainError("RESOURCE_OWNERSHIP_MISMATCH", "云实例归属不匹配", status_code=409)
        return instance

    def get_public_ip(self, resource: ResourceRef) -> tuple[Address, ...]:
        return self.get_instance(resource).addresses

    def get_firewall(self, resource: ResourceRef) -> FirewallSnapshot:
        self._assert_region(resource)
        try:
            response = self.lightsail.get_instance_port_states(instanceName=resource.resource_id)
        except Exception as exc:
            raise map_provider_error(self.provider, exc, write_started=False) from exc
        rules = []
        for item in response.get("portStates", []):
            from_port = item.get("fromPort")
            to_port = item.get("toPort")
            for cidr in (item.get("cidrs") or item.get("cidrList") or []):
                family = 6 if ":" in str(cidr) else 4
                rules.append(
                    FirewallRule(
                        protocol=str(item.get("protocol") or "all").lower(),
                        port_from=int(from_port) if from_port is not None else None,
                        port_to=int(to_port) if to_port is not None else None,
                        source=str(cidr),
                        source_kind="cidr",
                        family=family,
                    )
                )
            for cidr in item.get("ipv6Cidrs", []) or []:
                rules.append(
                    FirewallRule(
                        protocol=str(item.get("protocol") or "all").lower(),
                        port_from=int(from_port) if from_port is not None else None,
                        port_to=int(to_port) if to_port is not None else None,
                        source=str(cidr),
                        source_kind="cidr",
                        family=6,
                    )
                )
            for alias in item.get("cidrListAliases", []) or []:
                rules.append(
                    FirewallRule(
                        protocol=str(item.get("protocol") or "all").lower(),
                        port_from=int(from_port) if from_port is not None else None,
                        port_to=int(to_port) if to_port is not None else None,
                        source=str(alias),
                        source_kind="provider_alias",
                        family=4,
                    )
                )
        return FirewallSnapshot(
            tuple(rules), datetime.now(UTC), self._request_id(response)
        )

    def get_capabilities(self, region: str) -> tuple[Capability, ...]:
        return capabilities_for(self.provider, region)

    def _authorize_and_verify(self, resource: ResourceRef, permit: MutationPermit, action: str):
        self.authorizer.assert_allowed(
            permit, action=action, account=self.account, resource_id=resource.resource_id
        )
        self.get_instance(resource)
        self.authorizer.assert_allowed(
            permit, action=action, account=self.account, resource_id=resource.resource_id
        )

    def _simple_action(
        self, resource: ResourceRef, permit: MutationPermit, action: str, method: str
    ) -> MutationResult:
        self._authorize_and_verify(resource, permit, action)
        try:
            response = getattr(self.lightsail, method)(instanceName=resource.resource_id)
        except Exception as exc:
            raise map_provider_error(self.provider, exc, write_started=True) from exc
        return MutationResult(
            "accepted", self._request_id(response), resource.resource_id, None, None
        )

    def create_instance(self, request: CreateRequest, *, permit: MutationPermit) -> MutationResult:
        self.authorizer.assert_allowed(
            permit, action="create", account=self.account, resource_id=None
        )
        if request.region != self.region:
            raise DomainError("REGION_MISMATCH", "创建区域与适配器不一致", status_code=400)
        try:
            response = self.lightsail.create_instances(
                instanceNames=[request.name],
                availabilityZone=f"{self.region}a",
                blueprintId=request.image_id,
                bundleId=request.plan_id,
                tags=[
                    {"key": str(key), "value": str(value)} for key, value in request.tags.items()
                ],
            )
        except Exception as exc:
            raise map_provider_error(self.provider, exc, write_started=True) from exc
        return MutationResult("accepted", self._request_id(response), request.name, None, None)

    def start_instance(self, resource: ResourceRef, *, permit: MutationPermit) -> MutationResult:
        return self._simple_action(resource, permit, "start", "start_instance")

    def stop_instance(self, resource: ResourceRef, *, permit: MutationPermit) -> MutationResult:
        return self._simple_action(resource, permit, "stop", "stop_instance")

    def reboot_instance(self, resource: ResourceRef, *, permit: MutationPermit) -> MutationResult:
        return self._simple_action(resource, permit, "reboot", "reboot_instance")

    def delete_instance(self, resource: ResourceRef, *, permit: MutationPermit) -> MutationResult:
        return self._simple_action(resource, permit, "delete", "delete_instance")

    def rotate_public_ip(self, resource: ResourceRef, *, permit: MutationPermit) -> MutationResult:
        raise DomainError(
            "CAPABILITY_UNVERIFIED", "AWS 原地换 IP 需要 P3 多步骤证据", status_code=409
        )

    def configure_firewall(
        self, resource: ResourceRef, rules: tuple[FirewallRule, ...], *, permit: MutationPermit
    ) -> MutationResult:
        self._authorize_and_verify(resource, permit, "firewall")
        # Lightsail replaces the complete rule set on each write.  Keep IPv4
        # and IPv6 sources in the same port entry so a dual-stack rule update
        # cannot silently remove the other address family.
        grouped: dict[tuple[int, int, str], dict[str, object]] = {}
        for rule in rules:
            key = (rule.port_from or 0, rule.port_to or 65535, rule.protocol)
            entry = grouped.setdefault(
                key,
                {
                    "fromPort": key[0],
                    "toPort": key[1],
                    "protocol": key[2],
                },
            )
            if rule.source_kind == "provider_alias":
                field = "cidrListAliases"
            elif rule.family == 6:
                field = "ipv6Cidrs"
            else:
                field = "cidrs"
            entry.setdefault(field, []).append(rule.source)
        port_infos = list(grouped.values())
        try:
            response = self.lightsail.put_instance_public_ports(
                instanceName=resource.resource_id, portInfos=port_infos
            )
        except Exception as exc:
            raise map_provider_error(self.provider, exc, write_started=True) from exc
        return MutationResult(
            "accepted", self._request_id(response), resource.resource_id, None, None
        )
