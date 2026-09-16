# P4 访问身份、订阅与强制撤销 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 发布四类一致的订阅，支持一次性交付令牌、可证明旧凭据及旧连接失效的撤销，并阻止恢复旧备份重新启用访问。

**Architecture:** PostgreSQL 保存访问身份、凭据世代、不可变修订和撤销进度；公开进程逐请求验证授权，仅解密已发布内容。撤销通过 P3 Operation/NodeExecutor 推进，精确移除、整体隔离和无法确认分别保存证据。恢复屏障跨越 HTTP、worker 和重新开放节点端口。

**Tech Stack:** Python 3.13、Django 5.2 LTS、DRF 3.16、PostgreSQL 17、Celery 5.5；固定版本 Xray、真实订阅格式解析器与本地协议测试容器。

**Spec:** `docs/superpowers/specs/2026-09-16-xray-manager-design.md`，主要对应第 5、6、8、9、11、12 节；执行前读完整规格。

## Global Constraints

- 一个全新 Git 单仓库，前后端放在一起，分别构建、运行，通过版本化 API 交互。
- 仅一个超级管理员，无注册、邀请、普通用户、多租户或复杂 RBAC。云账号和设备访问身份均不是登录用户。
- Shop、vue-shop-admin、shop-xray-installer 全部只读参考：不改、不删除、不复制历史迁移或运行数据，不导入其模块，不调用其部署资产。
- 第一版所有订阅响应 `Cache-Control: no-store`；数据库故障返回 503，禁止使用陈旧缓存绕过撤销。
- 第一版云资源变更由管理员显式发起；强制撤销确认已包含同一操作必要的重试和失败隔离，不包含删除或释放 IP。
- `archive/` 不进入 Git、镜像、测试发现或发布包；测试仅使用新造凭据，不读取归档秘密。
- 本文件是开发计划；本轮不执行业务实现、提交、云写入或生产验证。下列命令均在项目根目录执行。
- 依赖 P1 的密钥/近期认证/审计、P3 的可靠任务及安装器。测试数据库必须为独立 PostgreSQL，不能用 SQLite 证明并发事务。

---

### Task 1: 独立访问身份、令牌一次性交付和撤销感知读取

**Files:**
- Create: `backend/apps/subscriptions/models.py`、`backend/apps/subscriptions/migrations/0001_initial.py`：身份、凭据、令牌摘要、修订、撤销记录约束。
- Create: `backend/apps/subscriptions/tokens.py`、`backend/apps/subscriptions/delivery.py`、`backend/apps/subscriptions/security_barrier.py`：摘要查找、墓碑、一次性秘密交付及持久化读取屏障。
- Create: `backend/apps/subscriptions/public_views.py`、`backend/apps/subscriptions/urls.py`、`backend/config/subscription_urls.py`：只读公开路径。
- Modify: `backend/config/settings/base.py`、`backend/config/urls.py`：注册新应用及管理路由。
- Test: `backend/tests/subscriptions/test_tokens.py`、`backend/tests/subscriptions/test_public_read.py`、`backend/tests/subscriptions/test_secret_delivery.py`。

**Interfaces:**
- Consumes: `SecretStore.encrypt(plaintext: bytes, *, purpose: str, aad: bytes) -> dict` / `decrypt(envelope: dict, *, purpose: str, aad: bytes) -> bytes`；P1 管理会话与最近 5 分钟 step-up 规则。
- Produces: `IssuedToken(subscription_id: UUID, raw_token: str)`；`TokenService.issue(profile_id: UUID) -> IssuedToken`、`rotate(subscription_id: UUID) -> IssuedToken`、`disable(subscription_id: UUID) -> None`、`resolve(raw_token: str) -> Subscription`。
- Produces: `TokenGone`、`TokenUnknown`、`PublishingBlocked` 异常；`PublicSubscriptionReader.read(raw_token: str, *, format: str) -> bytes`。
- Produces: `SecurityState(singleton_key,mode,last_security_sequence)`、`SecurityBarrier.assert_open(*, purpose: str) -> None`；purpose 仅 public_read/cloud_write/reopen_node，mode 非 OPEN 抛 PublishingBlocked；Task 3 扩展恢复对账。
- Produces models: `AccessProfile(name, status)`、`NodeCredential(profile_id,node_id,protocol_id,version,envelope,desired_generation,applied_generation,revoked_at)`、`Subscription(profile_id,token_digest,token_epoch,status,current_revision_id)`、`SubscriptionToken(subscription_id,token_digest,token_epoch,revoked_at)`、`SubscriptionRevision(subscription_id,number,public_version,payloads,node_versions,published_at,usable)`；全部实体主键 UUID。SubscriptionToken 是独立墓碑模型，旧 digest 永久可识别为已撤销。

- [ ] **Step 1: 写出真实数据库上的令牌轮换回归测试。**

```python
import pytest
from apps.subscriptions.models import AccessProfile, Subscription
from apps.subscriptions.tokens import TokenGone, TokenService

@pytest.mark.django_db(transaction=True)
def test_rotation_rejects_old_url_and_retains_only_digest():
    profile = AccessProfile.objects.create(name="phone", status="ACTIVE")
    old = TokenService.issue(profile.id)
    new = TokenService.rotate(old.subscription_id)
    assert old.raw_token != new.raw_token
    assert len(new.raw_token) >= 43
    with pytest.raises(TokenGone):
        TokenService.resolve(old.raw_token)
    assert TokenService.resolve(new.raw_token).pk == old.subscription_id
    row = Subscription.objects.get(pk=old.subscription_id)
    assert new.raw_token not in repr(row.__dict__)
```

- [ ] **Step 2: 运行红灯。** `uv run --project backend pytest -c backend/pyproject.toml backend/tests/subscriptions/test_tokens.py::test_rotation_rejects_old_url_and_retains_only_digest -v`；预期因新模块不存在或旧令牌仍可读失败。
- [ ] **Step 3: 建立模型和令牌事务；迁移从新应用 0001 开始。** 摘要全局唯一，凭据 `(profile,node,protocol,version)` 唯一，修订 `(subscription,number)` 唯一；撤销时间不得回退。令牌限制为 URL-safe ASCII、固定最大长度，格式错误直接 404，不把输入放日志。

```python
from dataclasses import dataclass
from hashlib import sha256
from secrets import token_urlsafe
from uuid import UUID

@dataclass(frozen=True)
class IssuedToken:
    subscription_id: UUID
    raw_token: str

def fresh_token() -> tuple[str, str]:
    raw = token_urlsafe(32)
    return raw, sha256(raw.encode("ascii")).hexdigest()
```

`issue/rotate` 在 `transaction.atomic()` 内锁定 profile 和 subscription：拒绝 REVOKING/REVOKED，旧摘要插入 SubscriptionToken 墓碑，新摘要覆盖当前值且 token_epoch 递增。返回原文一次；模型、Operation 参数、审计和幂等响应均不保存原文。交付请求丢失后的重试返回 `SECRET_ALREADY_DELIVERED`，管理员显式轮换；不能为“方便重试”可逆保存 Token。AccessProfile 未完成撤销不能硬删除；已撤销身份也保留关联墓碑与审计，不级联删除历史摘要。

- [ ] **Step 4: 实现公开读取顺序并补充 HTTP 测试。** 查摘要/墓碑 → 查 profile/Subscription 撤销状态 → 校验恢复屏障 → 检查当前 usable revision → 读取请求格式并解密。读取与撤销使用同一数据库主库；HEAD 执行相同授权检查、不返回正文。未知 404 与已撤销 410 使用等长正文；全部响应含 no-store。能确定已撤销的 Token 始终 410，不因节点排除修订尚未就绪变 503；数据库不可用导致无法确定状态，以及有效身份未就绪/恢复模式返回 503。不持有云/SSH/TOTP 密钥；`v` 参数不能读取历史修订。

```python
import pytest
from django.test import Client, override_settings
from apps.subscriptions.models import AccessProfile
from apps.subscriptions.tokens import TokenService

@pytest.mark.django_db(transaction=True)
@override_settings(ROOT_URLCONF="config.subscription_urls")
def test_revoked_link_is_gone_before_revision_lookup():
    profile = AccessProfile.objects.create(name="temporary", status="ACTIVE")
    issued = TokenService.issue(profile.id)
    TokenService.disable(issued.subscription_id)
    client = Client()
    for method in (client.get, client.head):
        response = method(f"/s/{issued.raw_token}")
        assert response.status_code == 410
        assert response["Cache-Control"] == "no-store"
```
- [ ] **Step 5: 添加一次性交付与并发测试。** 管理 POST 创建/轮换/显式交付均要求 CSRF 和近期认证；列表、详情、错误和重放响应不能含 Token。两次并发轮换串行化，只有最后一次有效；轮换与强制撤销竞争不能重新启用已撤销身份。日志测试断言 URL、代理链接、UUID 凭据和 payload 原文未出现。
- [ ] **Step 6: 绿灯并审查迁移。** 运行 `uv run --project backend pytest -c backend/pyproject.toml backend/tests/subscriptions/test_tokens.py backend/tests/subscriptions/test_public_read.py backend/tests/subscriptions/test_secret_delivery.py -v`，再运行 `uv run --project backend python backend/manage.py makemigrations --check --dry-run`；全部通过才完成此任务。
- [ ] **Step 7: 在实施获授权时精确暂存，审查暂存差异后提交。**

```bash
git add backend/apps/subscriptions/models.py backend/apps/subscriptions/migrations/0001_initial.py backend/apps/subscriptions/tokens.py backend/apps/subscriptions/delivery.py backend/apps/subscriptions/security_barrier.py backend/apps/subscriptions/public_views.py backend/apps/subscriptions/urls.py backend/config/subscription_urls.py backend/config/settings/base.py backend/config/urls.py backend/tests/subscriptions/test_tokens.py backend/tests/subscriptions/test_public_read.py backend/tests/subscriptions/test_secret_delivery.py
git diff --cached --check
git commit -m "feat(subscriptions): add one-time token delivery and revocation-aware reads"
```

独立门禁：使用数据库真实读路径验证旧 Token GET/HEAD 均 410、新 Token 可解析；任何读取故障均不回落到旧快照；一次性交付从 API 到审计均无第二个可恢复原文副本。

### Task 2: 四格式不可变修订、协议兼容矩阵和共享密钥范围

**Files:**
- Create: `backend/apps/subscriptions/compatibility.py`、`backend/apps/subscriptions/credentials.py`：固定 Xray 协议能力、独立/共享凭据和版本分配。
- Create: `backend/apps/subscriptions/renderers.py`、`backend/apps/subscriptions/publishing.py`：四格式渲染与发布事务。
- Create: `backend/tests/subscriptions/fixtures/compatibility.json`、`backend/tests/subscriptions/test_formats.py`、`backend/tests/subscriptions/test_publishing.py`、`backend/tests/subscriptions/test_credentials.py`。
- Create: `tests/subscriptions/compose.yaml`、`tests/subscriptions/verify_formats.sh`：固定客户端解析器与隔离本地 Xray；容器不连接云平台。
- Create: `docs/contracts/subscription-formats.md`：每种格式/协议/传输的支持范围、排除理由、测试版本及许可证。

**Interfaces:**
- Consumes: Task 1 模型、SecretStore；P3 `ManagedNode` 的 READY/security 状态与 `NodeProtocol.credential_scope`；只发布 desired_generation=applied_generation 的有效凭据。
- Produces: `Format = Literal["shadowrocket","clash","mihomo","v2ray"]`；`render_subscription(format: Format, *, endpoints: list[dict], public_version: str) -> bytes`。
- Produces: `Publisher.publish(subscription_id: UUID) -> SubscriptionRevision`、`Publisher.invalidate_node(node_id: UUID) -> None`；后者先原子置所有引用修订 unusable，再为有效身份准备排除节点的新修订，按固定 ID 顺序锁定订阅，在一个 transaction 中复核世代并切换全部 current_revision；已撤销身份不参与重新发布，仍返回 410。
- Produces: `CredentialService.rotate(node_id: UUID, *, profile_ids: list[UUID], protocol_ids: list[UUID]) -> list[NodeCredential]`；共享 scope 自动扩展为该协议全部有效 profile，不静默影响其他身份。
- Endpoint 字典字段固定为 `node_id, protocol, host, port, transport, tls, credential_ref, credential_version, applied_generation`；秘密在渲染专用边界解密，不在节点列表返回。

- [ ] **Step 1: 写出空协议交集不能伪装成功的测试。**

```python
import pytest
from apps.subscriptions.renderers import NoCompatibleEndpoints, render_subscription

def test_empty_protocol_intersection_is_an_explicit_error():
    with pytest.raises(NoCompatibleEndpoints):
        render_subscription("clash", endpoints=[], public_version="r-1")
```

- [ ] **Step 2: 运行红灯。** `uv run --project backend pytest -c backend/pyproject.toml backend/tests/subscriptions/test_formats.py::test_empty_protocol_intersection_is_an_explicit_error -v`；预期新渲染器缺失或返回空配置失败。
- [ ] **Step 3: 固定格式矩阵并实现真实编码。** `NoCompatibleEndpoints` 为稳定 422 管理错误，公开未就绪返回 503；每个格式单独过滤兼容协议。Clash 与 Mihomo 使用各自明确版本的支持集，不能把 Mihomo 独有字段写入 Clash。Shadowrocket/V2Ray URI 格式分别测试 base64、userinfo 转义、IPv6 方括号、TLS SNI、VMess JSON 和换行，拒绝生产 allowInsecure；无可用协议的格式标记 unavailable_reason，其他格式仍同次发布。

```python
import json
from secrets import token_urlsafe

def seal_payload(secret_store, revision_id, number, format, body):
    aad = f"revision:{revision_id}:{number}:{format}".encode()
    return secret_store.encrypt(body, purpose="subscription", aad=aad)

def revision_manifest(node_versions):
    return json.dumps(node_versions, sort_keys=True, separators=(",", ":"))

def new_public_version():
    return token_urlsafe(16)
```

`Publisher.publish` 先锁 subscription/profile，检查 ACTIVE、恢复屏障及未冻结；以同一个节点/凭据版本集合生成四个 payload，再校验该集合未变化并原子切换 current_revision。内容不可修改，usable 可单向关闭；每次发布只有一个 number/public_version。AAD 绑定实体/字段/版本，交换两个修订密文必须解密失败。

- [ ] **Step 4: 加入发布与凭据事务测试。** 本任务测试建立真实 NodePool/ManagedNode/NodeProtocol/NodeCredential 记录，覆盖非 READY、隔离、世代未应用、撤销中、TLS 未满足、发布与撤销竞争；四格式 manifest 与已发布节点一致，更新修订不旋转 Token，任意 v 均读当前版本。共享协议使用固定版本支持的密码格式，多个 profile 引用同一共享材料时明确记录引用和影响集。
- [ ] **Step 5: 用独立解析器核验内容。** `verify_formats.sh` 必须读取已生成 fixture，分别调用固定版本 Clash/Mihomo 的配置校验与 Xray URI 转配置兼容测试；不得只调用被测 renderer 的逆函数。Shadowrocket 缺少可自动化官方解析器的部分使用公开格式规范 fixture 验证，明确记录尚需真实客户端验收，不声称本地结果等于 iOS 客户端验证。
- [ ] **Step 6: 运行绿灯。** `uv run --project backend pytest -c backend/pyproject.toml backend/tests/subscriptions/test_formats.py backend/tests/subscriptions/test_publishing.py backend/tests/subscriptions/test_credentials.py -v`；运行 `bash tests/subscriptions/verify_formats.sh`。脚本任一依赖不可用须非零退出并报告门禁未运行，不能 skip 后当通过。
- [ ] **Step 7: 在实施获授权时仅暂存本任务 Files。**

```bash
git add backend/apps/subscriptions/compatibility.py backend/apps/subscriptions/credentials.py backend/apps/subscriptions/renderers.py backend/apps/subscriptions/publishing.py backend/tests/subscriptions/fixtures/compatibility.json backend/tests/subscriptions/test_formats.py backend/tests/subscriptions/test_publishing.py backend/tests/subscriptions/test_credentials.py tests/subscriptions/compose.yaml tests/subscriptions/verify_formats.sh docs/contracts/subscription-formats.md
git diff --cached --check
git commit -m "feat(subscriptions): publish immutable compatible subscription revisions"
```

独立门禁：已发布修订内容哈希恒定；四格式有明确可用性；真实解析门禁通过且不兼容协议被排除；共享协议影响范围从后端返回，不由前端猜测。

### Task 3: 强制撤销、正反向证据、失败隔离和恢复屏障

**Files:**
- Create: `backend/apps/subscriptions/revocation.py`、`backend/apps/subscriptions/verification.py`：撤销状态机与证据验证。
- Modify: `backend/apps/subscriptions/security_barrier.py`：在 Task 1 的读取屏障上加入恢复对账与节点复开判断。
- Create: `backend/apps/subscriptions/management/commands/reconcile_security_state.py`：导入独立安全事件副本，缺失时保持恢复关闭。
- Modify: `backend/apps/subscriptions/models.py`、`backend/apps/subscriptions/migrations/0002_revocation_barrier.py`、`backend/apps/subscriptions/public_views.py`：子节点状态和屏障读取。
- Modify: `backend/apps/operations/handlers.py`、`backend/apps/nodes/execution_types.py`：注册撤销/轮换/恢复处理器及探测证据类型。
- Test: `backend/tests/subscriptions/test_revocation.py`、`backend/tests/subscriptions/test_isolation_failure.py`、`backend/tests/subscriptions/test_restore_barrier.py`、`tests/subscriptions/test_xray_revocation.py`。
- Create: `docs/runbooks/subscription-revocation.md`：状态解释、共享协议影响、隔离恢复、残留风险与真机验收步骤。

**Interfaces:**
- Consumes: `OperationService.submit(*, kind: str, target_id: UUID, params: dict, key: UUID, preview_id: UUID | None) -> Operation`；`NodeExecutor.apply_config(node_id: UUID, *, generation: int, config: dict, operation_id: UUID, allow_security_rollback: bool=False) -> ApplyResult`。
- Consumes: `NodeExecutor.probe(node_id: UUID, *, credential_ref: UUID, expect_accept: bool, operation_id: UUID) -> ProbeResult`；`NodeLifecycle.quarantine(node_id, *, operation_id) -> IsolationResult`，后者含 `confirmed: bool, evidence: dict`，永不自动删除。
- Consumes: `ProbeResult` 见下文；P3 共享类型统一在 `nodes/execution_types.py`，不能在两个应用重复声明。
- Produces: `RevocationService.request(profile_id: UUID, *, key: UUID, preview_id: UUID) -> Operation`；`run(operation_id: UUID) -> None`；`rotate_node(node_id: UUID, *, key: UUID, preview_id: UUID) -> Operation`。
- Consumes: `NodeExecutor.capture_probe_sessions(node_id: UUID, *, credential_refs: list[UUID], operation_id: UUID) -> dict[UUID, str]`：建立旧凭据持续连接并保存凭据 ID 到会话证据 ID 的映射；后续 probe 关联此证据。连接凭据只经受保护 stdin 进入本地客户端进程。
- Produces: `SecurityBarrier.assert_open(*, purpose: str) -> None`、`enter_restore() -> None`、`reconcile(events: list[dict], *, expected_sequence: int) -> bool`；purpose 仅为 public_read/cloud_write/reopen_node，恢复专项安全操作走显式授权处理器。

- [ ] **Step 1: 写出超时不能证明撤销成功的纯证据测试。**

```python
from apps.nodes.execution_types import ProbeResult
from apps.subscriptions.verification import verified_revoked

def test_timeout_without_positive_control_is_unconfirmed():
    old = ProbeResult(accepted=False, positive_control=False,
                      fresh_connection=True, existing_session_closed=True,
                      evidence={"failure": "timeout"})
    assert verified_revoked(old) is False
```

- [ ] **Step 2: 运行红灯。** `uv run --project backend pytest -c backend/pyproject.toml backend/tests/subscriptions/test_revocation.py::test_timeout_without_positive_control_is_unconfirmed -v`；预期缺少类型/验证器或错误认定撤销成功。
- [ ] **Step 3: 固定取证类型与成功判定。**

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class ProbeResult:
    accepted: bool | None
    positive_control: bool
    fresh_connection: bool
    existing_session_closed: bool | None
    evidence: dict

def verified_revoked(result: ProbeResult) -> bool:
    return (result.accepted is False and result.positive_control
            and result.fresh_connection
            and result.existing_session_closed is True)
```

positive_control 必须包含同一节点/协议/地址族/传输/时间窗的新凭据成功或明确服务端认证拒绝证据。每个 NodeProtocol 就是一个具体 endpoint，按其 credential_ref 对全部启用协议逐个正反向探测；Google 请求只验证 SOCKS/outbound，不代表 VLESS/Trojan 等认证成功。fresh_connection 表示旧凭据发起全新握手；existing_session_closed 必须关联 capture_probe_sessions 建立的旧持续连接及中断时间，不能从 systemd 重启成功推断。evidence 只保存关联 ID、时间、认证结果和配置 generation，不保存原始凭据。

- [ ] **Step 4: 原子接收撤销，再逐节点执行。** `request` 在同一事务锁 profile/Token，标 REVOKING、撤销 Token 并保留摘要、冻结发布、写 Operation/outbox/审计。P3 预览校验包括所有共享凭据受影响身份和节点隔离授权；事务回滚时不能出现 Token 已撤销但没有任务。令牌失效后 can_cancel=False；拒绝旧安装任务或旧 worker 重新写入已撤销 generation。每个节点遵循 fail-closed 顺序：保留 SSH 管理通道，先关闭受管协议端口或停止 Xray并验证不能新建旧连接，再 capture 持续会话证据、部署新 generation、校验并启动但保持协议端口关闭，最后应用最小规则重新开放并执行正反向探测。提交到逐节点生效存在传播窗口：后台持续返回 REVOKING 和未确认节点清单，前端不能在收到 202 时提示全部旧连接已断开。

```python
def choose_node_outcome(*, removed: bool, isolation_confirmed: bool) -> str:
    if removed:
        return "VERIFIED_REVOKED"
    if isolation_confirmed:
        return "QUARANTINED"
    return "REVOCATION_UNCONFIRMED"
```

处理顺序固定：capture_probe_sessions → 生成删除目标身份的新配置 → Xray 校验 → apply_config(allow_security_rollback=False) → 重启 → 正反向 probe → 写 OperationStep。记录 REQUESTED/APPLYING/CONFIG_APPLIED/SERVICE_RESTARTED/VERIFIED_REVOKED；只有全部目标验证精确移除才把 profile 标 REVOKED、Operation 标 SUCCEEDED。共享密码协议先轮换所有有效 profile，整节点轮换处理全部协议；新订阅只在新 generation 验证应用后发布。共享协议只保证未撤销身份的新一代配置可用，其旧配置同样失效；危险预览列出必须刷新配置的全部身份。唯一身份撤销用临时正向控制凭据，验证后删除、重启并再次验证临时凭据失效，避免遗留探测后门。

- [ ] **Step 5: 实现失败分支和不确定结果取证。** 任一步失败先将该节点所有修订 unusable，为其他有效身份发布排除它的新修订，未就绪 503；被撤销身份的 Token 始终 410。随后调用 quarantine，只有规则回读和节点外 IPv4/IPv6、TCP/UDP/旧连接证据充分才写 QUARANTINED；这只证明整体阻断，仍保留精确撤销未完成。隔离确认不足同时写 ISOLATION_UNCONFIRMED，操作进入 PARTIALLY_SUCCEEDED 或外部结果不明时 NEEDS_RECONCILIATION。失败不可恢复旧配置，重试仅处理未完成节点，不自动删实例、放弃配额或释放 IP。
- [ ] **Step 6: 写恢复屏障及复开测试。** 恢复初始 MAINTENANCE（LOCKDOWN 安全锁定语义）：有效订阅 503、可确认已撤销的 Token 410、普通云写 worker 拒绝，仅允许认证恢复流程。安全事件副本必须连续、完整到独立确认的 expected_sequence；缺口、较旧快照或证据不足均不能置 OPEN。无法证明最新状态时保留锁定，通过恢复流程撤销全部 Token、轮换全部有效节点凭据并完成验证。隔离复开必须人工确认，先受限探测源地址验证新凭据成功/旧凭据失败、所有历史撤销身份缺席，再按最小规则开放、再次正反向验证；异常重新隔离并保持屏障。
- [ ] **Step 7: 运行数据库与故障绿灯。** `uv run --project backend pytest -c backend/pyproject.toml backend/tests/subscriptions/test_revocation.py backend/tests/subscriptions/test_isolation_failure.py backend/tests/subscriptions/test_restore_barrier.py -v`；覆盖两个节点部分成功、SSH/API 双失败、宽泛 allow 规则、IPv6 漏关、worker 租约失效、重放、旧快照恢复和并发发布，不得仅断言 Operation 名称。
- [ ] **Step 8: 运行固定 Xray 的本地协议实测。** `uv run --project backend pytest -c backend/pyproject.toml tests/subscriptions/test_xray_revocation.py -v`；每种支持的认证/传输组合建立长连接，撤销后断开旧连接并拒绝旧握手，正常身份继续连接，共享协议受影响身份更新后可用。测试无本地运行时则失败并标未执行；禁止替代成 Mock 后声称实测通过。
- [ ] **Step 9: 在实施获授权时仅暂存本任务 Files。**

```bash
git add backend/apps/subscriptions/revocation.py backend/apps/subscriptions/verification.py backend/apps/subscriptions/security_barrier.py backend/apps/subscriptions/management/commands/reconcile_security_state.py backend/apps/subscriptions/models.py backend/apps/subscriptions/migrations/0002_revocation_barrier.py backend/apps/subscriptions/public_views.py backend/apps/operations/handlers.py backend/apps/nodes/execution_types.py backend/tests/subscriptions/test_revocation.py backend/tests/subscriptions/test_isolation_failure.py backend/tests/subscriptions/test_restore_barrier.py tests/subscriptions/test_xray_revocation.py docs/runbooks/subscription-revocation.md
git diff --cached --check
git commit -m "feat(subscriptions): verify credential revocation and enforce recovery barriers"
```

独立门禁：完成 Token 410、旧握手拒绝、旧持续会话终止、新/未撤销凭据成功的组合证据；QUARANTINED 不混为精确移除；云/SSH 双失败保持醒目的未知风险；恢复旧备份不能重新发布旧访问。

## P4 完成记录与交接

- [ ] 运行 `uv run --project backend pytest -c backend/pyproject.toml backend/tests/subscriptions -v` 和上述格式/本地 Xray 门禁，记录命令、退出码、固定版本和证据位置。
- [ ] 运行 `uv run --project backend python backend/manage.py makemigrations --check --dry-run`；检查模型约束、公开数据库角色和 secret purpose/AAD 均一致。
- [ ] 交 P5：交付窗口原文只存内存；显示“链接失效/精确撤销/整体隔离/仍有风险”四种区别，共享协议影响清单及恢复屏障状态。
- [ ] 交 P6：独立安全审计增量副本、expected_sequence 来源、恢复 MAINTENANCE 和双云防火墙数据面验收矩阵。
- [ ] 本地代码门禁与真实 Shadowrocket 客户端、AWS/SWAS 云端和生产恢复验收分别记录；未授权真机阶段统一 `not-run`，不得把 Stub 或本地容器结果写为生产完成。
