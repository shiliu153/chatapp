# superagent 运维手册(WSL)

> 面板:`http://127.0.0.1:3082`(Windows 浏览器直接开)。Overview 只列「需要人」的项;健康时是空的。
> 设计见 [docs/superpowers/specs/2026-11-07-superagent-dev-workflow-design.md](../superpowers/specs/2026-11-07-superagent-dev-workflow-design.md),
> 实施计划见 [docs/superpowers/plans/2026-11-07-superagent-dev-workflow.md](../superpowers/plans/2026-11-07-superagent-dev-workflow.md)。

## 1. 启停与身份

| 事 | 命令 |
|---|---|
| 启动 / 查状态 / 停止 | `wsl -e bash /root/start-superagent.sh start` / `status` / `stop` |
| 状态退出码 | `0` 正常 · `1` 没跑 / 跑了两份 / 不响应(可试重启)· `2` 某部件报错(重启无效)· `3` 等设置 |
| agent 账号 | `~/.local/bin/gh-agent api user --jq .login` → `shiliu655` |
| agent 检出 | `/root/dsh-superagent`(升级就是 `git pull && pnpm install && pnpm build`) |
| 仓库母体 | `/root/src/chatapp`;工单 worktree 在 `/root/.dsh/state/superagent/work/` |
| 数据 | `/root/.dsh/state/superagent/orchestrator.sqlite`(**升级前必须备份**) |
| 模型 | `wb-pool` / `cn:deepseek-v4.1-flash`,经本地兜底代理(`127.0.0.1:8788`,见 §10),密钥在 `/root/.dsh/superagent.env` |
| 代理 | `start-superagent.sh` 启动时导出宿主网关 `:7897`;代理挂了表现为 fetch / npm / pub 全部超时 |

**面板当前设置**(2026-11-07):`maxWorkers=2`、`blockedCommands=[ssh, scp, rsync]`、
`prepare` 只做 `git fetch` + `git worktree add`(代理不写在这里)、
prompt `scope`/`delivery` 追加了本项目条款(一单一条栈、verify 唯一入口、app UI 必须 draft)、
eval 模式 `observe`、允许清单只有 `shiliu153`。

## 2. 本地验证环境(worker 靠它自证)

| 组件 | 位置 / 版本 | 说明 |
|---|---|---|
| MySQL + Redis | `docker compose -f docker-compose.ci.yml up -d --wait` | MySQL `127.0.0.1:13306`、Redis `127.0.0.1:16379`;端口刻意避开 Windows 本机 3306/6379 |
| 后端解释器 | `~/venvs/chatapp`(3.12) | `scripts/verify.sh bootstrap` 建;CI 用 3.11,差异见 §6 |
| Node | `~/node22`(22.x,与 `web.yml` 一致) | Node 24 会让 web 一条 jsdom 用例失败 |
| Flutter | `~/flutter`(3.47.2,与 `app.yml` 一致) | **不要**用 `/mnt/d/.../flutter`(Windows SDK) |

一条命令跑全部五栈:`cd <工单目录> && scripts/verify.sh all`。
**web / app 必须在 Linux 文件系统上跑**——`/mnt/*` 是 9p,慢到 vitest/flutter 超时(脚本会拒绝)。

新增 WSL 发行版或换机器时的依赖清单:`docker`(Docker Desktop 的 WSL 集成)、
`python3.12-venv`、`unzip`、`xz-utils`、`git`、`tmux`。

## 3. Ticket 卡住了怎么处理

| 现象 | 处置 |
|---|---|
| **派单后一直没动静**(面板 Overview 无 Working、`work/` 下没有新目录) | **先确认「是否入队」**,不要先怀疑 worker / Docker / 模型 —— 见 §4 的「入队三连」。`status` 全绿也不能证明评论已进队列 |
| `person / blocked`、`person / failed` | 在面板上直接回一句让它继续;或 **Retry**(新 Assignment,同 Session / 同目录 / 同分支) |
| `person / delivery` | Input 没送达,重试是唯一解法,**不要**删工单 |
| `The prepare command failed` | 输出里写着原因(克隆路径、代理、ref 冲突)。修好后 Retry |
| 工单跑到一半不动 | 先看面板 `load` 与 `worker` 健康位;进程在就 Retry,进程没了按 §1 重启 |
| `verify.sh` 报「没有可用的 venv」 | 跑 `scripts/verify.sh bootstrap` |

## 4. 一次工单的完整闭环(人工部分)

1. 面板 / issue 收到「PR #N 就绪」→ 评审 diff(它只是「就绪」,不等于可合)。
2. 碰 `app/` 的:PR 应为 draft → 拉分支到 Windows → 装模拟器 → 逐页手测截图 → 贴进 PR → 勾模板第 4 项。
3. CI 六轨绿 → **squash 合并** → 删分支。
   **别在母体里 `git push origin --delete`**:母体没有 credential helper,https remote 会**静默挂住**
   等输入(不是报错)。删已合并分支用页面,或 REST
   `DELETE /repos/shiliu153/chatapp/git/refs/heads/<branch>`(token 用 `~/.dsh/github-mcp-token.txt`)。
4. **合并后立刻收尾:一条命令(L1)**
   ```bash
   wsl -e bash -c 'bash /root/src/chatapp/scripts/superagent-closeout.sh --apply'
   ```
   它依次做:探测并导出代理 → `fetch origin master` → 母体 `pull --ff-only`
   (**脏工作区 / 有本地提交时拒绝并退出 2**,绝不猜测)→ `superagent-prune.sh --apply` →
   报告 Windows 仓库是否跟上。末尾给一行机器可读状态:

   ```
   CLOSEOUT ok mother=<sha> windows=<sha> same=yes|no pulled=0|1 prune=ok(n)|warn|skipped mode=apply
   ```

   - **Windows 仓库不由它改动**:WSL 的 git 在 `/mnt/*` 上会把 CRLF 工作区搞乱。`same=no` 时自己在 Windows 侧跑
     `git -C D:\pycharmproject\chat_app pull --ff-only`(或交给每小时定时任务)。
   - **fetch 失败不算失败**(issue #108 那一类):退回本地记录的 `origin/master` 判定 + 打警告;
     只有「落后又拉不动」才退出 2。
   - `--check` 只报告不动手;`--quiet` 只在有动作/异常时说话(定时任务用)。
   - **快进不发第二次网络请求**:fetch 成功后只用 `git merge --ff-only origin/master` 做纯本地快进。
     旧版这一步是 `git pull`,而 `pull` 内部会**再 fetch 一次** —— 于是刚被上面容错掉的抖动会在这里变成
     `die`,收尾停在进行到一半(决定同步之后、prune 之前)。2026-11-07 实测踩到过一次
     「fetch 成功了、紧接着 pull 报 gnutls 握手失败、收尾退出 1」。
   - 自测:`bash scripts/test_superagent_closeout.sh`(11 条,纯本地 git 仓库,不联网)。
   - ⚠️ **鸡生蛋**:脚本自己也在母体里,所以「脚本刚上线 / 刚更新」时要先手动引导一次
     `git -C /root/src/chatapp pull --ff-only`(带代理),之后才能用它。
   - 母体不自动跟随 `origin/master`,而 prune 脚本就住在母体里 —— **先 pull 再 prune** 的顺序不能反。

   **`prune` 的判定值(看 closeout 输出或单独跑时)**:

   | 值 | 含义 | 会不会清 |
   |---|---|---|
   | `merged=yes` | `git cherry` 按 patch-id 认出来了(**单提交**分支 + squash 时成立) | 会 |
   | `merged=yes-pr` | patch-id 认不出(分支有多个提交,被 squash 成一条),改问 GitHub「这个 head 有过已合并的 PR 吗」 | 会 |
   | `merged=no` | 两条都不成立(或网络不通、`GH_CLI` 不可用) | **不会**,只报告 |
   | `merged=empty` | 分支上**一个提交都没有**(`ahead=0`)—— 工单刚建 worktree / 正在写第一个文件 | **不会**,只报告(2026-11-08 补) |
   | `dirty≠0` | worktree 有未提交/未跟踪文件(常见:`app/macos/Flutter/` 这类生成物) | **不会**,先自己清干净 |

   **`merged=empty` 为什么必须单独一档**:空分支在 `git cherry` 下没有任何 `+` 行,
   旧版会因此判成 `merged=yes` —— 干净的空 worktree 会被 `worktree remove --force` 删掉,
   而它很可能正在干活。2026-11-08 实测时 #125 的 worktree 是靠 `dirty=3` 才没被删的。
   判不出来时唯一安全的动作是保留;真的废弃了,人手 `git worktree remove` 收尾。

   **`refs/dsh-superagent/*` 的清理(2026-11-08 补)**:这些临时引用**无法反查属于哪个工单**,
   所以只在「本轮一个 worktree 都没保留」时才删;只要还有在飞 / 未合并 / 有改动的 worktree,
   就打印「本次不动 refs/dsh-superagent/*」并原封不动(旧版一刀切删,会把在飞工单的引用一起删掉)。

   **退出码(2026-11-07 #108 修复后的行为)**:`0` = 正常,含「无可清理」的空转 —— 此时
   **根本不联网**(不 fetch、不动 `refs/dsh-superagent/*`);`2` = 确实有工单 worktree 但 fetch 不通
   (或判定 / 清理出错),**一个 worktree 都没删**,修好网络或代理再跑。

   网络兜底用的是 `/root/.local/bin/gh-agent`(可用 `GH_CLI=...` 覆盖,置空即关掉)。
5. 纯文档 PR(只动 `docs/**`):六轨都不触发、**没有 check runs 是正常的**,本地
   `scripts/verify.sh contract` 绿即可直接 squash 合并,不必再单独占一轮确认。
   2026-11-08 起这一步已由 `.github/workflows/auto-merge.yml` 自动完成(见 §8)。

**派工与关单的两条硬规矩(2026-11-07 补,两条都是「不报错、只沉默」的坑)**:

- **派工后 ≥90 秒核回执,而且要用「入队三连」核,不能只看游标**。见下面 §4.1。
- **PR 正文必须有 `Closes #<编号>`**。GitHub 只认 `Closes` / `Fixes` / `Resolves`,
  正文别处提到编号不算,squash 提交信息里带编号也不算。漏写 = 合并后 issue 一直悬着
  (#102 就这么悬了两小时)。实测记录见计划文档 §10.1。

### 4.1 派单后必须做「入队三连」(2026-11-08 补,踩过一次真的丢单)

`@shiliu655` 的评论**不等于**工单已入队。2026-11-08 实测:#129 / #130 两台单在 19:02 派发,
13 分钟后 `work/` 仍然空、issue 里连回执都没有,而 `status` 全部 `ready`、模型兜底代理也 `ok` ——
最后查明是**评论压根没进队列**。

**三件都要真、缺一就是没入队**(把 `<n>` 换成 issue 号):

```bash
# 1) 线程是否建立 + 是否真的产生了 trigger
wsl -e bash -c 'python3 - <<PY
import sqlite3
db=sqlite3.connect("file:/root/.dsh/state/superagent/orchestrator.sqlite?mode=ro",uri=True);c=db.cursor()
n="<n>"
print("thread        :", c.execute("select count(*) from thread where key=?",(f"github:{n}",)).fetchone()[0])
print("trigger_thread:", c.execute("select count(*) from trigger_thread where thread=?",(f"github:{n}",)).fetchone()[0])
print("cursor        :", c.execute("select value from kv where key=?",(f"github-cursor:{n}",)).fetchone())
print("tickets       :", c.execute("select count(*) from ticket where value like ?",(f"%github%{n}%",)).fetchone()[0])
PY'
# 2) 有没有真的开了 worktree(目录名带 ticket id)
wsl -e bash -c 'ls -1 /root/.dsh/state/superagent/work/'
# 3) issue 里有没有回执评论(面板 Overview 有没有 Working)
```

**⚠️ 最容易误判的一点:游标前移 ≠ 入队。** `github-cursor:<n>` 在读取该线程后**无论有没有产出
trigger 都会前移**;真正的判据是 `thread` / `trigger_thread` / `ticket` 三张表有没有记录。
今天的现象正是「`github-cursor:129` 已推进到 19:04:55,而 `trigger` / `thread` / `ticket` 全空」。

**机制**(`src/sources/github.ts::pollNotifications` + `readThread`):读线程评论的取数起点是
`max(该线程自己的游标, 全局通知游标)`,再对每条评论做 `fresh()` 过滤。于是「评论早于上一轮通知
游标」时会被结构性过滤掉,而游标照常前移 —— 这条评论就**永久丢失**,且**没有任何错误日志**
(所以 `status` 不会报错)。新建 issue 60 秒内派单是高发场景,但 2026-11-08 证实在
**已存在的 issue 上、合并后紧接派单**时同样会发生。

**处置:补发一条新评论,不要改 issue 正文。** 正文触发只认 opening(`issueTrigger` 取
`created_at`),后改正文不会被读;而新评论的时间戳一定晚于旧游标,能被正常收进来。
重发同一条指令是无害的(trigger id 幂等),**漏发才是时间损失**。今天补发后 2 分钟内
`thread` / `ticket` / `worktree` 三样齐全,worker 也立刻回了认领评论。

**顺带记住**:`work/` 长时间为空 + `status` 全绿 = 先查入队,再查 worker。排查顺序反了会白等十几分钟。

实测记录:计划文档 §10.2(2026-11-07 首例,新建 issue 60 秒内派工)、§10.3(2026-11-08 复发,
已存在的 issue + 合并后紧接派单,证明旧经验「≥90 秒再核」不够 —— 判据只能看 `thread` /
`trigger_thread` / `ticket` / `work/` 四样,不能看游标)。

## 5. 升级与回滚

```bash
# 1) 确认没有 Executor 正在跑(面板 Overview 无 Working)
cp /root/.dsh/state/superagent/orchestrator.sqlite /root/.dsh/state/superagent/orchestrator.sqlite.bak-$(date +%F)
cd /root/dsh-superagent && git pull && pnpm install && pnpm build
wsl -e bash /root/start-superagent.sh restart   # 从 Windows 侧执行
wsl -e bash /root/start-superagent.sh status
```

新版迁移过的库**旧版打不开**:回滚必须用上面那份备份。升级后检查面板 Prompts 里标注 `Default updated` 的段。

## 6. 已知偏差(出现「本地绿 CI 红」时先看这里)

| 偏差 | 影响 | 处理 |
|---|---|---|
| 本地 Python 3.12 / CI 3.11 | Django 5.2 两边都支持;极少数库行为不同 | 优先怀疑版本差异;必要时给 compose 加 `python:3.11` 服务 |
| 生成物校验忽略行尾 | Windows 检出是 CRLF,WSL 的 git 会把全仓算成改动 | 脚本用「比内容」而不是 `git diff --exit-code` |
| WSL 用 Docker Desktop 的引擎 | 容器端口发布在 Windows 宿主上 | 所以 13306/16379 避让本机 3306/6379 |

## 7. 授权与边界(改之前想清楚)

- 允许清单只有 `shiliu153`;bots 仅 `dependabot[bot]`;eval 模式 `observe`(proactive 只记录不执行)。
- `blockedCommands` 只是按命令名拦的 shim,**不是安全边界**;真正的边界是
  `/root/.ssh` 保持为空 + 人合 PR + 面板不配 merge CLI。
- agent 以自己的账号(`shiliu655`)提交与评论,所有动作都在仓库可见。

## 8. 自动合并(L2,2026-11-08 起)

> 设计见 [自动化阶梯 spec](../superpowers/specs/2026-11-08-superagent-automation-ladder-design.md) §4。
> 一句话:**worker 依然没有合并能力**;合并由 GitHub Actions 里的**确定性脚本**按白名单执行。

| 事 | 命令 / 位置 |
|---|---|
| 开关(唯一总闸) | `gh variable set AUTOMERGE --body on\|off --repo shiliu153/chatapp` |
| 白名单(唯一事实来源) | `.github/workflows/auto-merge.yml` 里的 `WHITELIST_PREFIXES`,当前只有 `docs/` |
| 手动跑一轮(不合并) | `gh workflow run auto-merge.yml -f dry_run=true --repo shiliu153/chatapp` |
| 看日报 | Actions → `自动合并（白名单）` → 每次运行的 **Summary**(合并了谁 / 跳过了谁 / 为什么) |
| 看审计痕迹 | 被合并的 PR 上有一条评论(命中白名单、checks 结论、revert 命令) |
| 紧急停 | 把 `AUTOMERGE` 设为 `off`;下一轮扫描直接退出 0,不合并任何东西 |
| 回滚一次自动合并 | `git revert --no-edit <sha> && git push origin master`(人做) |

**启用记录**:2026-11-08 `AUTOMERGE=on` 并当场验证两件事 —— ①`workflow_dispatch` 干跑一轮(exit 0,无 PR 时只写「没有开着的 PR」);
②首个真实样本就是本文这次改动所在的 PR:它只动 `docs/`,在 checks 通过后被 workflow 自己合并,PR 上留下了
「自动合并(L2)」审计评论与合并 SHA。此后 `docs/**` 的 PR 不需要人点合并。

**合并条件**(全部满足才合):开关开 · base=master · 非 draft · 作者是 `shiliu655` · 1–20 个文件**全部**命中白名单 ·
无 `no-auto-merge`/`blocked`/`needs-human` 标签 · checks 无未完成且无失败(**0 个 check 视为通过**,纯文档 PR 的正常形态)·
`mergeable=MERGEABLE` · 近 24h 的 `[auto]` 合并数 < 8。

**人的否决票**:给 PR 打 `no-auto-merge` 标签即可永久拦住它(比关总闸精确)。

**已知偏差(出现异常先看这里)**:
- 用 `GITHUB_TOKEN` 合并**不会**触发 master 上的 `push` 轨。要保留那道二次确认,加 secret
  `AUTOMERGE_TOKEN`(fine-grained PAT),workflow 会自动优先用它。
- 纯文档 PR 有 **0 个 check run**:「没有红」不等于「跑绿了」,门仍是本地 `scripts/verify.sh contract`。
- `gh` 在 worker 的 PATH 里,shim 只按命令名拦 ⇒ **技术上**它能 `gh pr merge`。现在靠 `AGENTS.md` 自律;
  要变成硬拦,加一个拒 `merge`/`release` 子命令的 `gh` 包装器(见 spec §7 未决问题 4)。
  **2026-11-08 已落地**:见 §9。
- ~~master 目前没有任何分支保护~~ → **2026-11-08 已开 ruleset**(`master: 必须走 PR + 禁强推`):禁删除、禁强推、
  必须走 PR(0 个 approval 即可合,以兼容自动合并);`shiliu153` 在 bypass 名单里,worker 账号不在。
  实测:worker 账号直推 master 被拒(`push declined due to repository rule violations`),推特性分支照常。

## 9. worker 侧硬拦:gh 包装器(gh-guard,2026-11-08 起)

面板的 `blockedCommands` 只按**命令名**拦(`ssh`/`scp`/`rsync`),而 `gh` 在 worker 的 PATH 里 ——
所以「agent 不自合、不发版」原先只是 `AGENTS.md` 的自律。`scripts/gh-guard/gh` 把它变成机械拦截。

| 事 | 命令 |
|---|---|
| 安装(一次性) | `wsl -e bash -c 'bash /path/to/repo/scripts/gh-guard/install.sh'` → 装到 `/usr/local/bin/gh` |
| 自测(不联网) | `wsl -e bash -c 'sh scripts/gh-guard/selftest.sh'` → 13 条,含 5 条拒绝 / 8 条放行 |
| 卸载 | `rm /usr/local/bin/gh`(真 gh 在 `/usr/bin/gh`,不受影响) |
| 被拒记账 | `/tmp/gh-guard.log`(每行 `时间 DENY 动作 :: 完整命令`) |

**拦什么**:`gh pr merge`、`gh release create|edit|delete|upload`、`gh repo delete|edit|archive`、
`gh api` 里改 `refs/heads/master|main` 的写操作、graphql `mergePullRequest`。

**放什么**:`pr create/view/list/checks/diff`、`api` 只读、`auth git-credential`、`release list` 等 ——
拦太宽 worker 就干不了活,然后它会去找绕过的办法。

**为什么 PATH 生效**:`/root/start-superagent.sh` 里 `export PATH="/usr/local/bin:$HOME/.local/bin:$PATH"`,
`/usr/local/bin` 在 `/usr/bin` 之前,所以 worker 与人的 `gh` 都会走 shim。

⚠️ **这不是安全边界**:任何进程都能 `exec /usr/bin/gh`。真正的边界是 §8 的 ruleset(禁直推、必须走 PR)
与「WSL 里没有生产密钥」。shim 的作用是**把误操作变成一条明确的拒绝信息**,而不是拦住有意的绕过。

## 10. 模型兜底(cn → global → global-sg,2026-11-08 起)

**为什么**:DSH 没有模型回退链 —— `@deepseek-ai/dsh-agent-default-model` 与 `@deepseek-ai/dsh-llm-pi-ai`
都只认「一个 provider + 一个模型 id」。cn 线路一挂(`model_unavailable` / `no_healthy_account` / 直接超时),
所有工单会在同一条错误上一起停摆。而 wb-pool 网关下同一份 key 本来就有三条线路。

**做法**:`scripts/superagent-failover/`(源码在仓库,运行副本在 `/usr/local/lib/superagent-failover/`)
是一个只听 `127.0.0.1:8788` 的小代理,挡在 DSH 与网关之间,把请求体里的 `model` 依次换成回退链上的
下一个,直到某次真的成功。除 `model`(与随之变化的 `content-length`)外字节原样转发,不需要密钥 ——
`Authorization` 由 DSH 自己带上。profile 里的 `baseURL` 因此指向它(见 `/root/.dsh/profiles/superagent/cordis.patch.yml`)。

| 事 | 命令 |
|---|---|
| 装 / 升级(幂等) | `wsl -e bash -c 'bash /root/src/chatapp/scripts/superagent-failover/install.sh'` |
| 状态 | `systemctl status superagent-failover --no-pager` |
| 日志 | `journalctl -u superagent-failover -n 50 --no-pager`(`served model=…` 每请求一行,`failover A -> B(code)` 只在切换时) |
| 看了算数的实时状态 | `curl -s http://127.0.0.1:8788/__failover/status`(每条线路的 served/failed/冷却剩余) |
| 自测(不联网) | `cd /root/src/chatapp && node --test scripts/superagent-failover/selftest.mjs`(12 条) |
| 回退到直连 | `systemctl disable --now superagent-failover`,再把 profile 的 `baseURL` 改回 `https://wb.shiliu153.me/v1`,重启 superagent |

**回退链**:`cn:deepseek-v4.1-flash` → `global:deepseek-v4.1-flash` → `global:deepseek-v4.1-flash-sg`。
一条线路失败后进冷却 30s,期间直接跳过;冷却一过下一次请求重新试它 —— **cn 恢复后会自动切回,不用人管**。

**什么时候换、什么时候不换**(判错方向比不换更糟,所以口径写死):

| 触发 | 结果 |
|---|---|
| 网关线路类错误码(`model_unavailable` / `no_healthy_account` 等)、5xx、402、连接失败/等头超时 | 换下一条 |
| SSE 已回 200 但**首帧**就是 `error` 事件(客户端还没收到任何字节) | 换下一条 |
| 400 参数错、401/403 鉴权 | **不换**,原样返回 —— 换了也是同样报错,只会把真 bug 藏进噪声 |
| 请求的模型不在链上(有人把模型换成了别的) | **不换**,原样单发 |
| 流已经开始往客户端写字节之后才失败 | **救不回来**(会串话),交给 DSH 自己的 `llm-retry`;下一次请求会因冷却落在更好的线路上 |

**验收证据(2026-11-08,真网关 + 真 DSH)**:
① `node --test selftest.mjs` 12/12 绿(假上游,覆盖换/不换、SSE 首帧、冷却、恢复);
② `dsh headless --patch <走代理> "用三个字回答"` → 代理日志 `served model=cn:deepseek-v4.1-flash status=200 attempts=1`;
③ 演练:把主线路换成 `cn:no-such-model`,同一条命令仍答出结果,代理日志
`failover cn:no-such-model -> global:deepseek-v4.1-flash(http_503)` → `served model=global:deepseek-v4.1-flash attempts=2`。

**已知偏差 / 排障**:
- **代理是单点**:它挂了 = superagent 的模型调用全挂(表现为 `failover_upstream_unreachable` 或直接 ECONNREFUSED)。
  所以它是自己的 systemd 服务(`Restart=always`),不挂在 DSH 的进程树里;`start-superagent.sh` 在
  `start|restart|status` 时会顺手探一下它,探不到就在 stderr 上喊一声。
- 面板与 session 日志里显示的模型仍是**请求方写的那条**(通常是 cn),不代表实际服务的线路 ——
  真实线路只看代理日志或 `/__failover/status`。
- 代理强制 `accept-encoding: identity`:它要读响应体才能识破「200 其实是错误」,让上游压缩就换掉了这个判断能力。
- 代理**不是**安全边界也不记账:不鉴权、不校验、不做额度控制,额度仍由网关按账号算。
