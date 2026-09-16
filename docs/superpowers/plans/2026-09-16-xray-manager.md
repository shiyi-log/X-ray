# 独立 X-ray 管理平台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在全新单仓库交付双云、自用、可强制撤销旧凭据的 X-ray 管理系统。

**Architecture:** Vben 前端与 Django 模块化单体分进程运行，PostgreSQL 保存事实，Celery/Redis 执行可靠任务。云平台通过能力适配器隔离，公开订阅进程只有订阅读取与解密权限，控制平面部署在独立服务器。

**Tech Stack:** Python 3.13、Django 5.2、DRF 3.16、PostgreSQL 17、Redis 7.4、Celery 5.5、Node 22 LTS、pnpm 10.33.0、Vben 5.7/Vue 3/Ant Design Vue、Docker Compose、Nginx。

**Spec:** [已确认设计规格](../specs/2026-09-16-xray-manager-design.md)

## Global Constraints

- 项目根目录 `/Users/a399/Desktop/data/X-ray`；所有相对路径以此为基准。
- Shop 三个来源仓库仅只读参考；禁止运行时导入、源码路径链接、读取其配置、测试数据库或密钥。
- `archive/` 禁止进入 Git、Docker context、CI artifact、发布包和测试扫描。
- 唯一超级管理员；无注册、多租户或普通用户。前端 Vben 二开，前后端同仓。
- 第一版同时交付 AWS Lightsail 与阿里云 SWAS；能力必须有证据，不支持与未验证有区别。
- 节点池默认配额 3 可调；真实 PostgreSQL 验证配额/幂等，不以 SQLite 替代。
- 强制撤销必须验证旧凭据与旧会话失效；隔离或撤销未确认时明确显示风险，禁止宣称成功。
- 所有阶段先本地模拟、专用测试环境；真实云成本、指定服务器部署、删除和释放须分别获得当前任务授权。
- 实施任务采用失败测试 → 最小实现 → 相关回归 → 文件范围审查。局部提交仅包含对应新项目文件；推送和发布独立处理。

---

## 当前事实与交付范围

本轮完成规格和计划。本地 Git 已初始化；原先 `nodes/`、`xray_service/` 的 4 个空文件保留，未并入计划代码，`static/` 为空。代码、数据库迁移、测试、安装器、云 SDK 调用、Vben 构建、服务器部署均尚未开始。

这套计划不包括修改 Shop 或迁走旧节点。不导入历史订阅/密钥；以后若需接管已有云资源，应作为单独功能，先验证归属与明确授权。

## 六个可独立验收的子计划

| 顺序 | 子计划 | 可验收产物 | 前置条件 |
| --- | --- | --- | --- |
| P1 | [基础与唯一管理员](2026-09-16-xray-p1-foundation.md) | 专用 PostgreSQL 上的认证/加密/API 测试通过 | 无 |
| P2 | [双云账号与适配器](2026-09-16-xray-p2-cloud.md) | 两平台 SDK 契约、能力矩阵、无秘密泄漏 | P1 |
| P3 | [节点、可靠任务与安装器](2026-09-16-xray-p3-nodes.md) | 模拟双云完整建机/安装/恢复，可验证并发不重复 | P1/P2 |
| P4 | [订阅与强制撤销](2026-09-16-xray-p4-subscriptions.md) | 四格式、不可变修订、逐节点撤销与隔离证据 | P3 |
| P5 | [Vben 与管理 API](2026-09-16-xray-p5-console.md) | 本地全流程浏览器验收、类型生成和生产构建 | P1；完整验收依赖 P2–P4 |
| P6 | [部署、恢复与验收](2026-09-16-xray-p6-delivery.md) | 独立 Compose、恢复演练、全套门禁、真机验收表 | P1–P5 |

关键顺序为 P1 → P2 → P3 → P4 → P6；P5 的 Vben 基线和登录在 P1 完成后可并行，业务页面等后端 OpenAPI 明确后再完成。P2 两个适配器可并行，但共享 DTO 先锁定；不要多人同时修改共享模型和初始迁移。

## 共享实现契约

Python 根包放在 backend/，使用 `config.settings.test`，pytest-django 管理独立 PostgreSQL 测试库。每个测试运行默认禁止出网，仅 loopback/Compose service 的专用数据库、Redis 例外；云/SSH Fake 不读取环境中的真实凭据。

所有阶段统一提供下列接口，各子计划负责实现并测试自己产出的部分：

```python
# P1: backend/common/crypto.py
class SecretStore:
    def encrypt(self, plaintext: bytes, *, purpose: str, aad: bytes) -> dict: ...
    def decrypt(self, envelope: dict, *, purpose: str, aad: bytes) -> bytes: ...

# P1: backend/common/errors.py
class DomainError(Exception):
    def __init__(self, code: str, message: str,
                 retryable: bool = False, details: dict | None = None): ...

# P3: backend/apps/operations/services.py
class OperationService:
    def submit(self, *, kind: str, target_id: UUID, params: dict,
               key: UUID, preview_id: UUID | None) -> Operation: ...

# P3: backend/apps/nodes/executor.py
class NodeExecutor:
    def apply_config(self, node_id: UUID, *, generation: int, config: dict,
                     operation_id: UUID,
                     allow_security_rollback: bool = False) -> ApplyResult: ...
    def probe(self, node_id: UUID, *, credential_ref: UUID,
              expect_accept: bool, operation_id: UUID) -> ProbeResult: ...

# P3: backend/apps/nodes/lifecycle.py
class NodeLifecycle:
    def create(self, node_id: UUID, *, operation_id: UUID) -> None: ...
    def quarantine(self, node_id: UUID, *, operation_id: UUID) -> IsolationResult: ...
```

以上 `...` 只表示跨计划 Python 接口签名而非空实现安排；返回类型、错误与行为在负责的 P1/P3/P4 子计划中定义。P2 定义云 DTO 和 `MutationPermit`，写授权由 P3 的数据库 Operation 再验证，不能信任调用者自行构造的 permit。

## 执行与记录规则

- [ ] 执行前运行 `git status --short --branch`，读取规格及当前阶段计划。
- [ ] 创建 `docs/progress.md`，记录 task、提交、命令、结果与未执行外部门禁；不填造测试结果。
- [ ] 每个任务完成定向测试和 `git diff --check` 后选择性提交；新需求先修改规格/计划，避免实现时暗增范围。
- [ ] 每阶段产物至少通过本地可重现检查，再开启依赖阶段。
- [ ] 最终验收逐项用 `passed / failed / blocked / not-run / risky_not_executed`；代码验收、真机验收、生产发布分别记录。

## 预计工作量与里程碑

以下是实施前估算，不是已完成时间：P1 2–3 人日，P2 3–4 人日，P3 4–6 人日，P4 4–6 人日，P5 4–6 人日，P6 本地 3–4 人日，总计约 20–29 人日。可并行的适配器与前端基础可缩短日历时间；云购买/权限、域名证书和两平台真机限制另外计算。

P1 完成即可演示真实独立登录；P3 完成可用模拟双云验证管理动作；P4 完成才具备完整撤销语义；P5 完成可演示全套 UI；P6 完成并通过授权真机矩阵后才可宣称运行验收通过。

## 规格覆盖自审

| 要求 | 实施任务 |
| --- | --- |
| 全新单仓库、归档隔离、无 Shop 导入 | P1.1、P6.1/P6.3 |
| 唯一管理员、MFA、恢复/会话失效 | P1.2/P1.3、P5.1、P6.2 |
| 密钥信封加密、只读秘密交付 | P1.2、P2.1、P4.1、P6.2 |
| 双云、能力差异、真实费用与归属 | P2.1–P2.3、P3.2、P6.3 |
| 配额、幂等、outbox、fence、未知云结果 | P3.1/P3.2 |
| SSH 指纹、固定安装资产、协议与证书 | P3.3、P6.3 |
| 四格式、Token、修订、撤销/隔离/恢复 | P4.1–P4.3、P5.3、P6.3 |
| Vben、新契约、危险交互、真实状态 | P5.1–P5.3 |
| 独立服务器/数据库、回滚、离机备份 | P6.1/P6.2 |
| 云验收授权和资源残留清单 | P6.3 |
