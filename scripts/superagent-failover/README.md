# superagent-failover —— 模型兜底代理

superagent 的模型是 `wb-pool` / `cn:deepseek-v4.1-flash`。当 cn 这条线路挂了(网关回
`model_unavailable` / `no_healthy_account`,或干脆超时),DSH 自己没有回退链可用:
`@deepseek-ai/dsh-agent-default-model` 和 `@deepseek-ai/dsh-llm-pi-ai` 都只认「一个 provider +
一个模型 id」。于是所有工单一起失败,而且失败得很难看(每条工单都停在同一条错误上)。

这个代理挡在 DSH 与网关之间,只做一件事:把请求体里的 `model` 依次换成回退链上的下一个,
直到某次真的成功。默认链:

```
cn:deepseek-v4.1-flash  →  global:deepseek-v4.1-flash  →  global:deepseek-v4.1-flash-sg
```

除 `model` 与随之变化的 `content-length` 外,请求与响应字节原样转发;不解释、不改写、
不缓存、也不需要密钥(`Authorization` 由 DSH 自己带上,代理只转发)。

## 什么时候换、什么时候不换

| 触发 | 结果 |
|---|---|
| 网关 `model_unavailable` / `no_healthy_account` 等线路类错误码 | 换下一条 |
| 5xx、402(按模型计费/额度) | 换下一条 |
| 连接失败 / 等响应头超时 | 换下一条 |
| SSE 200 但**首帧**就是 `error` 事件 | 换下一条(此时客户端还没收到任何字节) |
| 400 参数错、401/403 鉴权 | **不换**,原样返回(换了也是同样报错,只会把真 bug 藏进噪声) |
| 模型不在链上(有人把模型换成了别的) | **不换**,原样单发 |

失败过的线路进入冷却(默认 30s),期间直接跳过;冷却结束后下一次请求重新试它 ——
所以 cn 恢复之后不需要人工切回。

## 文件

| 文件 | 作用 |
|---|---|
| `proxy.mjs` | 代理本体(Node 内置模块,无依赖) |
| `install.sh` | 装成 WSL 的 systemd 服务 `superagent-failover`,装完自检 |
| `selftest.mjs` | 12 条自测:假上游 + 真代理进程,不联网 |

## 装 / 看 / 卸

```bash
# 装(WSL 里,幂等;再跑一次 = 升级)
wsl -e bash -c 'bash /root/src/chatapp/scripts/superagent-failover/install.sh'

# 看
wsl -e bash -c 'systemctl status superagent-failover --no-pager'
wsl -e bash -c 'journalctl -u superagent-failover -n 50 --no-pager'
wsl -e bash -c 'curl -s http://127.0.0.1:8788/__failover/status'

# 自测(不联网,任何时候都能跑)
wsl -e bash -c 'cd /root/src/chatapp && node --test scripts/superagent-failover/selftest.mjs'
```

装完还要让 DSH 走代理:把 `/root/.dsh/profiles/superagent/cordis.patch.yml` 里
`llm-pi-ai.providers.wb-pool.baseURL` 改成 `http://127.0.0.1:8788/v1`,重启 superagent。
卸载时反过来改回 `https://wb.shiliu153.me/v1`。

## 配置(env,都有默认值)

| 变量 | 默认 | 含义 |
|---|---|---|
| `FAILOVER_LISTEN` | `127.0.0.1:8788` | 监听地址;写 `:0` 用随机端口,启动日志会打印实际端口 |
| `FAILOVER_UPSTREAM` | `https://wb.shiliu153.me` | 上游根地址 |
| `FAILOVER_MODELS` | cn → global → global-sg | 回退链,逗号分隔,顺序即优先级 |
| `FAILOVER_COOLDOWN_MS` | `30000` | 线路失败后多久内不再尝试 |
| `FAILOVER_HEADER_TIMEOUT_MS` | `600000` | 等上游响应头的最长时间(长上下文首字节可能很慢) |
| `FAILOVER_MAX_BODY_BYTES` | `64MiB` | 请求体超过它就完全不改写 model、原样单发 |
| `FAILOVER_QUIET` | 空 | 非空 = 只打切换/失败日志,不打每次请求 |

## 边界(别指望它做这些)

- **不是安全边界**:它只认 `model` 字段,不校验、不鉴权、不记账。
- **流到一半才失败救不回来**:已经往客户端写了字节,再换线路就会串话。这类失败交给
  DSH 自己的 `llm-retry` 重试,下一次请求会因为冷却而落在线路更好的那条上。
- **强制 `accept-encoding: identity`**:代理要读响应体才能发现「200 其实是错误」,
  让上游压缩就把这个判断能力换成了省下来的那点字节。
- **管线只有一条**:代理挂了 = superagent 的模型调用全挂。所以它有自己的 systemd 服务
  (`Restart=always`),而不是挂在 DSH 的进程树里。
