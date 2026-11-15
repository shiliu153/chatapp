# 文档关键数字的机械化(生成 + 判定)设计

> **立项**:2026-11-16 · **状态**:已实现并合并(`scripts/facts.py` + 13 个事实 + 2 道门禁;
> **上游口径**:[`docs/standards/sources-of-truth.md`](../../standards/sources-of-truth.md)(谁说了算)、
> [`docs/standards/writing.md`](../../standards/writing.md) §5(数字与术语怎么写)

---

## 1. 要解决的问题

治理第 3 节(2026-11-14)已经证明一件事:**手写计数必然过期**。它当时把「文档份数 / 归档份数 /
接口数 / 操作数」四类收进了生成器 `scripts/docs_index.py`,但**正文里的内联数字**没被覆盖。
留下三个具体缺口,全部**实测存在**:

| # | 缺口 | 证据 |
|---|---|---|
| 1 | `docs_lint` 的 `term` 规则让人改说「workflow(当前 10 个)」,但**没有任何东西守这个 10** | `docs/standards/writing.md` §5.2 的替代写法原文;`docs/architecture.md:91` 就写着一处 |
| 2 | 门禁条数是手写的 | `sources-of-truth.md` §2.3「现 `contract` 组 **25 / 25**」、§4 C5、§7 共 4 处 |
| 3 | **同一份活文档里两个数字互相矛盾** | `docs/ops/capacity-and-reliability.md:20`「**17 条告警**」vs 同文件 `:131`「Prometheus + Grafana + **10 条告警**」;`deploy/observability/alerts.yml` 实际 **17 条** |

第 3 条是这项工作的真实价值:**不是防未来的错,现在就有错**,而且没有任何门禁会发现它。

---

## 2. 数字分四类,只做第一类

活文档(根 `README.md` / `CLAUDE.md` / `AGENTS.md` + `docs/{ops,standards,api,pitfalls,backlog}/**`)
里有 650+ 处「N 个 / N 条 / N 份」。绝大多数**不该**进机械机制:

| 类型 | 例子 | 能否机械保真 | 本期处置 |
|---|---|---|---|
| **A 统计型** | workflow 10 个、门禁 41 道、接口 70 操作 / 58 paths、文档 80 + 106 份、告警 17 条、业务码 13 个 | ✅ 纯本地数文件 / 解析契约,**秒级** | **生成 + 判定**(本方案主体) |
| **B 规格型** | 限流 120 次/小时、上限 200MB、TTL 60s、`ids` ≤ 50 条 | ⚠️ 能从 `settings.py` / 常量取,但文档要讲「为什么是这个值」 | **不做**(登记为刻意不判) |
| **C 测量型** | 476 rps、p99 6.4s、1000 连接 0 失败 | ❌ 要跑压测 | **冻结**,只增不改 |
| **D 叙事型** | `milestones.md` 的「693 个后端测试」、发版记录里的数字 | ❌ 要跑全量测试,`contract` 轨等不起 | **冻结**(不改写历史) |

判据:**一个数字能不能进机制,只看「它是不是仓库里数得出来的」**,不看它重不重要。
`docs/milestones.md`、`docs/reports/`、`docs/security/`、`docs/reviews/`、`docs/learning/`、
`docs/superpowers/**`(含归档)一律**不在作用域内** —— 那是「当时的事实」,改它等于改写证据。

---

## 3. 机制设计

三层,一个脚本 `scripts/facts.py`:

### 3.1 唯一计算源:`FACTS` 注册表

放**在脚本里**(不是又一个 TOML):每个事实 = `id` + 人读说明 + 计算函数 + 断言正则。
计算函数只许**读文件 / 复用既有脚本的函数**,**禁止**跑测试、起容器、联网 ——
`contract` 轨必须秒级,这条是硬约束(它把 D 类挡在门外)。

| id | 值(2026-11-16) | 计算来源(全部复用,不新写解析) |
|---|---|---|
| `workflows` | 10 | 数 `.github/workflows/*.yml` / `*.yaml` |
| `gates_total` | 41 | `scripts.run_gates.load_registry()` 的条数 |
| `gates_contract` | 27 | 同上,`scope == "contract"` 的条数(渲染成 `27 / 27`) |
| `api_operations` | 70 | `docs_index.parse_openapi_operations()` |
| `api_paths` | 58 | 同上,去重路径数 |
| `docs_non_archive` | 81 | `docs_index.summarize()` |
| `docs_archive` | 106 | 同上 |
| `docs_total` | 189 | `docs/` 下全部 `.md`(含两份生成物;80 + 106 + 2 的近似值不要手算,这里就是扫描) |
| `alert_rules` | 17 | 数 `deploy/observability/alerts.yml` 的 `- alert:` |
| `cpp_comment_blocks` | 637 | 数 `imserver/{src,tests}/**/*.{h,cpp}` 里内容等于分隔线(`//`+115 个 `-`)的行数 ÷ 2(纯标准库,**不用 tree-sitter**;见 §3.1.1) |
| `dashboard_panels` | 12 | `deploy/observability/grafana/dashboards/*.json` 的 `panels` 数组长度之和 |
| `alert_targets` | 6 | 数 `deploy/observability/prometheus.yml` 的 `- job_name:` |
| `error_codes` | 13 | `docs_index.read_error_codes()` 去重 |

> **第二批(同日)加了三个**:`cpp_comment_blocks` / `dashboard_panels` / `alert_targets` ——
> 它们的引用都在活文档里出现 2 次以上,且都能从仓库里的配置 / 源码数出来。
>
> **第二批刻意没收的两个**:
> - 「容器 6 个」:`deploy/observability/docker-compose.yml` 有 **8** 个 service(loki / promtail
>   挂在 `--profile logs` 后面),文档里的 6 不是「配置里的 service 数」而是「默认起几个」——
>   机器数不出来,硬收只会逼门禁说谎;
> - 「5 个字段」:它是**规范常量**(每块必须有 5 个字段),属 B 类,归 `cpp.md` 与门禁本身。

### 3.1.1 C++ 注释块为什么不用 tree-sitter 数

块的判据是「上下各一条分隔线」,所以「内容恰好等于分隔线的行数 ÷ 2」就是块数,不需要 AST。
这样 `facts.py` 在只装标准库的机器上也跑得动(Windows 宿主没有 tree-sitter,而 `--write` 是
人在本地要跑的动作)。正确性由两处夹住:① 分隔线总数是奇数 → 判不出来,直接报错;
② `scripts/test_facts.py::CppBlockCrossCheckTests` 在有 tree-sitter 的环境(CI 与 bootstrap 后)
把这条计算与 `check_cpp_comments` 的 AST 口径**逐数比对** —— 两套算法只准给出同一个答案。
断言正则也必须与 `dashboard_panels` 不相交(裸的 `N 块` 会命中看板的「12 块」),
防撞由 `test_facts.py::PatternCollisionTests` 钉住。

> **为什么不写成 `facts.toml`**:计算是代码,断言正则是代码;拆成「数据文件 + 代码」会让
> 「哪个 id 有实现」变成两处对账(`sources-of-truth.md` §2.7 收 `DEFAULT_REPO` 就是同一个教训)。
> 注册表只有一处 = 唯一事实来源。

### 3.2 哨兵:数字怎么由脚本写进正文

```markdown
共 <!-- num:gates_total -->41<!-- /num --> 道门禁
```

- HTML 注释在 GitHub / 本地预览里**都不渲染**,读者看到的就是「共 41 道门禁」;
- 值可以是字符串(`gates_contract` 的值是 `27 / 27`);
- `--write` 负责两件事:① 刷新已有哨兵里的值;② 把命中断言正则的**裸数字**就地包上哨兵。
  它**只替换捕获组那一段**,句子其余部分一字不动。

### 3.3 判定:三条规则(这才是「机械化」的部分)

| 规则 | 判什么 | 为什么 |
|---|---|---|
| **R1 值** | 每个哨兵里的值必须 == 计算值 | 防止手改哨兵、或改了事实忘了重生成 |
| **R2 强制哨兵** | 作用域内命中某事实断言正则的**裸数字**一律判红 —— **即使数值正确** | 不留「反正我写对了」的灰色地带:今天对,加一个 workflow 后就不对,而没有人会记得回来改 |
| **R3 位置** | 哨兵不得出现在 ATX 标题(`^#{1,6} `)与代码围栏内 | 标题里的哨兵会污染 anchor(目录链接全断);围栏内的 HTML 注释会当字面量显示出来 |

**R2 的作用域必须收紧**(否则门禁第一版就红一片然后被人关掉):只有**注册表里声明过的形态**
受约束。B/C/D 类数字不匹配任何正则,自然不受影响。这是本方案唯一需要人反复确认的边界。

豁免:`<!-- lint:allow:number -->` 加在行尾,只豁免**那一行**(与 `term` 规则的
`<!-- lint:allow:term -->` 同一套机制)。

### 3.4 作用域与豁免

| 范围 | 处置 |
|---|---|
| 根 `README.md` / `CLAUDE.md` / `AGENTS.md` | **扫** |
| `docs/` 根的散装文档(`architecture.md` 就在这里) | **扫** |
| `docs/{ops,standards,api,pitfalls}/**` | **扫** |
| `docs/standards/sources-of-truth.md` | **整文件白名单** —— 它是「冲突 / 裁决 / 收尾记录」,里面**故意**保留历史数字(如「当时 21 / 21,现 27 / 27」),逐句判会把治理档案逼成假的。与 `term` 规则的白名单同款 |
| `docs/backlog/**` | **豁免** —— 它虽叫「当前工作面」,内容绝大多数是「某日交付时的数字」,与里程碑同类。**这是实测改判的**:首轮扫描在 backlog 里命中 7 处历史数字(`47 个操作` / `39 paths`),把它们改成今天的事实等于改写证据 |
| `docs/milestones.md` | **豁免** —— 交付时间线,只增不改 |
| `docs/README.md`、`docs/api/README.md` | **豁免** —— 生成物,由 `docs_index.py` 负责,两个生成器不抢同一份文件 |
| `docs/superpowers/**`、`docs/{reports,security,reviews,learning}/**` | **豁免** —— 历史 / 一次性报告 / 教学材料 |

### 3.5 刻意不判

- **B 类规格数字**(阈值 / 上限 / TTL):从代码取会让手册退化成配置镜像,可读性归零;
- **测试用例数**:要跑全量测试才有真数,`contract` 轨做不到。按 §3.6 改成**禁用写法**;
- **C++ 注释块数(637)**:需要 tree-sitter 才能数准,而 `docs/standards/cpp.md` 开头已经给了
  三条可复跑的 `git grep` 命令 —— 人工复核优于半可信自动值;
- **中文数字**(「四轮」「三条硬规矩」):归 `term` 规则与人的语感,不归数字门禁。

### 3.6 不可保真的数字 = 禁用写法

与生成机制**互补的一半**:数不出来的数字**不许写具体值**。`docs_lint` 的 `number` 规则因此
扩成两半(仍是「六条规则」,不新增规则名):

| 半边 | 判什么 |
|---|---|
| `number/A`(旧) | `docs/api/*.md` 首句「本分册含 N 个接口」必须等于「接口一览」表里指向该分册的行数 |
| `number/B`(新) | 活文档里不得出现「N 个测试 / 测试 N 例 / N 条自动化测试」等**不可保真计数**;改写方式是给命令或不写数字 |

口径与替代写法登记在 `sources-of-truth.md` §5 禁用表(术语表的 owner 在那里,本文件不复述)。
作用域沿用 `term` 规则(活文档),**额外豁免 `docs/ops/release.md`**:它的「上线实况」写的是
当次发版的证据(「App 侧由 506 条自动化测试覆盖」),数字天然带日期;禁它等于逼每次发版都挂
一行豁免标记,而那种摩擦会让人把整条规则关掉 —— 与 `term` 规则「作用域刻意收窄」同一个理由。

---

## 4. 门禁与开发流程

`scripts/gates.toml` 加两道(`contract` 组,本地与 CI 同一份):

| id | 命令 | 判什么 |
|---|---|---|
| `contract-facts-run` | `python scripts/facts.py --check` | **当前仓库**的每个数字都等于事实 |
| `contract-facts-selftest` | `python -m unittest scripts.test_facts -v` | **判定器本身**判得对:漏报(数字错了不红)与误报(对的红了 / 该豁免的没豁免)两个方向都要钉住 |

新增一条事实的改动点 = **1 处**(`FACTS` 加一项)+ 跑一次 `--write`。

流程上的强约束(写进 `AGENTS.md` §三):**凡是会改变 A 类数字的改动**
(加 workflow、加门禁、加接口、增删文档、改告警规则、加业务码),提交前必须跑

```bash
python scripts/facts.py --write
python scripts/facts.py --check     # 确认干净
```

忘了跑的后果只是 CI 红一次(这正是设计目的),不会静默漂移。

---

## 5. 迁移方案(已执行)

1. **第一批(10 个事实)一次性 `--write`**,把引用全部包上哨兵。**实测只有 7 处 / 4 份文件**
   (远少于立项时估的 60–80 处:绝大多数「N 份 / N 条」是规格型与叙事型,不进正则);
2. **逐处复核「这次改动是否暴露了过期数字」** —— 改值的处所就是真 bug。第一批实得 **1 处**:
   `docs/ops/capacity-and-reliability.md:131` 的「10 条告警」→ **17**(同文件第 20 行早就写着 17);
3. **第二批(3 个事实)再迁 12 处 / 3 份文件**:`docs/standards/cpp.md` 8 处、
   `docs/ops/observability.md` 2 处、`docs/ops/capacity-and-reliability.md` 2 处。
   这一批没有发现新的过期数字(637 / 12 / 6 当时都是对的),价值在**防回归**:
   `cpp.md` 那 8 处 637 此前全靠「改 imserver 时记得手改」;
4. 仍有 6 个事实(接口数 / 文档份数 / 业务码 / 门禁条数)在作用域内**零引用** ——
   它们的价值不是「迁现有的」,而是「谁哪天写下 `41 道门禁` 就当场红」。

**不做**:把 `docs/api/*.md` 首句的「本分册含 N 个接口」也收进哨兵 —— 那是 15 个不同的值
(一册一个数),收进哨兵等于造 15 个事实,而现有 `number/A` 规则已经把它判准了(判据是表行数)。
**哨兵为准、老规则留作兜底**:同一个值两处表达时,哨兵管正文、老规则管分册首句。

---

## 6. 验收口径

```bash
python scripts/facts.py --check                 # 0 = 全部一致
python scripts/facts.py --report                # 人读:每个事实算出多少、命中哪些位置
python -m unittest scripts.test_facts -v        # 判定器双向自测全绿
python scripts/docs_lint.py                     # 六条规则 0 违例(含 number/B)
python -m unittest scripts.test_docs_lint -v    # docs_lint 自测全绿
python scripts/docs_index.py --check            # 索引与事实一致
python -m unittest scripts.test_gates -v        # 注册表自洽(条数 / 顺序 / 无字面量)
```

CI 侧由 `contract` 轨跑同一份 `scripts/gates.toml`(`scripts/verify.sh contract`)。

---

## 7. 风险与反面清单

| 风险 | 对策 |
|---|---|
| **误报会杀死门禁**(本仓库有前科:`term` 规则第一版差点红一片) | 断言正则**必须**带上下文词组(`\d+ 条告警`,绝不写 `\d+ 条`);`test_facts.py` 必须覆盖「误报也要红」 |
| 断言正则漏掉真实写法 → 静默漂移 | 宁可漏判不可误报;`--report` 是人补充正则的入口 |
| 有人在代码围栏里写哨兵 | R3 直接判红 |
| 有人把哨兵塞进标题 | R3 直接判红(改用文字表述,如「workflow 目前的条数见下表」) |
| 计算变慢(将来有人加「跑测试」类事实) | §3.1 的硬约束 + 代码审查;`--check` 实测 < 1s |
| 生成物与手写同文件互相覆盖 | 作用域明确排除两份生成物(§3.4) |
| Windows / Linux 行为不一致 | 复用 `docs_index._read_text` / `_write_text`(不折 CRLF)与 `as_posix()` 排序;`--check` 只比字符串 |

**明确不做**:不为 C/B/D 类造「半可信快照文件」—— 快照会腐烂,而腐烂的快照比手写数字更危险
(它看起来是机器生成的)。

---

## 8. 后续(不在本期)

- 第二批事实:待第一批跑两周后按 `--report` 的命中量决定;
- 若「不可保真数字」在实践中反复出现,再考虑把 `number/B` 拆成独立规则名(届时需要同步改
  `writing.md` §6 的表格与「六条规则」口径)。
