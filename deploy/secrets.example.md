# 部署秘密清单

本文件只描述秘密文件的名称和用途，不包含示例秘密值。实际文件必须在独立服务器上创建，不进入仓库、镜像、Compose 环境变量、命令参数或验收产物。

## 文件边界

| 配置键 | 使用者 | 用途 |
| --- | --- | --- |
| `XRAY_DJANGO_SECRET_KEY_FILE` | admin、worker、beat、outbox、migrator | 控制面 Django 签名密钥 |
| `XRAY_SUBSCRIPTION_DJANGO_SECRET_KEY_FILE` | subscription only | 独立 Django 签名密钥，挂载为订阅容器的 `django_secret_key` |
| `XRAY_CONTROL_MASTER_KEY_FILE` | admin、worker、migrator | 云、SSH、MFA 控制域密文 |
| `XRAY_SUBSCRIPTION_MASTER_KEY_FILE` | admin、subscription、worker、migrator | 订阅 payload 密文 |
| `XRAY_*_DB_PASSWORD_FILE` | 对应数据库角色 | 每个进程独立数据库口令 |
| `XRAY_CLOUD_CREDENTIALS_FILE` | worker | 云 SDK 的显式凭据载体 |
| `XRAY_*_TLS_KEY_FILE` | gateway | 两个入口各自的 TLS 私钥 |
| `XRAY_BACKUP_PGPASS_FILE` | backup tools | 只读备份/隔离恢复数据库口令文件 |
| `XRAY_BACKUP_AGE_RECIPIENT_FILE` | backup tools | 公开 age recipient，不含私钥 |

私密文件使用绝对路径，所有者为部署账户或受限运维组，权限只能是 `0400`、`0440`、`0600` 或 `0640`。证书公钥可以是 `0644`。`preflight.sh` 只检查存在性、非空、权限和 Compose 解析，不输出内容。

## 创建原则

- Django、数据库和主密钥使用密码管理器或 HSM/KMS 生成；不要在 shell 历史中用 `echo secret` 创建。
- control 与 subscription 主密钥分别托管、分别轮换，不能互相代用。
- 订阅 Django 签名密钥独立生成，不与控制面的 Django 签名密钥或订阅 payload 主密钥复用。
- 云凭据只允许 worker 读取，并限制到账户、区域和所需 API；不允许 SDK 默认凭据链。
- age 恢复私钥不放在控制服务器。备份端只保存公开 recipient，恢复时通过离机审批临时挂载私钥文件。
- TLS 私钥、数据库 owner 口令和恢复私钥不写入备份 manifest。

真实值准备完毕后复制 `deploy/compose/config.example.env` 到服务器的受限目录并改为真实路径。不要在仓库内创建 `.env` 版本。
