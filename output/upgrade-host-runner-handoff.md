# 主机在线升级执行器交接

仅本地源码与测试；本子代理未进行 SSH、生产写入、云操作、commit 或 stage。
主代理集中追加 ledger/progress，以下命令与结果请录入统一事件。

## 文件

- `deploy/upgrade/runner.py`：root 单次执行器，严格 UUID 请求、SemVer、90 分钟 TTL、可信预置源码/不可变镜像、独占锁、防重放、快照导出、现有 release.sh、固定状态结果。
- `deploy/upgrade/{xray-manager-upgrade.service,xray-manager-upgrade.timer}`：root oneshot，每 15 秒检查，禁止日志输出。
- `deploy/upgrade/README.md`：固定目录、权限、catalog/manifest、安装、恢复边界。
- `deploy/compose/production.yml`：仅 admin-api 添加 XRAY_UPGRADE_ROOT 与 /var/lib/xray/upgrade 挂载；所有 API 均无 Docker socket。
- `tests/deploy/test_online_upgrade_runner.py`：16 条聚焦测试。

注意：deploy/upgrade 是未跟踪新目录，生产文件同步不能只依赖 git ls-files deploy，需显式包含。

## 契约

请求字段 schema_version/id/version/created_at/actor_id，与 backend/apps/identity/upgrade.py 相同。
结果 status QUEUED/RUNNING/SUCCEEDED/FAILED；phase 使用 VALIDATING/BACKUP/RELEASING/COMPLETE/ROLLBACK_REQUIRED。
共享后端 _PHASES 当前已包含所有执行器 phase。未知固定 error_code 后端会安全归一化为 UPGRADE_FAILED，不含原始命令输出。

准备目录权限：root0755 upgrade/results/releases，10001:10001 0700 requests，root0700 history，root0644 catalog。
源码发布快照包含完整 deploy/、installer/、VERSION；manifest 写 backend_image/frontend_image 的真实 digest。
正式固定 root=/var/lib/xray/upgrade，config=/etc/xray/config.env，current=/opt/xray/VERSION。

## 验证

- 首次有效 RED：最小 stub 后 9 failed/1 passed，exit1；实现后 10 passed，exit0。
- Compose 契约 RED：缺 admin 环境变量时 1 failed/12 passed，exit1；补挂载与环境后 13 passed，exit0。
- 真实快照命令参数、私有快照/临时目录清理、导出失败隐藏异常并保持 config/no release 两测试后 15 passed，exit0。
- 历史记录防饥饿 RED：101 个已完成记录后 pending 不被执行，1 failed，exit1；去除只扫描前100记录的限制后最终 16 passed in 1.12s，exit0。
- 完整 tests/deploy 在最后队列单行修复前：96 passed in 47.17s，exit0。使用现有 0.14.9 backend-final/frontend-layout 与 0.14.8 backup-tools 镜像，不代表本次新增后端在线升级镜像已重建。
- Ruff 0.13.1 check，exit0；format 已应用。
- git diff --check，exit0。
- scripts/check-boundary.sh，exit0。
- scripts/check-secrets.sh 全历史 162 commits 无泄露，exit0。
- 新增 deploy/upgrade 与本测试独立复制后 Gitleaks dir 扫描约49KB，无泄露，exit0（发生于最后队列测试添加前；新增测试仅合成 UUID/数字/状态）。

测试使用项目专用 PostgreSQL127.0.0.1:55435/Redis56382，所有云操作 Fake/无云写入。

## 生产与回退限制

- 本机 macOS 未运行 systemd-analyze verify，需主代理在已授权生产主机上执行。
- 需显式安装 unit/timer、目录权限、预置发布 catalog/source/manifest；API 开放不证明 timer 已运行。
- 发布失败仅恢复原始 config 字节，结果 ROLLBACK_REQUIRED；服务实际状态必须读回，数据库与安全历史不能逆向恢复。
- 中断 RUNNING 不重放，标记 UPGRADE_INTERRUPTED。
- 新版本 source 作为实际 Compose/release 来源保留；/opt/xray/VERSION 成功后更新，但 runner 自更新不在此次执行路径内，首版由主代理安装。
