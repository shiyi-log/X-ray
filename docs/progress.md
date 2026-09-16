# 开发进度

本文件只记录已执行的命令和证据。状态只能使用 `passed`、`failed`、`blocked`、`not-run` 或 `risky_not_executed`；未授权的真实云/生产动作不得写成 `passed`。

| date | phase | task | commit | command | exit_code | evidence | status | rollback_ref |
| --- | --- | --- | --- | --- | ---: | --- | --- | --- |
| 2026-09-17 | baseline | capture initial repository | `2da51e7` | `git show --stat --oneline HEAD` | 0 | `v0.0.0-baseline` | passed | `v0.0.0-baseline` |
| 2026-09-17 | P0 | migration/boundary/traceability | `2885503` | `./scripts/check-runtime.sh`; skill validator; `pytest backend/tests -q` | 0 | local command output | passed | `v0.0.0-baseline` |
| 2026-09-17 | P1 | administrator, MFA, encryption | pending | `pytest backend/tests -q`; `manage.py makemigrations --check --dry-run` | 0 | pending commit artifact | passed | `v0.0.1` |
| 2026-09-17 | P2 | dual-cloud contracts | pending | pending | - | pending | not-run | `v0.1.0-foundation` |
| 2026-09-17 | P3 | operations and nodes | pending | pending | - | pending | not-run | `v0.2.0-cloud` |
| 2026-09-17 | P4 | subscriptions and revocation | pending | pending | - | pending | not-run | `v0.3.0-nodes` |
| 2026-09-17 | P5 | Vben console | pending | pending | - | pending | not-run | `v0.4.0-subscriptions` |
| 2026-09-17 | P6 | delivery and recovery | pending | pending | - | pending | not-run | `v0.5.0-console` |

真实 AWS/SWAS、远程 SSH、Google 公网探测、独立生产服务器、实例删除和 IP 释放在获得具体授权前保持 `blocked` 或 `not-run`。
