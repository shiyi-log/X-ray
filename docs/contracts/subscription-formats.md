# 订阅格式契约

P4 同一修订最多生成 Shadowrocket、Clash、Mihomo 与 V2Ray 四份内容。各格式独立过滤兼容 endpoint；没有交集时记录 unavailable reason，不输出看似有效的空配置。

| 格式 | 固定验证器 | Shadowsocks | SOCKS5 | VMess | VLESS | Trojan |
| --- | --- | --- | --- | --- | --- | --- |
| Shadowrocket | 独立 URI 规范 fixture | 支持 | 支持 | 支持 | 支持 | 支持 |
| Clash | Clash 1.18.0 `-t` (`sha256:8d1081...b807c`) | 支持 | 支持 | 支持 | 不支持 | 支持 |
| Mihomo | Mihomo 1.19.12 `-t` (`sha256:faa7f8...36c8`) | 支持 | 支持 | 支持 | 支持 | 支持 |
| V2Ray | Xray 26.3.27 `run -test` | 支持 | 支持 | 支持 | 支持 | 支持 |

TLS endpoint 必须验证证书，SNI 来自 `server_name`，生产渲染拒绝 `allowInsecure`。IPv6 URI 使用方括号，userinfo 进行百分号转义，VMess 使用 base64 JSON。当前自动化仅证明固定 fixture 被相应解析器接受；Shadowrocket 没有可用于 CI 的官方解析器，真实 iOS 导入验收保持 `not-run`，不得由本地规范检查替代。

运行：

```bash
XRAY_TEST_BINARY=runtime/xray/v26.3.27/xray \
  bash tests/subscriptions/verify_formats.sh
```

脚本缺少 Docker、固定镜像或固定 Xray 二进制时非零退出。测试 fixture 只含显式的测试凭据，不得替换为生产订阅或真实 Token。
