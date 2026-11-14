---
状态: 常驻
复核: 每节治理落地后
---

# 唯一事实来源(口径地图)

> **立项**:2026-11-14(治理方案第 1 节)· **证据复核**:2026-11-14
> **依据**:[文档与脚本治理设计 §1](../superpowers/archive/specs/2026-11-14-docs-and-scripts-governance-design.md)
>
> 本文回答**一个问题**:同一条事实,谁说了算?每行只允许一个 owner,每个 owner 必须配一种校验手段。
> 本文**不改结构、不改脚本** —— 物理归位、索引生成、门禁同源分别在治理方案的第 2–6 节。
> 冲突裁决在 §4,术语禁用表在 §5,已拍板决策在 §6,本次不改的欠账在 §7。

---

## 0. 三条使用规则

1. **引用事实时引用 owner,不引用「某处也写了」。** 同一事实的第二处出现,只能是它的生成物或指向它的指针。
2. **改 owner 之外的副本 = 制造漂移。** 需要第二处显示同一事实时,加生成器,不加手写。
3. **新增一条事实 → 本表加一行。** 一个事实只能有一个 owner;拿不准 owner 时先裁决(§4),再动手。

---

## 1. 判定口径

| 术语 | 定义 |
|---|---|
| **owner** | 该事实的**权威载体**:一个文件、一个目录或一个脚本。不是「人」,因为人不进版本库 |
| **机械校验** | 有命令或测试会红。必须能给出确切命令 |
| **人工校验** | 没有门禁,靠定期复核。必须写清**周期**与**复核命令**,否则等于没有校验 |
| **生成物** | 由 owner 派生的文件(如 `openapi.yml` 由视图上的 `@extend_schema` 生成)。**禁止手改**,CI 比对 |

> 判据:一条事实如果**既没有机械校验、又没写人工周期**,它就不算有 owner —— 它只是「某处写着」。

---

## 2. 事实 → 唯一 owner → 校验手段

### 2.1 对外契约

| 事实 | 唯一 owner | 校验手段 | 状态 |
|---|---|---|---|
| 接口集合 / 路径 / 字段(机器可读) | [`docs/api/openapi.yml`](../api/openapi.yml)(**生成物**) | 机械:`cd chatapp && python manage.py spectacular --file ../docs/api/openapi.yml --validate` + CI 比对生成物;`config/tests.py::OpenApiSchemaTests` | 已落地 |
| 接口的人读文档(参数表 / 示例 / 错误码) | [`docs/api/*.md`](../api/README.md)(15 分册 + README) | 机械:`ApiDocsCoverageTests`(双向覆盖)+ `config/test_schema_contract.py`(字段级双向) | 已落地 |
| 接口与分册的**数量** | 无独立载体 —— 它是 `openapi.yml` 的**派生量**(禁止手写) | 机械:`python scripts/docs_index.py --check` —— 计数由契约生成,且 `docs/api/README.md` 的「接口一览」表与契约的操作集合必须**完全相等**(缺一行 / 多一行 / 重复一行即红) | **已落地**(2026-11-14 第 3 节);表的「说明」列仍是人写要点,理由见 §4 C1 |
| 错误响应信封 `{code, message, request_id}` 与业务码取值 | [`chatapp/config/error_codes.py`](../../chatapp/config/error_codes.py) | 机械:`python manage.py test config`(信封形状 + 业务码 = HTTP 前 3 位 + 2 位序号) | 已落地 |
| 业务码的**含义与处理建议** | 各接口分册的「错误码」小节(`docs/api/*.md`);码本身 = [`chatapp/config/error_codes.py`](../../chatapp/config/error_codes.py) | 机械:`python scripts/docs_index.py --check` —— 每个业务码**至少在一份分册里出现**(缺即红) | **已落地**(2026-11-14 第 6 节):`errors.md` 的 11 行手写总表**已删除** —— 它是副本且已漂移(缺 `40301` / `50302`),C11 收口 |
| WS 帧格式(三端唯一线上契约) | [`imserver/tests/fixtures/ws/*.json`](../../imserver/tests/fixtures/ws/README.md) | 机械:三端各一条 fixture 测试(`imserver` test_ws / App `protocol_fixture_test.dart` / Web `im-protocol-fixture.spec.ts`) | 已落地 |
| 客户端手写模型读取的字段 ⊆ 契约 | 契约本身(`openapi.yml`) | 机械:`scripts/check_app_models.py`;Web `npm run gen:api` + 生成物比对 | 已落地 |

### 2.2 发版

| 事实 | 唯一 owner | 校验手段 | 状态 |
|---|---|---|---|
| 版本号 | [`app/pubspec.yaml`](../../app/pubspec.yaml)(**唯一事实来源**) | 机械:`python scripts/sync_version.py --check`(`contract` 轨) | 已落地 |
| 发版记录(版本 / tag / Release 链接 / 上线 SHA / APK) | **`docs/releases.yml`**(D1-B 拍板) | 机械:`python scripts/releases.py --check`(渲染物 == YAML,逐字节)+ `python scripts/sync_version.py --check`(当前版本有记录 / `tag` 含 `v<版本>` / `Release` 非空) | **已落地**(2026-11-14 第 5 节):13 行历史逐字段迁移,`release.md` §5 改为生成区间;4 行散文用 `release: ""` + `note:` **原样还原**(不改写历史) |
| 四个发版脚本的职责边界(谁写哪些文件 / 联不联网 / 退出码) | [release.md §3.2](../ops/release.md) | 人工:**每次新增或改发版脚本时**对照;机械:`python -m unittest scripts.test_lib`(共享层只有一份实现) | 已落地(2026-11-14 第 5 节) |
| 发版动作清单(8 步) | [release.md §3](../ops/release.md) | 人工:**每次发版**按清单逐条执行 | 已落地 |
| Release 正文规范 | [release.md §4](../ops/release.md) | 人工:**每次发版**对照 | 已落地 |
| 「部署只认合并后的 SHA」 | [`scripts/deploy_gate.py`](../../scripts/deploy_gate.py) | 机械:`python scripts/deploy_gate.py`(部署前必跑) | 已落地 |
| 发版历史叙述(哪天上了什么) | [`docs/milestones.md`](../milestones.md) | 人工:**每次交付后**追加一行 | 已落地 |

### 2.3 门禁与流程

| 事实 | 唯一 owner | 校验手段 | 状态 |
|---|---|---|---|
| 门禁清单(有哪些、跑什么) | [`scripts/gates.toml`](../../scripts/gates.toml)(**唯一事实来源**);workflow 只留 job 名与装配 | 机械:`python scripts/run_gates.py --list`(与注册表逐条一致)+ `python -m unittest scripts.test_gates`(两边无命令字面量、条数相等) | **已落地**(2026-11-14 第 4 节):本地与 CI 调**同一份清单、同一个执行器**,19 / 15 的差额归零(现 21 / 21) |
| 新增一道门禁的改动点 | 同上 —— `gates.toml` 加一个 `[[gate]]` | 机械:`scripts/test_gates.py::SameSourceTests::test_no_gate_command_literal_in_wiring`(命令出现在 `contract.yml` / `verify.sh` / `stacks/*.sh` 里即红) | **已落地**(2026-11-14 第 4 节):**1 处** |
| 各栈装配(起容器 / 装依赖 / 迁移 / 生成物校验) | [`scripts/stacks/*.sh`](../../scripts/stacks) | 机械:`scripts/test_gates.py::SameSourceTests::test_heavy_workflows_call_shared_stack_scripts`(四条 workflow 与 `verify.sh` 调同一份) | **已落地**(2026-11-14 第 4 节,D3-B) |
| 本地验证入口(子命令与退出码) | [`scripts/verify.sh`](../../scripts/verify.sh) | 机械:`bash scripts/test_verify.sh` + `python scripts/run_gates.py --scope contract` | 已落地(第 4 节:contract 分支收成一行调用执行器,并把 `test_verify.sh` 自己也收进注册表) |
| 改动面判定(哪些栈要跑重活) | [`scripts/ci-scope.sh`](../../scripts/ci-scope.sh) | 机械:`bash scripts/test_ci_scope.sh` | 已落地 |
| worker 禁自合 / 禁发版 | [`scripts/gh-guard/`](../../scripts/gh-guard) | 机械:`sh scripts/gh-guard/selftest.sh` | 已落地 |
| L4 自动入队判据 | [`scripts/l4_intake.py`](../../scripts/l4_intake.py) | 机械:`python -m unittest scripts.test_l4_intake` | 已落地 |
| 栈归属(一单一条栈) | [`AGENTS.md` §二](../../AGENTS.md)(本次补 `flow` 域) | 人工:**每次开单时**对照 | 已落地 |
| 提交前必跑表 | [`AGENTS.md` §三](../../AGENTS.md) | 人工:**每次提交前**对照 | 已落地([CONTRIBUTING.md](../../CONTRIBUTING.md) 重复维护,见 §4 C6) |

### 2.4 文档与索引

| 事实 | 唯一 owner | 校验手段 | 状态 |
|---|---|---|---|
| 文档目录结构规则(`docs/` 只放文档)+ 命名 / 元信息 / 归档口径 | [`scripts/docs_lint.py`](../../scripts/docs_lint.py)(结构判定)+ [`docs/standards/writing.md`](writing.md)(写作规范) | 机械:`python scripts/docs_lint.py`(注册表 `contract-docs-lint-run`,本地与 CI 同一份):六条规则 structure / broken-link / unindexed / metadata / term / number | **已落地**(2026-11-14 第 2 节结构 + 第 6 节写作规范):`docs/` 下非 md 只剩 `openapi.yml` 1 个,合规 |
| 文档索引与**全部计数** | [`docs/README.md`](../README.md)(**生成物**,`scripts/docs_index.py`)+ 归档清单 [`docs/superpowers/archive/INDEX.md`](../superpowers/archive/INDEX.md)(**生成物**) | 机械:`python scripts/docs_index.py --check`(注册表 `contract-docs-index-check`,本地与 CI 同一份):生成物逐字节比对 + 归档完整性 + 入口完整性 + 接口表 ≡ 契约 | **已落地**(2026-11-14 第 3 节):`docs/README.md` 是唯一目录入口,索引数字 0 处手写;**索引覆盖**另由 `docs_lint` 机械判定(第 2 节) |
| 相对链接是否断 | [`scripts/check_docs_links.py`](../../scripts/check_docs_links.py) | 机械:`python scripts/check_docs_links.py`;PR 上由 `python scripts/docs_lint.py` **真跑**(`contract` 轨) | **已落地**(2026-11-14 第 2 节起进 PR 轨;此前只有 L4 定时轨与自测) |
| 工作面 / 归档清单 | 工作面 = `docs/superpowers/specs/` **目录即事实**(人写摘要见 [该目录 README §2](../superpowers/README.md));归档逐份清单 = [archive/INDEX.md](../superpowers/archive/INDEX.md)(**生成物**) | 机械:`python scripts/docs_index.py --check` —— 归档里每份 `.md` 在清单里**出现且仅出现一次** | **已落地**(2026-11-14 第 3 节):§4 的 105 行手写表已删除(只留交付脉络),当年漏登的 7 份 R–W plan 自动补齐 |
| 安全审计轮次与结论 | [`docs/security/`](../security)(目录即事实,**只增不改**) | 人工:**每轮审计结束后**核对 `Get-ChildItem docs/security` | 已落地(`CLAUDE.md` 导航表仍写「三轮」,见 §4 C3) |
| 待办总表 | [`docs/backlog/2026-11-03-todo.md`](../backlog/2026-11-03-todo.md) | 人工:**每次交付后**勾销 / 追加 | 已落地 |

### 2.5 规范与设计

| 事实 | 唯一 owner | 校验手段 | 状态 |
|---|---|---|---|
| Python 注释规范 | [`docs/standards/python.md`](python.md) | 机械:`cd chatapp && python config/comment_coverage.py` + `CommentCoverageTests` | 已落地 |
| 写作规范(命名 / 元信息 / 状态 / 归档 / 口径页写法 / 数字与术语) | [`docs/standards/writing.md`](writing.md) | 机械:`python scripts/docs_lint.py` 的 `metadata`(元信息)/ `term`(术语)/ `number`(分册计数)三条规则 | **已落地**(2026-11-14 第 6 节,D4-A) |
| UI 设计规则(「心跳」) | [2026-09-15-ui-design-language-design.md](../superpowers/specs/2026-09-15-ui-design-language-design.md)(常驻,**永不归档**) | 人工:**每次 App UI 改动前**必读 | 已落地 |
| UI 视觉 token 取值 | 同上(规则)+ 两端实现成对:`app/lib/core/theme/*.dart` ↔ `web/src/styles/tokens.css` | 机械:`web/tests/unit/tokens.spec.ts` 双向比对(漏改即红) | 已落地 |
| spec / plan 的写作与归档流程 | [docs/superpowers/README.md §3](../superpowers/README.md) | 人工:**每次立项 / 交付归档时**对照 | 已落地 |

> **token 为什么是「成对」而不是两个 owner**:两端运行在不同语言里,不存在可共享的单一文件;
> 「唯一」体现在**规则只有一个**(心跳 spec),双份实现由 `tokens.spec.ts` 双向钉死。
> 除这一处外,本表不允许任何「双份都对」的事实。

### 2.6 运行与运维

| 事实 | 唯一 owner | 校验手段 | 状态 |
|---|---|---|---|
| 服务器日常运维(备份 / 恢复 / 名单 / 巡检) | [docs/ops/runbook.md](../ops/runbook.md) | 人工:**每次运维操作前**按场景执行对应节 | 已落地 |
| IM 协议与运维口径 | [docs/ops/imserver.md](../ops/imserver.md)(帧格式归 fixtures,见 §2.1) | 人工:**每次改 IM / imserver 前**必读 | 已落地 |
| 容量与可靠性口径(数字与测法) | [docs/ops/capacity-and-reliability.md](../ops/capacity-and-reliability.md) | 人工:**每轮压测后**更新,引用前先看日期 | 已落地 |
| 观测栈配置 | [`deploy/observability/*`](../../deploy/observability)(**配置即事实**) | 机械:`python -m unittest discover -s deploy/observability -p 'test_*.py'`(`contract` 轨) | 已落地 |

### 2.7 工程脚本(`flow` 域,D5-A 已拍板)

| 事实 | 唯一 owner | 校验手段 | 状态 |
|---|---|---|---|
| 脚本放在哪(唯一家 + 3 处已裁决例外) | `scripts/`(域内子目录);**例外**:`tools/`(容器内 `/repo/tools` 路径被 `imserver/scripts/test_http.sh` 硬编码)、`perf/`(20+ 处历史报告的「当时命令」引用,搬了变死链)、`imserver/scripts/`(C++ 测试入口与镜像同源) | 机械:`python scripts/docs_lint.py` 的 structure 规则(`docs/` 下不得有脚本 / 补丁 / 配置)+ `git grep` 例外清单 | **已裁决**(2026-11-14 第 5 节,D2-A):`docs/` 侧已清零(第 2 节);三处例外的理由写在 [release.md §3.2](../ops/release.md) 与本节,不再悬着 |
| 仓库名(`owner/name`) | 第 5 节 `scripts/lib/repo.py` | 机械:`git grep -c "DEFAULT_REPO =" -- 'scripts/**/*.py'` 命中 = 1 | **已落地**(2026-11-14 第 5 节):4 → **1**,同性质三处(`DEFAULT_TOKEN_FILE` / `API` / token 解析逻辑)一并收进同一模块 |
| 「生成物 == HEAD」的比对语义(忽略行尾) | 第 5 节 `scripts/lib/artifacts.py` | 机械:`python -m unittest scripts.test_lib`(正反两面)+ 注册表两道 `kind = "artifact"` 门禁(`backend-openapi-artifact` / `web-schema-artifact`) | **已落地**(2026-11-14 第 5 节):shell 的 `check_artifact` 已删除,语义只有 Python 一份;退出码由 2 改为 **1**(判定失败,不是执行器故障) |

---

## 3. §2 证据复核(2026-11-14)

复核命令(在本仓库根目录执行,Windows PowerShell):

```powershell
# 规模
(Get-ChildItem docs -Recurse -Filter *.md -File).Count
git rev-list --count HEAD; git rev-list --count HEAD -- docs; git rev-list --count HEAD -- CLAUDE.md
git log --diff-filter=A --format='%H' -- CLAUDE.md          # 再用 git show <sha>:CLAUDE.md 数行
# 计数与漂移
(Get-ChildItem docs/api -Filter *.md -File).Count
python -c "import yaml;d=yaml.safe_load(open('docs/api/openapi.yml',encoding='utf-8'));print(len(d['paths']),sum(1 for v in d['paths'].values() for m in v if m in ('get','post','put','patch','delete')))"
(Get-ChildItem .github/workflows -File).Count
git -c core.quotepath=false grep -c 六轨
# 放错位置 / 脚本家
Get-ChildItem docs -Recurse -File | Where-Object { $_.Extension -ne '.md' }
(Get-ChildItem scripts -File).Count; (Get-ChildItem tools -File).Count
# 门禁条数:本地 stack_contract() 段 11 条;CI 17 个 step = 2 个装依赖 + 15 道门禁
Select-String -Path scripts/verify.sh -Pattern '^  run '                     # 33 条(全仓),contract 段 11 条
Select-String -Path .github/workflows/contract.yml -Pattern '^      - name:' # 17 条
# 常量重复
git -c core.quotepath=false grep -c 'DEFAULT_REPO =' -- 'scripts/*.py'       # 4
```

| # | spec §2 原文 | 复核实测 | 结论 |
|---|---|---|---|
| 1 | `docs/` 下 Markdown 175 份(105 归档 / 70 非归档) | 175 = 105 + 70(不含本方案自身的 spec;含它则 176) | ✅ 成立 |
| 2 | 提交 667;动过 `docs/` 325(49%);动过 `CLAUDE.md` 108(16%) | 667 / 325(49%)/ 108(16%) | ✅ 成立 |
| 3 | `CLAUDE.md` 28 → 202 行 | 首个提交 `2bf7f91` = 28 行;当前 202 行 | ✅ 成立 |
| 4 | `docs/ops/release.md` 112 → 866 行 | 新增提交 `4d46c72` = 112 行;当前 866 行 | ✅ 成立 |
| 5 | `contract.yml` 40 → 126 行 | 新增提交 `74f920f` = 40 行;当前 126 行 | ✅ 成立 |
| 6 | `docs/api/`「14 分册 / 54 操作」vs 实际 15 + README、63 接口 | 实际 **15 分册 + README**;`openapi.yml` = **58 paths / 70 operations**;`docs/api/README.md` 自述 **63** 且写「53 paths / 63 operations」;其「接口一览」表实有 **68 行**,缺 `POST/DELETE /users/me/voice` | ⚠️ 成立但**比原文更严重**:同一事实有 **5 个不同数字**(14/54、15、63、53/63、70),且派生表本身也漏了 2 个接口 |
| 7 | `docs/superpowers/` 工作面 1 份 / 归档 85 份 → 实际 3 份 / 105 份 | 归档 **105**(40 spec + 65 plan)✅;工作面 `specs/` 现 **5 份**(README §2 登记 4 组,`2026-11-13-aws-*` 未登记) | ⚠️ 成立,数量已变(3 → 5) |
| 8 | `docs/security/` 写「三轮」,实际四轮 | README §9 仍写「三轮」;目录实有 **4 份**(round1–4) | ✅ 成立 |
| 9 | 「六轨」在 9 份文档出现 19 次 | **19 次 / 12 个文件**;其中非归档 **9 个文件 10 次**(其余在 `archive/`) | ⚠️ **口径需修正**:19 是总数、9 是非归档文件数,不能并列 |
| 10 | `.github/workflows/` 下 10 个文件 | 10 个:`app-ui` / `app` / `auto-merge` / `backend` / `contract` / `imserver` / `l4-intake` / `main-health` / `web-e2e` / `web` | ✅ 成立 |
| 11 | 15 份非归档文档不被任何索引链接 | 实测**正好 15**:`docs/ops/` 10 + `docs/security/` 4 + `specs/2026-11-13-aws-*.md` | ✅ 成立 |
| 12 | `docs/learning/` 16 份在根导航没有入口 | 17 份 md(16 份内容 + 1 份目录 README);`README.md` / `CLAUDE.md` / `AGENTS.md` 确实无入口 | ✅ 成立(16 指内容页) |
| 13 | `docs/standards/README.md` 与 4 份安全报告只被 `archive/` 引用 | `standards/README.md` ✅;安全报告是 **3 份**只被 archive 引用,round1 另在 `docs/ops/imserver.md` 以**行内代码**被提到(不是链接) | ⚠️ **需修正**:3 份,且 round1 有非链接引用 |
| 14 | `docs/ops/patches/` 1 个 7KB 补丁 | 1 个,7316 字节 | ✅ 成立 |
| 15 | `docs/ops/stress/*.sh`、`*.py` 7 个脚本 | 7 个(5 个 `.sh` + 2 个 `.py`) | ✅ 成立 |
| 16 | `docs/superpowers/archive/` 是**空目录**(只有两个子目录) | **不成立**:`archive/` 递归 105 份 md;`docs/` 下**不存在任何空目录** | ❌ **不成立,应从 §2.4 删除** |
| 17 | 脚本有三个家:`scripts/` 29 个、`tools/` 3 个、`deploy/observability/*.py`、`imserver/scripts/` | 不是三个家而是 **7 处**:`scripts/` 27 个顶层文件(含子目录共 52)、`tools/` 3、`perf/` 2 个 py、`deploy/observability/` 2 个 py、`imserver/scripts/` 9、`docs/ops/stress/` 7、`docs/ops/check_ssl_expiry.sh` 1 | ⚠️ **需修正**:数量(27 非 29)与「家」的数量(7 非 3) |
| 18 | 本地 `verify.sh contract` 11 条门禁 vs CI `contract.yml` **16** 条 | 本地 **11** ✅;CI 实测 **15**(CI 独有 5:贴纸 / 告警自测 / ci-scope / `bash -n` / shellcheck;本地独有 1:启动脚本选路自测) | ⚠️ **需修正**:CI 是 15,不是 16 |
| 19 | `check_docs_links.py` 只被 L4 定时任务与它自己的单测调用 | ✅ `contract.yml:87` 与 `verify.sh:187` 只跑**自测**;真实扫描只在 `l4_intake.py`(L4 定时轨) | ✅ 成立(PR 上写坏链接不会红) |
| 20 | `DEFAULT_REPO` 在 4 个脚本里各定义一次 | 4 个:`apply_ruleset` / `create_release` / `deploy_gate` / `set_automerge_token` | ✅ 成立 |
| 21 | `app/pubspec.yaml` 路径在 3 个脚本里各拼一次 | 3 个:`create_release` / `release_prep` / `sync_version` 各有 `PUBSPEC` 常量 | ✅ 成立 |
| 22 | `docs/ops/release.md` 路径在 2 个脚本里各写一次 | 只有 `sync_version.py::RELEASE_DOC` 把它当**路径**用;`release_prep.py` 仅在文案里提到 | ⚠️ **需修正**:代码常量 1 处 |
| 23 | `check_artifact`(忽略行尾比对)只有 shell 实现 | 仅 `verify.sh` 定义与调用,Python 侧无等价实现 | ✅ 成立 |
| 24 | (§3.3 目标)`docs/` 下的脚本 / 补丁 / 二进制 = 0 个 | 当前非 md 文件 11 个,其中**违规 10 个**:1 patch + 7 压测脚本 + `check_ssl_expiry.sh` + `nginx-security.conf`(只有 `openapi.yml` 合规) | ⚠️ 比原文多 2 个:`check_ssl_expiry.sh`、`nginx-security.conf` |

**复核结论**:§2 的**方向全部成立**(根因判断、六类症状、可复现),但 **9 条数字或口径需要修正**,
其中 §2.4 的「空目录」一条**完全不成立**。以上修正值已回填本文 §2 与 §4,治理方案 §2 的原文按本文为准。

---

## 4. 当前冲突清单与裁决(0 条未裁决)

> 裁决 = 「谁说了算 + 在哪一节修」。裁决**不等于本次就修** —— 本次只修 C1 / C2 / C3 里标注「本次」的部分。

| # | 冲突 | 证据 | 裁决(谁说了算) | 修复归属 |
|---|---|---|---|---|
| **C1** | 接口 / 分册数量五处不一致 | README §9「14 分册 / 54 操作」、README 徽章「51 operations」、README 英文摘要「13 volumes, 51 operations」、`docs/api/README.md`「63 个接口」「53 paths / 63 operations」;实际 15 分册 / 58 paths / 70 operations;其「接口一览」表只有 68 行(缺 `users/me/voice` 两个) | **`openapi.yml` 说了算**。所有计数都是它的派生量,**禁止手写** | **第 1 节**修了 5 处手写数字 + 补齐派生表缺失的 2 行;**第 3 节已落地**:计数改为生成,表的操作集合与 `openapi.yml` **集合相等**由 `docs_index --check` 判定。表本身**仍手写** —— `openapi.yml` 没有 `summary` 字段,「说明」列是人写的要点,整表生成会丢 43 行的括号补充说明(拍板 3a′) |
| **C2** | `docs/superpowers/` 工作面与归档计数过期 | README §9「工作面 1 份 / 归档 85 份」;实际 5 份 spec(README §2 只登记 4 组)+ 105 归档;`2026-11-13-aws-*.md` 不在任何索引 | **目录说了算**(`specs/` 即工作面)。计数由 `docs_index` 生成 | **第 1 节**修 README §9 手写数字;aws spec 登记**提前到第 2 节**(索引覆盖规则一开就必须先登记,否则 `docs_lint` 自己红);**第 3 节已落地**:§4 的 105 行手写表删除,归档清单改由 `scripts/docs_index.py` 生成 —— 当年漏登的 **7 份** R–W plan 由生成物自动补齐,漏登从此即红 |
| **C3** | 安全审计轮次:三 vs 四 | 复核时 README §9 与 `CLAUDE.md` 导航表都写「三轮」;`docs/security/` 实有 4 份 | **`docs/security/` 目录说了算** = 四轮 | **已收口**(2026-11-14):第 1/2 节修 README §9 并新增 `docs/security/README.md` 索引;第 3 节把 `CLAUDE.md` 导航表改成「轮次以目录为准」,不再写数字;第 6 节把「三轮安全审计」列入禁用词(作用域内 0 处;归档与一次性报告按 §6 红线不改) |
| **C4** | 术语「六轨」与事实脱钩 | 19 次 / 12 个文件(非归档 9 个文件 10 次);workflows 实有 10 个 | **废止该词**。改说「workflow(当前 10 个)」或直接点名轨;由 `docs_lint` 术语规则拦截 | **已收口**(2026-11-14 第 6 节):`term` 规则(作用域 = 活文档,白名单 = 本文件,行内豁免 `<!-- lint:allow:term -->`);活文档 4 处已清(`AGENTS.md` / backlog ×2 / `release.md`);归档 9 处、常驻 spec 3 处、一次性审计报告 1 处按 §6 红线**不改写历史** |
| **C5** | `verify.sh` 自称「CI 的镜像」但两边门禁集不同 | 复核时本地 **11** 条 / CI **15** 条;CI 独有 5 条,本地独有 1 条。第 2 节两边各加 2 条、第 3 节各加 2 条后为 **15 / 19**(差额仍是 4)。第 4 节实测差异账:CI 独有 5、本地独有 1、两边都没跑 1(`test_verify.sh`)、**写法不同 14**(逐字相同的命令 **0** 条) | **`scripts/gates.toml` 说了算**(2026-11-14 第 4 节起);workflow 与 `verify.sh` 只调执行器 | **已落地**(第 4 节):两边跑同一份清单 + 同一个执行器,**21 / 21**,差额 4 → **0**;「命令不再出现在两边接线文件里」由 `scripts/test_gates.py` 机械判定 |
| **C6** | 「改什么 → 跑什么」表维护两份 | `AGENTS.md` §三 与 `CONTRIBUTING.md` 各一张,内容近乎重复 | **`AGENTS.md` §三 说了算**;`CONTRIBUTING.md` 收成指针 | **已收口**(2026-11-14 第 6 节):`CONTRIBUTING.md` 的「提交前必须通过」表与「硬性约束」10 条都收成指针,owner 只有 `AGENTS.md` §三/§四 |
| **C7** | 脚本有 7 处家 + 常量重复 | `scripts/`(52 含子目录)/ `tools/` 3 / `perf/` 2 / `deploy/observability/` 2 / `imserver/scripts/` 9 / `docs/ops/stress/` 7 / `docs/ops/check_ssl_expiry.sh`;`DEFAULT_REPO` 4 处 | **`scripts/` 是唯一家**(域内子目录);`DEFAULT_REPO` 等常量收敛到 `scripts/lib/` | **已收口**(2026-11-14 第 2 + 5 节):7 处 → `docs/` 侧清零(第 2 节)→ 剩余 `tools/` `perf/` `imserver/scripts/` **三处按 D2-A 裁决为例外**(理由见 §2.7,搬了会断容器路径与历史报告的「当时命令」);常量 **4 → 1**(`DEFAULT_REPO` / `DEFAULT_TOKEN_FILE` / `API` / token 解析逻辑一并收进 `scripts/lib/repo.py`) |
| **C8** | 发版记录 = 用 Markdown 表格当数据库 | `sync_version.py::read_release_record` 解析 `release.md` §5 表头「版本 / tag」;改一次表格格式就可能误红 | **D1-B 拍板**:`docs/releases.yml` 说了算,`release.md` §5 改为渲染 | **已落地**(2026-11-14 第 5 节):13 行历史逐字段迁进 `docs/releases.yml`;`scripts/releases.py --check` 比对渲染区间(逐字节,区间外一字不动);`sync_version --check` 只读结构化数据,不再猜表头 |
| **C9** | 生成物比对语义只有 shell 一份 | `check_artifact` 只在 `verify.sh`;Python 脚本无法复用 | 抽成 `scripts/lib/artifacts.py` | **已落地**(2026-11-14 第 5 节):语义收进 `scripts/lib/artifacts.py`(可独立执行);注册表加 `kind = "artifact"` 两道;`scripts/stacks/{backend,web}.sh` 的调用与 `env.sh` 的实现**已删除**;退出码 2 → **1**(判定失败) |
| **C10** | `docs/` 下 10 个非文档文件 | 1 patch + 7 压测脚本 + `check_ssl_expiry.sh` + `nginx-security.conf`(spec §2.4 漏了后两个) | **`docs/` 只放 `.md` / `.yml` / `.json` / 图片**;脚本进 `scripts/` | **已落地**(2026-11-14 第 2 节):非 md 从 11 个降到 **1 个**(`docs/api/openapi.yml`,合规);`nginx-security.conf` 经核实**本身就是 Markdown**,改名为 `docs/ops/nginx-security.md`。机械判定:`python scripts/docs_lint.py` |
| **C11** | `errors.md` 自称「业务码总表」但缺 2 个码 | `error_codes.py` 有 13 个码,`errors.md` 总表只列 11;`40301` / `50302` 只在 `auth.md` / `im.md` 的分册表里 | **`error_codes.py` 说了算**;`errors.md` 是渲染物 —— 第 6 节拍板 **C 案:删掉总表** | **已收口**(2026-11-14 第 6 节):11 行手写总表**已删除**,改「专属业务码在哪查」+ 分册指针;新增机械判定「每个业务码至少在 `docs/api/` 的一份分册里出现」(`scripts/docs_index.py --check`),反向验证过(删掉一处分册引用即红) |

---

## 5. 术语与写法禁用表

| 禁用写法 | 为什么 | 替代写法 |
|---|---|---|
| 「六轨」「CI 四轨」 | 与 10 个 workflow 的事实脱钩,且数字会继续变 | 「workflow(当前 10 个)」或点名具体轨(`contract` / `backend` …) |
| 「N 份分册 / M 个操作」手写 | 手写计数必然过期(C1 已有 5 个版本) | 引用 `openapi.yml`,或等第 3 节生成的索引 |
| 「工作面 N 份 / 归档 M 份」手写 | 目录本身即事实(C2) | 由 `docs_index` 生成后引用 |
| 「三轮安全审计」 | 已有第四轮(C3) | 「`docs/security/` 下 N 份」或「四轮」 |
| 无条件断言「本地绿 ≈ CI 绿」 | 第 4 节之前两边门禁集不同(C5) | 现在可写:两边调**同一份** `scripts/gates.toml` 与**同一个**执行器(本地 `verify.sh contract` / CI `run_gates.py --scope contract`),由 `scripts/test_gates.py` 判 |
| 「两处都要改」 | 唯一事实来源原则的反面 | 一处 owner + 一处生成物(或指针) |

---

## 6. 已拍板决策

| 编号 | 决策 | 拍板日期 | 落地位置 |
|---|---|---|---|
| **D1** | 发版记录迁成 `docs/releases.yml`(B 案),`release.md` §5 只渲染 | 2026-11-14 | **已落地**(第 5 节):`docs/releases.yml` 为 owner,`scripts/releases.py --check` 守渲染物,`sync_version.py` 只读结构化数据 |
| **D2** | 脚本目录**不搬**(保守档 A):只新增 `scripts/lib/`;`tools/` `perf/` `imserver/scripts/` 登记为**已裁决例外**(容器内 `/repo` 路径 / 历史报告「当时命令」可复跑 / C++ 测试入口与镜像同源) | 2026-11-14 | 本文 §2.7 + [治理方案第 5 节](../superpowers/archive/specs/2026-11-14-docs-and-scripts-governance-design.md) |
| **D3** | backend / web / imserver / app 四条重活轨也同源(B 案):各栈的装配抽进 `scripts/stacks/*.sh`,`verify.sh` 与四条 workflow 调同一份;门禁命令一律进 `scripts/gates.toml` | 2026-11-14 | 本文 §2.3 + [治理方案第 4 节](../superpowers/archive/specs/2026-11-14-docs-and-scripts-governance-design.md)(不改 job name,required check 不变) |
| **D4** | ① `sync_version` **保留 `--write`**,读 / 写原语都进 `scripts/lib/version.py`(「写」只有一份实现;发版记录改为只读校验)。② **文档元信息 = A 档**:只强制非归档文档,字段 `状态` + `复核`(`owner` 可选,只在本文不是 owner 时写),`docs/superpowers/` 豁免 —— 它的状态 owner 是该目录 README §2 | 2026-11-14 | ① 本文 §2.2 / §2.7;② [`writing.md`](writing.md) §2 + `docs_lint` 的 `metadata` 规则 |
| **D5** | 新设 `flow` 域:`scripts/**`、`.github/**`、`deploy/**` 的改动自成一条栈,验证入口 `scripts/verify.sh contract`。**栈归属 ≠ 改的权限**:`deploy/**` 仍受 `AGENTS.md` §六 禁止 | 2026-11-14 | 本文 §2.3 + [`AGENTS.md` §二](../../AGENTS.md)(本次已补一行) |

> 第 5 节已拍板 **D2**(不搬目录,三处例外登记在 §2.7)与 **D4 的前半**(`sync_version` 保留 `--write`,
> 读写进 lib);**D4 的后半(文档元信息档位)已由第 6 节拍板为 A 档**,本表不再有「待第 6 节」的条目。

---

## 7. 待修清单(登记,本次不改)

> **2026-11-14 第 6 节收尾**:勾掉 3 项(六轨措辞、`errors.md` 总表、C6 重复必跑表),
> 并把 §2.5 的写作规范从「待建」改为「已落地 + 三条 lint 规则」。
>
> **2026-11-14 第 5 节收尾**:勾掉「三处脚本家的归属」一项 —— D2-A 裁决为**例外**
> (理由在 §2.7),不搬目录;并登记一条新欠账(`create_release` 仍无单测)。
>
> **2026-11-14 第 4 节收尾**:勾掉「本地 15 条 vs CI 19 条门禁」一项 —— C5 归零(现 21 / 21),
> 门禁清单改由 `scripts/gates.toml` 单点维护。
>
> **2026-11-14 第 3 节收尾**:再勾掉 2 项(接口一览表、`CLAUDE.md` 的「三轮」),
> 并把「本地 vs CI 门禁条数」更新为 15 / 19(两边各加 `docs_index` 两条,差额仍是 4)。
>
> **2026-11-14 第 2 节收尾**:已勾掉 2 项(非文档文件归位、aws spec 登记),
> 并把「六轨」措辞改判到第 6 节(C4 的裁决理由见 §4)。

| 项 | 归属节 | 状态 |
|---|---|---|
| ~~`docs/api/README.md` 的「接口一览」表仍是**手写派生索引**~~ | 第 3 节 | **已完成**(2026-11-14):计数改为生成,表的操作集合与 `openapi.yml` **集合相等**由 `docs_index --check` 判定;「说明」列按 C1 保留人写 |
| ~~`CLAUDE.md` 文档导航表「三轮报告」→ 四轮(C3 的另一处)~~ | 第 6 节(原) | **已完成**(2026-11-14 第 3 节顺手):该行改为指向 [`docs/security/README.md`](../security/README.md) 并声明「轮次以目录为准」,不再写任何轮次数字 |
| ~~19 处「六轨」措辞(12 个文件,其中 9 个非归档;归档 3 处按 §6 红线不改)~~ | 第 6 节(**原第 2 节,2026-11-14 改判**) | **已完成**(2026-11-14):活文档 4 处清零,`docs_lint` 的 `term` 规则防回归(作用域 + 白名单 + 行内豁免) |
| ~~`errors.md` 业务码总表与 `error_codes.py` 不同步(C11)~~ | 第 6 节 | **已完成**(2026-11-14):总表删除(改分册指针),新增「每个业务码至少在一份分册出现」门禁 |
| ~~本地 15 条 vs CI 19 条门禁(C5)~~ | 第 4 节 | **已完成**(2026-11-14):`scripts/gates.toml` + `scripts/run_gates.py` 单点维护,两边 **21 / 21**,差额 0 |
| ~~`AGENTS.md` §三 与 `CONTRIBUTING.md` 重复的必跑表(C6)~~ | 第 6 节 | **已完成**(2026-11-14):`CONTRIBUTING.md` 收成指针,owner 只有 `AGENTS.md` §三/§四 |
| ~~`tools/` `perf/` `imserver/scripts/` 三处脚本家的归属(C7 剩余)~~ | 第 5 节 | **已完成**(2026-11-14):D2-A 拍板**不搬目录**,三处登记为已裁决例外(容器内 `/repo` 路径、历史报告「当时命令」可复跑、C++ 测试入口与镜像同源),理由见 §2.7 与 release.md §3.2 |
| `scripts/create_release.py` **仍无单测**(四个发版脚本里唯一有外部副作用:建 Release / 删附件 / 传 APK) | 未定(第 5 节拍板为「验收里明确排除并写理由」) | 待修(已登记,不阻塞):可测面几乎全是 `urllib` 胶水,真风险在副作用顺序(先查 tag / 先删后传),要 mock 大半个 REST 语义才测得动 |
| ~~10 个非文档文件归位(C10)~~ | 第 2 节 | **已完成**(2026-11-14) |
| ~~`specs/2026-11-13-aws-distributed-deployment-design.md` 未进 `docs/superpowers/README.md` §2~~ | 第 2 节(原第 3 节) | **已完成**(2026-11-14,索引覆盖规则需要) |

---

## 8. 维护规则

1. **新增事实 = 本表加一行**,并给出 owner 与校验命令;给不出校验命令的,必须写清人工周期。
2. **一个事实只能一个 owner**。需要第二处显示时,加生成器(`docs_index` / `openapi.yml` 模式),不加手写。
3. **冲突先裁决再改**:裁决写进 §4 并注明修复归属节;禁止「两处都改一遍」。
4. **本表的复核节奏**:每节治理落地后复核一次;数字类结论必须附可复跑的命令(见 §3)。
5. 第 6 节的 [`writing.md`](writing.md) 已于 2026-11-14 生效:本表的元信息(`状态` / `复核`)、状态词与归档口径**按该规范维护**;
   新增文档时先读它的 §2,再动笔。
