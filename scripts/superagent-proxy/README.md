# superagent 出口代理(WSL 内自建 mihomo)

给 WSL 里的 superagent worker 用的出口代理。**运维手册见
[docs/ops/superagent.md](../../docs/ops/superagent.md) §12**,这里只放快速索引。

## 为什么有这个

改造前 worker 走宿主 Clash(`:7897`),并发探针实测**掉 8%**(55/60),
比直连还差 —— 那正是 GitHub 轮询健康位被打成 `error` 的来源。改成 WSL 内自建后 60/60。

## 三个脚本的分工

| 文件 | 干什么 | 什么时候跑 |
|---|---|---|
| `install.sh` | 装 mihomo + 预下 geoip + 渲染配置 + systemd 服务 + 6 小时刷新定时器 | 首次装、升级、改 `override.yaml` 后 |
| `render-config.py` | 拉订阅 → 校验 → 注入覆写与 `github` 测速组 → 原子落盘 | 由上面两个调用;`--from-file` 可离线调试 |
| `refresh.sh` | 重渲染、比对、热重载(`PUT /configs`) | 定时器每 6 小时;也可手动 |
| `probe.sh` | 三路对比(直连 / 宿主 / mihomo) | 换线路、怀疑代理没用时 |
| `selftest.sh` | 渲染逻辑的离线自测(17 条) | 改 `render-config.py` 后 |

## 密钥边界

订阅地址与 `config.yaml`(含全部节点凭据)只在 `/root/.dsh/proxy/`(600 权限),**不入库**。
仓库里只有脚本与 `override.yaml`(端口、测速组这些非敏感设置)。

## 自测

```bash
bash scripts/superagent-proxy/selftest.sh    # 17 条,不联网
```
