---
状态: 常驻
复核: 每节治理落地后
---

# 写作规范(文档怎么写、怎么归档、怎么被机械判定)

> **立项**:2026-11-14(治理方案第 6 节)· **owner**:本文件
>
> 本文回答一个问题:**一份文档长什么样才算合规**。它是
> [`sources-of-truth.md`](sources-of-truth.md) §2.5「写作规范」那行的 owner;
> 每条规则都对应 `python scripts/docs_lint.py` 里的一条 lint 规则 ——
> 没有门禁的规范会在三轮迭代内退化成「历史遗留风格 + 新代码各写各的」
> (见本目录 [README](README.md) 原则三)。

---

## 1. 命名

| 对象 | 规则 | 谁判 |
|---|---|---|
| 设计 spec | `YYYY-MM-DD-<主题>-design.md`,放 `docs/superpowers/specs/` | 人工(立项时) |
| 实施 plan | 与 spec **同名**去掉 `-design`,放 `docs/superpowers/plans/` | 人工(立项时) |
| 一次性报告 | `<主题>-YYYY-MM-DD.md` 或 `YYYY-MM-DD-<主题>.md`,放 `docs/reports/` | 人工 |
| 常驻手册 | `<主题>.md`(**不带日期**),放 `docs/ops/`、`docs/pitfalls/` | 人工 |
| 归档 | `git mv` 进 `docs/superpowers/archive/{specs,plans}/`,**文件名不改** | `docs_index --check` |

- 文件名用**立项日期**,不是交付日期;spec 与 plan 成对时两者日期必须一致。
- 一个文件只属于一个状态(进行中 / 常驻 / 一次性 / 已归档),不混写。

---

## 2. 头部元信息(front-matter)

**作用域**:非归档 `docs/**/*.md`。
**豁免**:`docs/superpowers/**` —— 它的状态 owner 是
[该目录 README §2](../superpowers/README.md) 的工作面表,元信息再写一份就是同一事实两处。

```markdown
---
状态: 生效中
复核: 每次运维操作前
---
```

| 字段 | 必填 | 取值 | 判据 |
|---|---|---|---|
| `状态` | 是 | `生效中` / `常驻` / `一次性` / `已归档` | `docs_lint` 的 `metadata` 规则 |
| `复核` | 是 | 下面三种形态之一 | `docs_lint` 的 `metadata` 规则 |
| `owner` | 否 | 仓库内路径 —— **只在本文不是该事实的 owner 时写**(如渲染物写它的数据源) | 人工 |

`复核` 的三种合法形态(规则只认形状,不认内容):

1. **反引号命令** —— 有机械校验的文档写命令,如 `` `python scripts/docs_lint.py` ``;
2. **周期短语** —— 含 `每次` / `每周` / `每月` / `每季度` / `每年` / `每轮` / `每批` / `每节` /
   `发版前` / `交付后` / `立项时` / `归档时` / `变更时` / `审计后` / `巡检时`;
3. `无(一次性)` —— 一次性文档(测量报告 / 审计报告)明确写「不再复核」。

**禁止写日期**。`复核: 2026-11-14` 会变成一条没人验证过的假数据:这些文档里绝大多数
没有真被逐份复核过,写日期等于造数据。写周期或命令,下一个人才能判断「该不该现在复核」。

`状态` 的含义:

- **生效中** —— 还在用的手册 / 契约 / 规范,改代码时要跟着改;
- **常驻** —— 强制规则,永不归档(UI 设计规则、口径地图);
- **一次性** —— 只增不改的测量 / 审计报告,复核写 `无(一次性)`;
- **已归档** —— 历史文档;实际由 `docs/superpowers/archive/` 承担,元信息里基本不出现。

生成物(`docs/README.md`)的元信息由 `scripts/docs_index.py` 输出,**不手改**。

---

## 3. 状态与归档

- **进行中**:`docs/superpowers/{specs,plans}/` 里的文档。目录即工作面,不另写一份「进行中清单」。
- **常驻**:`specs/` 里标注「常驻 / 永不归档」的文档(如 UI 设计规则、superagent 流程)。
- **一次性**:`docs/reports/`、`docs/security/`、`docs/reviews/`。**只增不改** ——
  报告写的是「当时测到/审到什么」,改它等于改写证据。
- **已归档**:交付即归档。动作固定三步,顺序不能反:

  1. `git mv <文件> docs/superpowers/archive/{specs,plans}/`(**文件名不改、内容不改写**);
  2. 改 `docs/superpowers/README.md` §2 的工作面行(删掉这一行 / 改状态);
  3. `python scripts/docs_index.py --write` 重生成 `docs/README.md` 与 `archive/INDEX.md`,
     再在 [`docs/milestones.md`](../milestones.md) 留一行交付记录。

> 归档后**不要**回头补勾旧 checkbox、不要改历史文档里的数字与术语 ——
> 历史价值与审计价值都在原文里(spec §6 红线)。

---

## 4. 「口径页」怎么写

「口径页」= 回答「同一条事实谁说了算」的页面,样板是
[`sources-of-truth.md`](sources-of-truth.md)。写它的三条硬要求:

1. **一行一事实,一行一 owner。** owner 是**载体**(文件 / 目录 / 脚本),不是人 —— 人不进版本库。
2. **每个 owner 必须配校验手段。** 机械校验要给出**可复制的命令**;人工校验要写清**周期**
   (「每次发版前」「每轮压测后」),否则那条事实只是「某处写着」,不算有 owner。
3. **同一事实的第二处出现,只能是生成物或指针。** 需要两处显示时加生成器
   (`docs_index.py` / `openapi.yml` 模式),不加手写副本。

配套的三张表(缺一不可):

- **禁用表**:禁用写法 → 为什么 → 替代写法。禁用的东西必须**同时**进 lint 规则,
  否则禁用表只是散文(本文件 §6 就是它的门禁)。
- **裁决表**:冲突编号 / 证据 / 谁说了算 / 在哪一节修。裁决**不等于本次就修**,
  但必须写明归属,不允许「两处都改一遍」。
- **待修清单**:登记了但本次不改的欠账,必须带归属与理由,不留在对话里。

---

## 5. 数字与术语

### 5.1 数字

**手写计数必然过期** —— 本仓库已经过期过五次(接口数在 5 个地方各写一个版本)。
所以:

- **能用生成器的绝不用手写**:目录份数、归档份数、接口数、路径数、操作数一律引用
  `docs/README.md`(生成物)或 `openapi.yml`;
- **唯一保留的手写计数形态**是分册首句「本分册含 N 个接口」,因为它服务的是**分册自身**的
  可读性。它由 `docs_lint` 的 `number` 规则机械核对:必须等于「接口一览表」里指向该分册的行数;
- 其余 `N 份` / `N 条` / `N 个操作` 出现在历史叙事里(里程碑、发版记录、一次性报告)时
  **不强制改** —— 那是「当时的事实」,机械禁会逼人改写历史。

### 5.2 术语

禁用词表由 [`sources-of-truth.md`](sources-of-truth.md) §5 **唯一维护**,本文件不抄第二份(同一张表两处手写必然分叉)。
`term` 规则(`scripts/docs_lint.py` 的 `BANNED_TERMS`)按那张表拦截,当前是两类:

1. **「N 轨」形式的轨数词** —— 与 `.github/workflows/` 现在 10 个文件的事实脱钩,且数字会继续变;
   改写方式:「workflow(当前 10 个)」或直接点名轨(`contract` / `backend` …);
2. **「N 轮安全审计」** —— 已有第四轮;改写方式:「`docs/security/` 下 N 份」或「四轮」。

`term` 规则的作用域与豁免(**刻意收窄**,否则第一版就会红一片然后被人关掉):

| 范围 | 处置 |
|---|---|
| 根三份(`README.md` / `CLAUDE.md` / `AGENTS.md`) | **扫** |
| `docs/{ops,standards,api,pitfalls,backlog}/**` | **扫** |
| `docs/superpowers/{specs,archive}/**` | 豁免 —— 常驻 spec 与归档是历史,不改写 |
| `docs/{reports,security,learning,reviews}/**` | 豁免 —— 一次性报告 / 教学材料 |
| `docs/README.md` | 豁免 —— 生成物,内容来自各文档标题 |
| `docs/standards/sources-of-truth.md` | **整文件白名单** —— 它本身在**定义**这些禁用词 |

**行内豁免**:确实需要引用禁用词(例如说明它为什么被禁)时,在该行加

```markdown
这句话引用了一个禁用词以说明它被禁 <!-- lint:allow:term -->
```

标记**只豁免它所在的那一行**;整文件豁免只能通过上面的白名单,不提供「随手关掉整份文档」的口子。
禁用词本身在 `sources-of-truth.md` §5 有完整表,本文件不复述。

---

## 6. 机械校验

| 规则 | 判什么 | 命令 |
|---|---|---|
| `structure` | `docs/` 下只放 `.md` / `.yml` / `.json` / 图片 | `python scripts/docs_lint.py` |
| `broken-link` | 相对链接 0 条断 | 同上 |
| `unindexed` | 非归档文档被索引覆盖 100% | 同上 |
| `metadata` | 非归档文档的 front-matter 齐全且取值合法 | 同上 |
| `term` | 作用域内禁用词 0 处(白名单与行内豁免除外) | 同上 |
| `number` | 分册首句的接口数与接口一览表一致 | 同上 |
| 生成物 | `docs/README.md` / `archive/INDEX.md` / 接口一览计数与事实一致 | `python scripts/docs_index.py --check` |

这七条都在既有门禁里(`scripts/gates.toml` 的 `contract-docs-lint-run` /
`contract-docs-lint-selftest` / `contract-docs-index-check` / `contract-docs-index-selftest`),
本地与 CI 跑同一份清单:**不新增 gate**。改完文档先跑

```bash
python scripts/docs_lint.py
python scripts/docs_index.py --check
```

两条都绿再提交;新增 / 搬动 / 归档文档后必须跑 `python scripts/docs_index.py --write`
重生成索引(生成物要一起提交,CI 按字节比对)。

---

## 7. 相关文档

- 口径地图(谁说了算):[`sources-of-truth.md`](sources-of-truth.md)
- Python 注释规范:[`python.md`](python.md)
- spec / plan 的立项与归档流程:[`docs/superpowers/README.md`](../superpowers/README.md) §3
- 文档总索引(生成物):[`docs/README.md`](../README.md)
