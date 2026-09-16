# P3 通用节点、可靠任务与安装器 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从空节点池完成双云模拟创建、安装、探测、换 IP/替代、隔离及资源回收的可靠操作流程。

**Architecture:** PostgreSQL 行锁预留配额，Operation/outbox 驱动 Celery；云未知结果先对账。远端 generation、固定主机指纹及版本化安装包保证配置不会被旧 worker 回写。

**Tech Stack:** Django 5.2、PostgreSQL 17、Redis 7.4、Celery 5.5、Paramiko、Bash、Xray 固定发行包、pytest、ShellCheck。

**Spec:** [设计规格](../specs/2026-09-16-xray-manager-design.md)，章节 4、6–8。

## Global Constraints

- 配额默认 3，可调；失败/停止/隔离/未知结果资源仍占额度，确认不存在或已删除才能释放。
- 云写来自管理员明确确认的 Operation；SDK 每次写之前重查租约与 scope。
- 不自动删实例或释放 IP；双云厂商差异由 capability 显示。
- PostgreSQL 是唯一正确性基础，Redis 仅队列/辅助；没有 Shop 导入或配置复制。
- 本阶段使用 Fake/SDK Stub 与本地容器；真实云授权独立。

---

### Task P3.1: Operation、配额、幂等、outbox 与 fencing

**Files:**
- Create: `backend/apps/operations/{models,services,claims,outbox,tasks,previews}.py`、对应 `migrations/0001_initial.py`。
- Create: `backend/apps/nodes/{models,quota}.py`、对应初始迁移。
- Create: `backend/apps/operations/management/commands/dispatch_outbox.py`。
- Test: `backend/tests/{test_quota_concurrency,test_operation_idempotency,test_outbox,test_operation_fencing}.py`。

**Interfaces:**
- Consumes: P1 DomainError/AuditService，P2 云契约和 MutationPermit。
- Produces: `ActionPreviewService.create(*,kind,target_id,params)->ActionPreview`；绑定资源版本、价格时间、影响范围、5 分钟有效期，submit 时消费验证。
- `OperationService.submit(*,kind:str,target_id:UUID,params:dict,key:UUID,preview_id:UUID|None)->Operation`；只读无成本任务可无 preview。
- `claim_operation(operation_id,*,worker_id)->Claim(operation_id,owner,fence,expires_at)`；`assert_current(claim)->None`。
- `reserve_node(pool_id,*,account_id,region,plan_id,image_id,operation_key)->ManagedNode`；caller 原子提交 Operation/outbox。
- `DatabaseWriteAuthorizer.assert_allowed(permit,*,action,account,resource_id)->None` 在每次 SDK 写前核验 Operation；测试 Fake provider 也必须走授权路径。

- [ ] **Step 1: 写并发配额和幂等失败测试。**

```python
@pytest.mark.django_db(transaction=True)
def test_only_one_create_fits_last_slot(pool_with_two_nodes, submit_create_concurrently):
    results = submit_create_concurrently(pool_with_two_nodes, workers=2)
    assert sum(r.accepted for r in results) == 1
    assert ManagedNode.objects.filter(pool=pool_with_two_nodes, consumes_quota=True).count() == 3

@pytest.mark.django_db
def test_same_key_changed_params_is_conflict(operation_service, create_request):
    first = operation_service.submit(**create_request)
    assert operation_service.submit(**create_request).id == first.id
    altered = {**create_request, 'params': {**create_request['params'], 'region': 'other'}}
    with pytest.raises(DomainError, match='参数'):
        operation_service.submit(**altered)
```

在 conftest 创建 `pool_with_two_nodes`（专用模型 Factory）和 `create_request`（有效 preview、fake account）；`submit_create_concurrently` 用两个线程各自关闭/新建 Django DB connection、Barrier 同时提交，返回 accepted/error_code；不要仅模拟行锁。outbox 用例注入 Broker 断开，恢复后重复投递但一次云动作。

- [ ] **Step 2: 运行四个指定测试文件，确认由于缺少操作引擎失败。**

```bash
uv run --project backend pytest -c backend/pyproject.toml backend/tests/test_quota_concurrency.py backend/tests/test_operation_idempotency.py backend/tests/test_outbox.py backend/tests/test_operation_fencing.py -q
```

- [ ] **Step 3: 实现短事务和 outbox。**

```python
with transaction.atomic():
    pool = NodePool.objects.select_for_update().get(pk=pool_id)
    used = ManagedNode.objects.filter(pool=pool, consumes_quota=True).count()
    if used >= pool.quota:
        raise DomainError('POOL_QUOTA_EXCEEDED', '节点额度已用完')
    node = ManagedNode.objects.create(pool=pool, consumes_quota=True, **node_fields)
    operation = Operation.objects.create(target_id=node.id, request_hash=request_hash, **op_fields)
    OutboxEvent.objects.create(operation=operation, schema_version=1)
```

同键查询在 quota 前完成并以唯一约束处理竞争；on_commit 只能唤醒 dispatcher，不能成为唯一可靠投递。每一步在数据库持久化结果再 ack；lease 过期遇到外部结果未知先 RECONCILIATION，不直接重试。取消保留已创建 resource，can_cancel 随步骤变化。

- [ ] **Step 4: 故障注入 broker outage、worker crash、重复消息、旧 fence、修改参数和取消。** 全部测试通过，核对 max quota 不超额；迁移 check/diff check 通过。
- [ ] **Step 5: 提交 `feat: add durable node operations and quota enforcement`。** 仅 add `backend/apps/{operations,nodes}`、对应 tests/conftest 和迁移。

### Task P3.2: 双云节点生命周期与安全隔离

**Files:**
- Create: `backend/apps/nodes/{lifecycle,reconciliation,execution_types}.py`、`backend/apps/operations/handlers.py`。
- Test: `backend/tests/{test_node_lifecycle,test_unknown_cloud_result,test_quarantine,test_node_replacement}.py`。
- Modify: `backend/apps/nodes/models.py`（NodeResource、细分状态）、相应新迁移。

**Interfaces:**
- Consumes: P2 `CloudProvider`、capabilities、MutationPermit；P3.1 Operation/claims/quota。
- Produces: `NodeLifecycle.create(node_id,*,operation_id)->None`；`quarantine(node_id,*,operation_id)->IsolationResult`；`reconcile(node_id,*,operation_id)->None`。
- `NodeLifecycle.dispatch(kind,node_id,*,operation_id)->None` 处理 start/stop/reboot/reinstall/rotate_ip/replace/delete/release_ip，未知 kind 拒绝；reinstall 必须带单独磁盘破坏确认。
- Shared DTO 定义如下，P4 只消费，不另建副本：

```python
@dataclass(frozen=True)
class IsolationResult:
    confirmed: bool
    evidence: dict

@dataclass(frozen=True)
class ApplyResult:
    applied_generation: int
    config_test_passed: bool
    service_restarted: bool
    rollback_performed: bool

@dataclass(frozen=True)
class ProbeResult:
    accepted: bool | None
    positive_control: bool
    fresh_connection: bool
    existing_session_closed: bool | None
    evidence: dict
```

- [ ] **Step 1: 写未知云结果和隔离证据失败测试。**

```python
def test_create_timeout_never_blindly_recreates(fake_cloud, lifecycle, prepared_node):
    fake_cloud.fail_after_create = True
    lifecycle.create(prepared_node.id, operation_id=prepared_node.operation_id)
    assert fake_cloud.create_calls == 1
    lifecycle.reconcile(prepared_node.id, operation_id=prepared_node.operation_id)
    assert fake_cloud.create_calls == 1
    assert fake_cloud.lookup_calls >= 1

def test_firewall_ack_alone_is_not_isolation(fake_cloud, lifecycle, prepared_node):
    fake_cloud.firewall_ack = True
    fake_cloud.external_probe_blocked = None
    result = lifecycle.quarantine(prepared_node.id, operation_id=prepared_node.operation_id)
    assert result.confirmed is False
```

Fake fixtures 在本任务 conftest 定义；prepared_node 含 Fake account、Operation 与有效 Claim。补 IPv6 宽泛规则、UDP、现有长连接、账号身份漂移、替代节点额度不足、停止但仍收费、删除后静态 IP 仍保留用例。

- [ ] **Step 2: 运行本任务四个测试文件，确认失败。** 使用总览指定 `uv run --project backend pytest -c backend/pyproject.toml` 入口。
- [ ] **Step 3: 按检查点实现生命周期。**

```python
if step.external_result_unknown:
    operation.mark_needs_reconciliation('CLOUD_RESULT_UNKNOWN')
    return
if node.security_state in {'REVOCATION_UNCONFIRMED', 'ISOLATION_UNCONFIRMED', 'QUARANTINED'}:
    if kind in {'start', 'reboot', 'open_firewall'} and not operation.is_verified_restore:
        raise DomainError('RESTORE_REQUIRED', '需先完成撤销状态核验')
```

创建确定命名/标签，保存外部资源与 request ID。平台原地换 IP 不支持时返回 CAPABILITY_UNSUPPORTED 和替代动作，不能默默建收费实例。节点协议端口规则由本系统独占管理；读取到无法证明归属的同端口或全端口 IPv4/IPv6 allow 时阻断发布与隔离判定。强制隔离在管理员确认后可替换受管协议端口的完整规则集，但保留 SSH 并在恢复时按当前期望状态重算；隔离按 firewall 回读与数据面证据判定，无法断开旧连接保持未确认；不得自动调用 stop/delete 代替。删除和释放需独立 preview，检查 external identity 及资源标签，云 confirmed absent 后才归还额度。

- [ ] **Step 4: 运行 Task 测试和 P3.1 回归；两平台 Fake 共用相同场景矩阵。** 检查任何失败未调用未经确认的资源删除。
- [ ] **Step 5: 提交 `feat: orchestrate dual-cloud node lifecycle and isolation`。**

### Task P3.3: 自有安装器、协议证书与有证据的探测

**Files:**
- Create: `installer/{install.sh,apply-config.sh,verify.sh,manifest.json,README.md}`、`installer/render/{config,credentials}.py`、`installer/licenses/`。
- Create: `backend/apps/nodes/{executor,ssh,probes,protocols}.py`、`backend/tests/{test_node_executor,test_ssh_fingerprints,test_generation_fence,test_protocol_capabilities}.py`。
- Create: `tests/installer/{test_cli,test_config,test_revocation_sessions}.py`、`deploy/docker/installer-test.Dockerfile`。

**Interfaces:**
- `NodeExecutor.apply_config(node_id,*,generation,config,operation_id,allow_security_rollback=False)->ApplyResult`。
- `capture_probe_sessions(node_id,*,credential_refs:list[UUID],operation_id)->dict[UUID,str]`：变更前建立持续连接并分配证据 session_id。
- `probe(node_id,*,credential_ref,expect_accept,operation_id)->ProbeResult`：新连接结果、正向控制、旧会话是否断开。
- 安装器 stdin JSON 为 `schema_version,node_id,generation,expected_previous_generation,config,action`；stdout 仅状态/步骤/版本/错误码，绝不输出秘密；exit 0成功、10参数、20配置、30代际冲突、40恢复失败。

- [ ] **Step 1: 写 generation 与安全回滚失败测试。**

```python
def test_stale_configuration_cannot_overwrite_revocation(remote_fixture):
    remote_fixture.apply(generation=5, clients=['new'])
    result = remote_fixture.apply(generation=4, clients=['revoked'])
    assert result.returncode == 30
    assert remote_fixture.current_clients() == ['new']

def test_security_change_never_rolls_back_revoked_user(executor, node, revocation_operation):
    result = executor.apply_config(node.id, generation=6, config={'clients': []},
                                  operation_id=revocation_operation.id,
                                  allow_security_rollback=False)
    assert result.rollback_performed is False
```

remote_fixture 是本任务创建的临时目录+容器安装器 harness，模拟 service restart 失败。另有每协议“旧连接保持→移除→重启→旧连接断开/新身份成功”真实本地 Xray 测试；不能用纯 Python Mock 替代协议行为证据。

- [ ] **Step 2: 用选定、哈希固定的 Xray 本地发行物运行失败测试，记录缺少 installer/executor 的预期失败。** 安装二进制只在隔离测试容器/临时目录，不在 macOS 注册系统服务。
- [ ] **Step 3: 实现结构化安装、锁与远端原子配置。**

```bash
# Linux 节点步骤核心；路径固定于本产品目录
exec 9>/var/lib/xray-manager/apply.lock
flock -x 9
# 在锁内比较 expected_previous_generation，再检查候选配置
xray run -test -config /run/xray-manager/candidate.json
install -m 600 /run/xray-manager/candidate.json /usr/local/etc/xray/config.json.next
mv /usr/local/etc/xray/config.json.next /usr/local/etc/xray/config.json
systemctl restart xray
```

所有候选与 generation journal 在锁内写入、fsync 和 rename；进程崩溃恢复读取 journal，不能单看 version 文件假定已经应用。SHA-256/架构/许可证离线检查；指纹不自动信任；未知版本拒绝。TLS 证书验证失败不能 READY；共享与独立凭据能力用测试矩阵固化。恢复普通安装使用旧有效配置，安全变更失败请求隔离。

- [ ] **Step 4: 验证 probes 确实经过节点：清空 proxy 环境、禁 curlrc、socks5h、凭据 stdin；持续连接与新连接分别测。**

```bash
bash -n installer/install.sh installer/apply-config.sh installer/verify.sh
shellcheck installer/install.sh installer/apply-config.sh installer/verify.sh
uv run --project backend pytest -c backend/pyproject.toml tests/installer backend/tests/test_node_executor.py backend/tests/test_generation_fence.py backend/tests/test_protocol_capabilities.py -q
```

- [ ] **Step 5: 提交 `feat: add verified xray installer and generation-safe executor`。** 测试二进制按 license/size 决策放 release artifact，仓库 manifest 保存摘要，不放运行凭据。

## P3 完成门禁

- [ ] 两云从空池到模拟 READY，所有错误保留正确资源与费用信息。
- [ ] 并发配额、重复消息、DB/Broker故障、旧 worker 和未知云返回不会重复创建。
- [ ] 本地 Xray 验证五协议的可用性、撤销粒度、TCP/UDP 和旧连接证据；证书策略通过。
- [ ] 隔离不足有 ISOLATION_UNCONFIRMED，未经确认不删除；资源释放不与删机绑在一起。
