# 文档与脚本治理:从「补丁式维护」到「机械化一致性」

> **状态**:进行中(方案待逐节确认) · **立项**:2026-11-14 · **工作面**:分 6 节,每节单独一个会话
>
> 本文只回答**做什么、为什么、怎么算做完**;每节的实现细节在对应会话里展开。
> 数字类结论都是 2026-11-14 在本仓库实测的,复核命令写在 §2 每条证据后。

---

## 1. 问题陈述

主人对现状的描述是三句话,分别对应三类可测量的症状:

1. **文件结构混乱** —— 该放脚本的地方放了文档,该归档的东西留在工作面,空目录残留。
2. **各文档口径不统一** —— 同一条事实在多处维护,已经分叉;索引里的数字是手写的,已经过期。
3. **补丁越来越多** —— 每加一道门禁要改三处(脚本 + CI + 注释),漏改就产生漂移;漂移靠下一个人肉发现。

这三件事的**共同根因**是同一个:**仓库里没有「唯一事实来源」这个机制,只有「大家记得同步」这个纪律。**

纪律会失效,机制不会。本方案的目标就是把纪律换成机制。

---

## 2. 现状证据(可复核)

> **2026-11-14 复核(落地第 1 节前逐条复跑)**:本节方向**全部成立**,但 **9 条数字 / 口径需要修正**
> (如 CI 门禁是 15 条不是 16、`六轨` 是 19 次 / 12 个文件、脚本家是 7 处不是 3 处),
> 且 **§2.4「`docs/superpowers/archive/` 是空目录」一条不成立**(递归 105 份 md,`docs/` 下无空目录)。
> 修正值、复核命令与逐条结论见
> [docs/standards/sources-of-truth.md §3](../../standards/sources-of-truth.md)。**本节数字以该复核为准。**

### 2.1 规模与增长

| 指标 | 实测值 | 复核命令 |
|---|---|---|
| `docs/` 下 Markdown | **175 份**(105 归档 / 70 非归档) | `Get-ChildItem docs -Recurse -Filter *.md` |
| 提交总数 | 667 | `git rev-list --count HEAD` |
| 动过 `docs/` 的提交 | **325(49%)** | `git rev-list --count HEAD -- docs` |
| 动过 `CLAUDE.md` 的提交 | **108(16%)** | `git rev-list --count HEAD -- CLAUDE.md` |
| `CLAUDE.md` 行数 | 28 → **202** | `git show <首个提交>:CLAUDE.md` 对比当前 |
| `docs/ops/release.md` 行数 | 112 → **866** | 同上 |
| `.github/workflows/contract.yml` 行数 | 40 → **126** | 同上 |

**读法**:每 6 次提交就有 1 次在改 `CLAUDE.md`。这不是「文档写得好」,是**所有新规则都往同一个文件里追加**。

### 2.2 索引数字已经漂移(手写的计数必然会过期)

`README.md` §9「文档索引」与现状逐条对不上:

| README §9 说 | 实际 | 复核 |
|---|---|---|
| `docs/api/` **14 份分册 / 54 个操作** | **15 份分册 + README**;`docs/api/README.md` 自述 **63 个接口** | `Get-ChildItem docs/api -Filter *.md` |
| `docs/superpowers/` 工作面 **1 份**、归档 **85 份** | 工作面 **3 份**(本方案落地后 4 份)、归档 **105 份** | `docs/superpowers/README.md` §4 |
| `docs/security/` **三轮**审计 | **四轮**(round1–round4) | `Get-ChildItem docs/security` |
| 全仓「**六轨**」 | **10 个** workflow 文件 | `Get-ChildItem .github/workflows` |

「六轨」这个词在 9 份文档里出现 **19 次**,而 `.github/workflows/` 下有 10 个文件
(`app-ui` / `app` / `auto-merge` / `backend` / `contract` / `imserver` / `l4-intake` /
`main-health` / `web-e2e` / `web`)。**术语已经与事实脱钩。**

### 2.3 文档散落在索引之外

用相对链接解析后统计(非归档文档):

- **15 份**不被任何顶级索引(`README.md` / `CLAUDE.md` / `AGENTS.md` / 各子 `README.md`)链接:
  `docs/ops/` 10 份(含 `certificates.md`、`observability.md`、`push.md`、5 份基线报告)、
  `docs/security/` 4 份、`docs/superpowers/specs/2026-11-13-aws-*.md`。
- **`docs/learning/` 16 份**(后端教学)在根导航里**完全没有入口**。
- `docs/standards/README.md` 与 4 份安全报告**只被 `archive/` 里的历史文档引用** ——
  事实上已经脱离主线,但仍在「活跃目录」里。

### 2.4 文件放错了地方

> **本节证据的唯一 owner 是
> [sources-of-truth.md §3](../../standards/sources-of-truth.md) 的第 14 / 15 / 17 / 24 条**
> (复核命令、逐条结论都在那里,包括 spec 原文漏掉的 `check_ssl_expiry.sh` 与
> `nginx-security.conf`)。这里**不再抄一份** —— 同一事实两处手写正是本方案要消灭的漂移。
> 其中「`archive/` 是空目录」一条**复核不成立,已撤回**(递归 105 份 md)。

归位已在**第 2 节**完成(2026-11-14),`docs/` 下不再有脚本 / 补丁 / 配置样本:

| 归位前位置 | 内容 | 归位后 | 依据 |
|---|---|---|---|
| `patches/` 子目录 | 1 个 7KB 补丁(dsh-superagent 轮询重试) | [`scripts/patches/`](../../../scripts/patches/) | 上游未修,补丁仍在用;`.gitattributes` 的 `*.patch` LF 规则按扩展名,不用改 |
| `stress/` 子目录 | **7 个**压测/混沌脚本 | [`scripts/stress/`](../../../scripts/stress/) | 作为历史证据保留,新压测一律用 `perf/run.py` |
| 证书巡检脚本 | `check_ssl_expiry.sh` | [`scripts/ops/`](../../../scripts/ops/) | 运维脚本,与 `docs/ops/certificates.md` 同域 |
| nginx 基线 | `nginx-security.conf` | [`docs/ops/nginx-security.md`](../../ops/nginx-security.md) | **内容本来就是 Markdown**(标题 / 引用块 / 代码围栏),只是扩展名写错 |

现状由机械判定,不靠人记:`python scripts/docs_lint.py` 的 structure 规则会拦住
「又有非文档文件放回 `docs/`」。

### 2.5 同一条事实多处维护,已经分叉

**发版**:版本号在 `app/pubspec.yaml`、`app/lib/core/app_info.dart`、`web/package.json` 三处,
发版记录又在 `docs/ops/release.md` §5 的 Markdown 表格里 —— `scripts/sync_version.py`
**直接解析 Markdown 表格当数据库用**(`read_release_record`)。文档格式一改,门禁就坏。

**门禁**:`scripts/verify.sh` 自称「CI 的镜像」,但两边步骤集已经不一致:

| | 本地 `verify.sh contract` | CI `contract.yml` |
|---|---|---|
| 门禁条数 | **11** | **16** |
| CI 独有 | — | 贴纸两端一致、告警脚本自测、`ci-scope` 自测、`bash -n`、`shellcheck` |
| 本地独有 | 启动脚本选路自测(靠 CI 侧的代理自测间接带跑) | — |

「本地绿 ≈ CI 绿」这句话在当前状态下**不成立**。

**文档门禁不在 PR 上**:`scripts/check_docs_links.py` 只被 L4 定时任务和它自己的单测调用。
一份只改文档、写坏 10 条链接的 PR,**所有 workflow 都是绿的** —— 而 `AGENTS.md` §三
恰恰写着「只改文档 → 跑 `scripts/verify.sh contract`」。

### 2.6 脚本「补丁式增长」的三个具体形态

1. **双份登记**:新增一道门禁 = 改 `contract.yml` 一个 step + 改 `verify.sh` 一行 + 各写一段
   「为什么需要它」的注释。三处手改,漏一处就漂移(§2.5 已发生)。
2. **硬编码路径清单**:`scripts/ci-scope.sh` 每个栈一条正则;新增栈或新增相关目录要改脚本。
3. **常量各写一份**:`DEFAULT_REPO = "shiliu153/chatapp"` 在 **4 个**脚本里各定义一次;
   `app/pubspec.yaml` 路径在 **3 个**脚本里各拼一次;`docs/ops/release.md` 路径在 **2 个**脚本里各写一次。
   `verify.sh` 的 `check_artifact`(忽略行尾差异比对生成物)只有 shell 实现,Python 侧无法复用。

---

## 3. 目标(全部可机械判定)

### 3.1 文档结构

```
docs/
  README.md            ← 唯一目录入口,内容由 scripts/docs_index.py 生成
  standards/           ← 规范(唯一 owner):python.md / writing.md(新)
  api/                 ← 对外契约:15 分册 + openapi.yml(不动)
  ops/                 ← 常驻手册:runbook / imserver / release / superagent / observability / push / certificates
  reports/             ← 一次性测量报告(新):5 份基线 + stress-test + scale-report
  security/            ← 审计报告(一次性,只增不改)
  pitfalls/ learning/ reviews/ backlog/ milestones.md
  superpowers/{specs,plans,archive}
```

**规则**:`docs/` 下只允许 `.md` / `.yml` / `.json` / 图片;脚本、补丁、可执行文件一律进 `scripts/`。

### 3.2 脚本结构(分两档,见 §7 待拍板 D2)

**保守档**(只加公共层,不搬目录):

```
scripts/
  lib/        ← 公共层:repo / version / docs / artifacts
  gates.toml  ← 门禁注册表(唯一事实来源)
  run_gates.py← 执行器(本地与 CI 同一个入口)
```

**彻底档**(再按域分目录):`scripts/{lib,gates,release,superagent,stress,dev,tests}/`。

### 3.3 判定口径(每节验收都用这些)

| 判定 | 目标值 | 谁来判 |
|---|---|---|
| `docs/` 下的脚本/补丁/二进制 | **0 个** | `docs_lint` |
| 非归档文档被索引覆盖 | **100%** | `docs_lint` |
| 索引里的计数为手写 | **0 处**(全部生成) | `docs_index --check` |
| 术语「六轨」 | **0 处** | `docs_lint` 术语表 |
| 新增一道门禁的改动点 | **1 处**(`gates.toml`) | 人工复核 + `run_gates --list` |
| 本地与 CI 的门禁条数 | **相等** | `run_gates --list` 对比 CI 日志 |
| `contract.yml` 行数 | **≤ 50** | 行数 |
| `verify.sh` 行数 | **≤ 160** | 行数 |
| `CLAUDE.md` 行数 | **≤ 120** | 行数 |
| `README.md` 行数 | **≤ 250** | 行数 |
| `DEFAULT_REPO` 定义处数 | **1** | `grep` |

---

## 4. 分节方案

> 每节 = 一次独立会话 = 一个 PR。顺序有依赖:**第 1 节定的口径是后面所有节的判据。**

### 第 1 节|口径地图:定「谁说了算」

- **产出**:`docs/standards/sources-of-truth.md` —— 一张「事实 → 唯一 owner → 校验手段」表;
  同时给出**当前冲突清单的裁决**(§2.2 那 4 条 + 术语表)。
- **为什么先做**:不先定 owner,后面每一节都会退化成「两处都改一遍」。
- **验收**:表里每条事实只有 1 个 owner;每条都有校验手段(机械 / 定期人工);冲突清单 0 条未裁决。
- **需拍板**:D1(发版记录是否从 Markdown 表格迁成数据文件)。

### 第 2 节|文件归位:docs/ 只放文档

- **动作**:`docs/ops/` 下的补丁处理掉;7 个压测脚本进 `scripts/stress/`(或 `perf/`);
  5 份基线 + 2 份报告进 `docs/reports/`;清空目录;`docs/learning` 进索引。
- **同时落地护栏**:`scripts/docs_lint.py` 的**最小骨架**(结构规则 + 断链 + 索引覆盖),
  并接进 `contract` 轨。**先装护栏再搬家具** —— 搬的过程中每一步都能机械验证。
- **验收**:`docs_lint` 对当前仓库 0 违例;`check_docs_links.py` 0 断链;全仓 `grep` 无旧路径残留。

> **执行记录(2026-11-14,PR 见 `docs/milestones.md`)**
>
> - **护栏**:新增 `scripts/docs_lint.py`(三条规则:structure / broken-link / unindexed,
>   `--json` 可被 L4 复用;断链**直接复用** `check_docs_links.find_broken_links`,不重写解析)
>   + `scripts/test_docs_lint.py`(23 条用例,纯离线);**同时**接进 `contract.yml` 与
>   `verify.sh::stack_contract()` 两处。顺带把「断链检测」从「只跑自测」变成「PR 上真跑」——
>   此前写坏链接的纯文档 PR 全绿。
> - **拍板结果**:压测脚本 → `scripts/stress/`;补丁 → `scripts/patches/`(实测上游未修,
>   母体 `/root/dsh-superagent` 仍是未提交的本地改动,不能删);证书巡检 →
>   `scripts/ops/check_ssl_expiry.sh`;`nginx-security.conf` **改名为 `.md`**(它本来就是
>   Markdown,三处引用全是散文提及,没有一处把它当配置文件用)。
> - **归位**:7 份测量报告 → `docs/reports/`(新建子 README);`docs/` 下非 md 文件从
>   11 个(违规 10)降到 **1 个**(`docs/api/openapi.yml`,合规)。
> - **索引覆盖拉满**:新增 `docs/ops/README.md`、`docs/reports/README.md`、
>   `docs/security/README.md`、`docs/learning/README.md` 四个子索引,`README.md` §9 全部挂上,
>   并把 `specs/2026-11-13-aws-*.md` 补登记进 `docs/superpowers/README.md` §2 ——
>   非归档 md 被索引覆盖 **100%**(注:该登记原定第 3 节,但索引覆盖规则一开就必须先做,
>   否则 lint 自身红)。
> - **范围外(遗留)**:19 处「六轨」措辞未清(C4)。它属**术语 lint 规则**,与第 6 节的
>   `writing.md` 一起做才有防回归手段;本节只做结构与索引,故 `sources-of-truth.md` §7
>   的归属已从「第 2 节」改判到「第 6 节」。

### 第 3 节|索引与入口:一个入口 + 生成式索引

- **动作**:新建 `docs/README.md`(生成);`README.md` §9、`CLAUDE.md` 导航表、各子 `README.md`
  收敛为**指针**;所有计数由 `scripts/docs_index.py` 扫描生成,CI 比对生成物与 HEAD(复用
  `check_artifact` 的「忽略行尾」语义);`docs/superpowers/README.md` §4 的 105 行归档表也改为生成。
- **验收**:`docs_index.py --check` 绿;三份根文档行数达标(§3.3);索引数字 0 处手写。

> **执行记录(2026-11-14)**
>
> - **拍板(5 项)**:① **行数责任** —— 本节只做「索引生成 + 指针化」,`README.md` ≤250 /
>   `CLAUDE.md` ≤120 留给**第 6 节**(真正的瘦身是把快速开始/部署段收成指针、把规则搬进
>   `docs/standards/`,提前砍只能删规则,与 §6「瘦身只搬位置不删规则」冲突);② **归档表** ——
>   拆生成物 `docs/superpowers/archive/INDEX.md`,README §4 只留「交付脉络」散文;
>   ③ **接口一览表** —— **不整表生成**(`openapi.yml` 没有 `summary` 字段,「说明」列是人写的要点,
>   整表生成只能取分册小节标题,实测 70 行里 43 行会丢括号补充说明),改为「计数生成 +
>   表 ≡ 契约操作集合」的**集合相等门禁**;④ **比对语义** —— `--check` 只比磁盘字节,
>   新生成物在 `.gitattributes` 固定 `eol=lf`,不把 shell 的 `tr -d '\r'` 抄进 Python
>   (抽 `scripts/lib/artifacts.py` 仍归第 5 节);⑤ **子 README** —— 保留「什么时候读 /
>   结论一句话 / 状态注记」的精选表,但声明完整清单在生成物里(删掉会让这几份索引失去唯一价值)。
> - **生成器**:新增 `scripts/docs_index.py`(纯标准库)+ `scripts/test_docs_index.py`(33 条用例)。
>   三个产物:`docs/README.md`(唯一入口:非归档逐份 + 每目录份数 + 归档只报数)、
>   `docs/superpowers/archive/INDEX.md`(105 份逐份登记)、`docs/api/README.md` 的
>   `generated:api-summary` 标记区间(只覆盖区间,区间外手写内容一字不动、换行风格跟随原文件)。
> - **机械规则**:归档里每份 `.md` 在 INDEX.md **出现且仅出现一次**;每份非归档文档在
>   `docs/README.md` 出现;接口一览表 ≡ `openapi.yml` 的操作集合。三条都在 `--check` 里,坏即红。
> - **净减少的重复(§8 记账)**:归档表 62 行手写 → **0 行**(生成物替代);`README.md` §9 的
>   11 行表 → **1 行指针**;`CLAUDE.md` 导航表的 3 处手写计数 → **0**;
>   `docs/api/README.md` 的 2 处手写计数 → 生成。手写计数在 `README.md` / `CLAUDE.md` /
>   `docs/**/README.md` 里清零。
> - **顺手修掉的漂移**:① 归档表自称 105 份、实际只链接 98 份 —— **7 份 R–W 批次 plan 从未单独
>   登记**(被压成一句「7 份文档一并归档」的叙述),生成物自动补齐;② `CLAUDE.md` 导航表
>   「当前工作面 4 组」实际已是 5 组(第 2 节登记 aws spec 后这一行没跟着改);
>   ③ `README.md` 第 150 行「13 份分册,51 个操作」是**第 1 节漏修的第 6 处**手写计数(实际 15 / 70)。
> - **接轨**:`contract.yml` 与 `verify.sh::stack_contract()` 各加 2 条(自测 + `--check`);
>   `verify.sh` 另加 2 条 `check_artifact`(生成物必须已提交到 HEAD —— 只在本地改了没提交,CI 不会红)。
> - **范围外(遗留)**:三份根文档行数未达标(第 6 节);`docs/learning/README.md` 的
>   「P00–P14 十五册」仍是手写计数(不在本节验收口径内,属第 6 节的数字 lint);`archive/` 105 份的
>   「交付结论」不再逐条维护,owner 是 `docs/milestones.md`。

### 第 4 节|门禁注册表:一份清单驱动本地与 CI

- **动作**:`scripts/gates.toml` 描述每道门禁(id / scope / kind / 命令 / 一句话理由);
  `scripts/run_gates.py` 执行(支持 `--list` / `--scope` / `--dry-run` / `--json`);
  `contract.yml` 收成一个 step;`verify.sh` 的 contract 分支收成一行。
  **CI 改为调用同一个执行器** —— 从「手抄镜像」变成「同源」,这一节直接消灭 §2.5 那类漂移。
- **验收**:`run_gates.py --list` 与 `gates.toml` 一致;`verify.sh` / `contract.yml` 里
  不再出现门禁命令字面量(由 lint 校验);本地与 CI 条数相等。
- **需拍板**:D3(backend/web/app 三条重活轨是否也抽成 `scripts/stacks/*.sh` 供两边共用)。

> **执行记录(2026-11-14)**
>
> - **拍板(6 项)**:① **D3-B** —— 四条重活轨全部同源:新增 `scripts/stacks/{env,deps,bootstrap,backend,web,imserver,app}.sh`,
>   `verify.sh` 与 `backend.yml` / `web.yml` / `imserver.yml` / `app.yml` 调同一份(**不改 job name**,
>   required check 不变);② **行数** —— 本节同时负责 `contract.yml ≤50` 与 `verify.sh ≤160`,
>   前提是 D3-B + env 块外移;③ **`check_artifact` 不进注册表** —— 它不是命令型门禁而是
>   「生成物语义」,抽 `scripts/lib/artifacts.py` 仍归第 5 节(C9);本节把它留在
>   `scripts/stacks/*.sh`,注册表暂无 `kind = "artifact"`;④ **CI 一个 step** —— 执行器逐条
>   `::group::` 打印、失败打 `::error title=<id>::`,「哪道门禁红了」看 id 即可;
>   ⑤ **外部工具 fail-closed** —— `requires` 缺工具即判红并给安装命令,不 skip(跳过会让 C5
>   以新形态复发);⑥ **字面量 lint** 放新增的 `scripts/test_gates.py`(与既有 `scripts/test_*.py` 同风格)。
> - **注册表与执行器**:`scripts/gates.toml` = 33 道门禁(contract 21 / backend 3 / web 4 /
>   imserver 3 / app 2),字段 `id / scope / kind / command / reason / cwd / requires / env`;
>   `scripts/run_gates.py` 纯标准库(`tomllib`,3.11+ 自带),支持
>   `--list` / `--list --json` / `--dry-run` / `--scope` / `--skip` / `--json`,
>   退出码 **0 全绿 / 1 有门禁红 / 2 执行器自己出错**(执行器坏了不许冒充门禁红)。
>   `python` 前缀按 `$CHATAPP_PY` 替换(本地 venv / CI 的 python),**不写两套表**。
> - **差额归零(C5)**:本地 15 / CI 19 → 两边 **21 / 21**。差异账(注册表第一次跑出来的账):
>   **CI 独有 5**(贴纸 / 告警转发自测 / `ci-scope` 自测 / `bash -n` / shellcheck)、
>   **本地独有 1**(启动脚本选路自测)、**两边都没跑 1**(`test_verify.sh`)、
>   **写法不同 14**(解释器 / 绝对路径 / `-v` 与 `--verbose` 的差异)——
>   21 道门禁里**逐字相同的命令是 0 条**,所谓「镜像」其实是手抄的同义改写。
> - **净减少的重复(§8 记账)**:① 门禁命令从 2 份(CI 19 个 step + 本地 15 条 `run`)收敛到
>   1 份(33 道注册表);② env 块(23 行)与 `deps_up`/`deps_down` 从 `verify.sh` 移进
>   `scripts/stacks/`,本地与 CI 共用;③ 四条重活轨的 step 内容从 workflow 收进
>   `scripts/stacks/*.sh`。行数:**`contract.yml` 146 → 40**(≤50)、
>   **`verify.sh` 274 → 85**(≤160)。
> - **顺手修的坑**:① `scripts/test_verify.sh` 是「有 owner 没校验」的空头 owner ——
>   §2.3 把它写成机械校验,但 CI 19 个 step 里没有它、`verify.sh contract` 也不调它;
>   现在是注册表里的 `contract-verify-selftest`;② 本地 `verify.sh contract` 漏跑
>   `check_stickers` / 告警转发自测 / `ci-scope` 自测 / `bash -n` / shellcheck 5 条,
>   CI 漏跑启动脚本选路自测 1 条,现在两边一样;③ 本地 web 跑的是 `test:run`(覆盖率门槛
>   不生效),CI 跑 `test:coverage` —— 同源后本地也真跑 70/60/70/70;④ `gates.toml` 钉成
>   LF(`.gitattributes`),否则 Windows 检出的 CRLF 会让 `bash -c` 的多行门禁整条报错
>   (执行器另做一层换行归一化兜底);⑤ **`env.sh` 的 `TEST_REDIS_*` 写死 16379 在 CI 上连错端口** ——
>   CI 的 workflow 只注入 `REDIS_URL`(Redis 在 6379),从不注入 `TEST_REDIS_*`,而后端测试
>   在 TESTING 模式下读的是后者;本地 16379 恰好是对的,所以「本地绿」看不出来。
>   已改成**从 `REDIS_URL` 解析**(这条是 CI 第一次跑同源脚本时抓到的,正好证明同源有用)。
> - **范围外(遗留)**:① `check_artifact` 的 Python 实现(`scripts/lib/artifacts.py`)仍归
>   第 5 节(C9),注册表里没有 `kind = "artifact"`;② 三个重活轨的「装配」仍有 CI 专属部分
>   (services / 装依赖 / MySQL 授权 / Flutter SDK / Node 版本),它们不是判定而是环境,
>   留在 workflow 里;③ 本节不增删文档,`docs/README.md` 等生成物无需重生成。

### 第 5 节|脚本公共层与发版域收敛

- **动作**:`scripts/lib/{repo,version,docs,artifacts}.py`;4 份 `DEFAULT_REPO`、3 份 `PUBSPEC`
  收敛到 lib;发版四个脚本(`sync_version` / `release_prep` / `create_release` / `deploy_gate`)
  的职责边界写成一张表,共享 lib。
- **验收**:`grep -c DEFAULT_REPO` = 1;四个脚本全部 import lib;各自单测全绿;`contract` 轨绿。
- **需拍板**:D4(发版记录迁数据文件后,`sync_version` 是否只保留只读校验)。

### 第 6 节|docs-lint 收口与写作规范

- **动作**:`docs/standards/writing.md`(命名 / 头部元信息 / 状态 / 归档 / 「口径页」写法);
  补齐 lint 规则(元信息、数字、术语、归档表完整性);`CLAUDE.md` 瘦身到「导航 + 强制规则指针」,
  细节搬到 `docs/standards/`;`README.md` 的快速开始/部署段收成指针。
- **验收**:§3.3 全部判定达标;`CLAUDE.md` ≤ 120 行且每条规则都能点到 owner 文档。

---

## 5. 顺序与依赖

```
第 1 节(定 owner)
   └─→ 第 2 节(物理归位 + lint 骨架)──→ 第 3 节(索引生成)
                                          └─→ 第 4 节(门禁同源)──→ 第 5 节(公共层)
第 6 节(收口)依赖 1–3 的结论
```

第 4/5 节与 1–3 节**互不阻塞**,可以先做(纯脚本改动,风险低);但第 6 节必须最后做,
否则规范会写在一个还没定型的结构上。

---

## 6. 明确不做

- **不合并/删除历史文档**。归档只 `git mv`,内容不改写 —— 历史价值与审计价值都在。
- **不改 `docs/api/` 的分册结构**。它已经有双向门禁(`ApiDocsCoverageTests` + 字段级校验),
  是全仓最健康的一块,不动。
- **不为「好看」重排 `CLAUDE.md` 的业务规则**。瘦身只搬位置,不删规则。
- **不引入新工具链**(静态站点、mkdocs、docsify)。生成物仍是纯 Markdown。
- **不碰 `flutter/`**、不改 `deploy/` 下任何脚本(见 `AGENTS.md` §六)。

---

## 7. 待拍板选项

| 编号 | 问题 | 选项 |
|---|---|---|
| **D1** | 发版记录留在 `release.md` §5 的 Markdown 表格,还是迁成 `docs/releases.yml`(由 `release.md` 引用)? | A. 保持表格(改动小,继续「文档当数据库」) / **B. 迁数据文件**(推荐:门禁只解析结构化数据,文档只渲染) |
| **D2** | 脚本目录搬不搬? | A. **保守**:只加 `lib/` 与 `gates.toml`(推荐,PR 小、可逆) / B. 彻底:按域分目录(一次大 diff) |
| **D3** | backend/web/app 三条重活轨是否抽成 `scripts/stacks/*.sh` 供本地与 CI 共用? | A. 只做 contract 轨同源 / **B. 四条轨全部同源**(推荐:这才是「本地绿≈CI 绿」) |
| **D4** | 文档元信息(front-matter:状态 / owner / 最后复核)强制到哪一档? | A. 全量 / **B. 只强制非归档文档**(推荐) / C. 只对新文档 |
| **D5** | 「工程脚本 / CI / 部署脚本」的改动算哪条栈?`AGENTS.md` §二「一单一条栈」没有覆盖 `scripts/**`、`.github/**` | A. 新设 `flow` 域(推荐,验证入口 `verify.sh contract`) / B. 归到 `docs` 栈 / C. 维持现状(散落在各栈) |

---

## 8. 风险

| 风险 | 应对 |
|---|---|
| 搬文件引发链接风暴(175 份文档) | 第 2 节先落地断链门禁,再搬;每节独立 PR,`check_docs_links` 兜底 |
| 索引生成物与手写内容冲突 | 生成物入库 + CI 比对(与 `openapi.yml` 同模式),禁止手改 |
| 门禁注册表本身成为新的单点 | 注册表有自测(`run_gates --selftest`),且 `--list` 与 CI 日志可比对 |
| 治理动作本身制造「新的补丁」 | 每节必须**净减少**一处重复(登记点 / 常量 / 手写数字),验收里逐节记账 |
