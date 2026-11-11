# 批次 W-L3 实施计划:golden 截图进 CI

- **状态**:已交付(PR [#242](https://github.com/shiliu153/chatapp/pull/242),squash 合并 `74c1cef`)
- **Spec 链接**:[批次 R–W 设计](../specs/2026-11-09-batch-r-w-design.md) §4.6 第 2 条
- **交接来源**:[批次 U/W 交接](2026-11-10-batch-u-w-handoff.md) §2「W-L3」
- **Goal**:把「App 长什么样」也变成 CI 的判据 —— 登录页与首页(发现)各一张 golden,
  像素变了就红;基准图**只在 CI 里生成、只在 CI 里比对**。
- **Architecture**:`integration_test` 的 golden 走 `VmServiceProxyGoldenFileComparator`
  (设备侧截帧 → VM service 事件 → 宿主侧 `flutter_tester` 里用 `LocalFileComparator` 落盘/比对),
  **不需要 `flutter drive`、不需要额外 workflow**。`flutter test -d emulator-5554` 本身就会
  注入这个 comparator,`--update-goldens` 同样走宿主侧写文件。
- **Global Constraints**:一条栈(`app` + 它的 CI 轨);不动版本号 / 不打 tag / 不建 Release / 不部署;
  App UI 走「心跳」token(本批不改 UI,只加**观测**);`scripts/verify.sh app` 推之前必须绿。
- **验收命令**:`scripts/verify.sh app`(analyze + 单测)+ `.github/workflows/app-ui.yml` 的 app-ui 轨绿

---

## 0. 现状核实(动手前查过)

| 事实 | 证据 |
|---|---|
| 模拟器轨已在 CI 跑 4 个 integration 文件 | `.github/workflows/app-ui.yml` 的 `script:` 单行(api-level 34 / x86_64 / swiftshader) |
| 仓库里**没有任何** golden 设施 | `grep -r matchesGoldenFile app/` 零命中;`app/test/` 下无 `goldens/` |
| 设备侧 golden **原生支持**,无需 `flutter drive` | `flutter/packages/flutter_tools/lib/src/test/flutter_platform.dart:250` 注入 `VmServiceProxyGoldenFileComparator.useIfRunningOnDevice()`;`:526` 起在宿主侧监听 `integration_test.VmServiceProxyGoldenFileComparator` 事件并调 `TestGoldenComparator`;`:814` 把 `--update-goldens` 传进 bootstrap |
| 基准图路径按**测试文件**解析,落在宿主仓库里 | `flutter_platform.dart:527` `goldensBaseUri = Uri.file(testPath)`;`test_golden_comparator.dart:328` 用 `LocalFileComparator(Uri.parse(testUri))` |
| 截图尺寸 = **逻辑像素**(与设备 DPR 无关) | `flutter/lib/src/rendering/layer.dart:1546` `toImage(bounds, pixelRatio: 1.0)`;`flutter_test/lib/src/_matchers_io.dart:26` `captureImage` 只传 `paintBounds` |
| 截整屏必须有个 RepaintBoundary 祖先 | `_matchers_io.dart:29` 向上找 `isRepaintBoundary`;`RenderView.isRepaintBoundary == true`(`rendering/view.dart:315`) |
| 容差要自己装:默认是**逐像素精确**比对 | `test_golden_comparator.dart` 的 bootstrap 只装 `LocalFileComparator`;`flutter_test/lib/src/goldens.dart:133` 起给了「自定义容差 comparator」的官方写法 |
| `flutter_test_config.dart` 会**同时**作用于宿主比对进程与设备侧 | `test_config.dart:17` 从测试文件目录向上找到 `app/`(pubspec.yaml 停下);`test_golden_comparator.dart:331` 与 `flutter_platform.dart:253` 都包 `test_config.testExecutable` |
| 本机模拟器与 CI 模拟器**不是**同一套 | 本机 `emulator-5554` = 1080x2400 / 420dpi / **API 37** / `sdk_gphone16k_x86_64`;CI = **API 34** / AOSP default。所以本机 `--update-goldens` 的产物**不能**当基准 |
| 隐藏 Tab 里有无限动画 | `app/test/features/shell/home_shell_test.dart:25` 注释:`IndexedStack` 隐藏页的 `HeartRipple` 一直跑,`pumpAndSettle` 永不收敛 → golden 只能 `pump` 固定帧数 |
| 卡片照片是网络图 | `profile_card.dart:68` `Image.network(...)`(带 `errorBuilder`);照片不铺(`photos: []`)时走 `:60` 的纯色占位,**零网络** |

**结论**:W-L3 不需要新依赖、不需要 `flutter drive`、不需要第二个 workflow。真正要设计的是
**「怎么让两张图在 API 34 的 AOSP 镜像上稳定」**,以及**「基准图怎么只在 CI 生成」**。

---

## 1. 设计决策(三条,都是被上一轮坑逼出来的)

### 1.1 单独一个 `golden_test.dart`,不并进 `smoke_test.dart`

交接文档写的是「把 `smoke_test.dart` 扩到 golden」,这里**偏离**为独立文件,理由:

- `smoke_test` 断言的是**行为**(后端不可达也落到登录页),失败时结论明确;
- golden 断言的是**像素**,失败有两种完全不同的原因(外观变了 / 跑图的环境变了);
- 混在一个用例里,视觉回归会把行为信号淹掉,而且 golden 一旦要临时跳过(换模拟器镜像)就得连行为断言一起跳。

两者仍在**同一条轨**(同一次 `flutter test` 调用、同一个 `script:` 行),交接文档的意图(「app-ui 轨覆盖登录页 + 一个主页面」)不变。

### 1.2 固定视口:**390×844 逻辑像素 + 零 padding + textScaler=1**

`captureImage` 用的是 `pixelRatio = 1.0`,所以 PNG 尺寸 = **逻辑**尺寸,与设备 DPR / 分辨率无关 ——
但逻辑屏幕尺寸**会**随 AVD 变(本机 411×914,CI 的 AVD 又是另一套)。所以:

- 被测页面放进 `Align(topLeft) → RepaintBoundary(key) → SizedBox(390×844) → MediaQuery(固定) → 页面`;
- 捕获用 `find.byKey(key)`,截的就是那块 390×844,**换 AVD 不变尺寸**;
- `MediaQuery` 钉死 `size / devicePixelRatio / padding / viewInsets / textScaler`(系统字体缩放、状态栏高度都是设备相关的);
- 顺手把 `debugShowCheckedModeBanner` 关掉 —— golden 要的是**设计基线**,不是 debug 角标。

`Align` 不能省:`Overlay` 给 `home` 的是**紧约束**,直接放 `SizedBox` 会被撑满整屏。

### 1.3 容差:宿主侧包一层 comparator,**只放宽 0.1% 像素 / 单通道 8**

精确比对在「同一镜像 + 同一 Flutter 版本」下大概率稳,但一个字形的抗锯齿差异就够红一次。
按 `goldens.dart` 官方写法在 `app/integration_test/flutter_test_config.dart` 里包一层:

- 先走原 comparator 的**精确**比对,相等直接过(绝大多数情况);
- 不等且基准文件存在 → 解码两张 PNG,逐像素比;差异像素占比 ≤ 0.1% 且每通道差 ≤ 8 视为通过;
- 基准不存在 → **原样抛出**(「还没生成基准」和「像素变了」必须能区分);
- **只在宿主侧生效**(`Platform.isAndroid/isIOS` 直接 `return testMain()`),否则会把设备侧的
  `VmServiceProxyGoldenFileComparator` 顶掉,截帧根本发不出去。

---

## Task 1 —— `app/integration_test/golden_test.dart`(两张图)

1. `goldens/login.png`:登录页(`LoginPage`,真实 widget + 真实主题 + 假网络),等到
   `login.submit` 出现再截。
2. `goldens/discovery.png`:首页(`HomeShell`,默认 Tab = 发现),`GET /users/me` 给完整资料、
   `GET /discovery/candidates` 给 2 个候选(**`photos: []`** → 纯色占位,零网络图)、
   `GET /discovery/daily` / `GET /posts` 给空页;`pumpFrames` 固定 12 帧(不能用 `pumpAndSettle`,
   见 §0 最后一行),截前断言 `小红,25` 已在(防止截到骨架屏)。

**不铺的路由**(`/discovery/quota`、`/matches`、`/discovery/likes/count` …)故意留 404:
它们在页面上是「静默不渲染」或「隐藏 Tab」,铺了反而把 golden 绑死在假数据上。

## Task 2 —— `app/integration_test/flutter_test_config.dart`(容差,见 §1.3)

## Task 3 —— `.github/workflows/app-ui.yml`

1. 正常路径:把 `integration_test/golden_test.dart` 加进那条 `script:` 单行(注释里已写明「新增文件必须加进来」)。
2. 新增 `workflow_dispatch` 输入 `update_goldens`(boolean,默认 false):
   - `true` → 单独跑 `golden_test.dart --update-goldens`,把 `app/integration_test/goldens/` 当 artifact 上传;
   - `false`/push/PR → 跑原来那 5 个文件(golden 在这里**比对**)。
3. 注释里写清:**基准图只能由这条 `update_goldens` 在 CI 上生成**,本机 `--update-goldens` 的产物不能提交
   (本机 API 37 vs CI API 34)。

## Task 4 —— 生成并提交基准图

`git push` 分支 → `workflow_dispatch(update_goldens=true)` → 下载 artifact → 提交两张 PNG → 再等 PR 的 app-ui 轨绿。

## Task 5 —— 文档

`docs/pitfalls/testing.md` 加「golden 基准图只能 CI 生成」一条;`docs/superpowers/README.md` §2 更新;
`docs/milestones.md` 加一行;交接文档把 W-L3 标成已交付。

---

## 验收

- [x] `scripts/verify.sh app` 绿(analyze 零告警 + 单测;golden **不在**这一轨,本机没有 CI 那套镜像)
- [x] 本机模拟器跑一次 `--update-goldens`,**肉眼**确认两张图是登录页 / 发现页而不是骨架屏或豆腐块
- [x] CI `update_goldens=true` 产出两张 PNG,提交后 PR 的 app-ui 轨**绿**
- [x] 故意改像素 → 红,且失败信息里能看到差异比例(本机扰动 4000 px 验的,见执行记录)
- [x] 本机基准图**没有**进提交(`git status` 干净)

## 不做

- 不做 `flutter drive` + `takeScreenshot` 的另一套:那是给「要图给产品看」用的,不是回归闸门。
- 不做深色模式 / 逐页 golden:两张图先立住「这套机制能跑」,再谈覆盖面。
- 不动版本号、不发版。

---

## 执行记录(2026-11-11)

**结论**:已交付,PR [#242](https://github.com/shiliu153/chatapp/pull/242),squash 合并 `74c1cef`。
`app-ui` 轨(模拟器)绿,`analyze-and-test` 绿;本机 659 例单测绿、analyze 零告警。

### 实际落地

| 计划里的 | 实际 | 说明 |
|---|---|---|
| 独立 `golden_test.dart` | ✅ 同计划 | 两张 golden:登录页 / 首页(发现) |
| 容差 comparator | ✅ 同计划,但**没用** `getTestUri` 解析路径 | 见坑 2 |
| 固定视口 390×844 | ✅ 但外层用 `OverflowBox` 而不是 `Align` | 见坑 1 |
| `app-ui.yml` 加 `update_goldens` 输入 | ✅ 同计划 | 产物走 artifact,不自动提交 |
| 基准图由 CI 生成 | ✅ 跑了两轮 | 第一轮 320×640(坑 1),修完 390×844 |

### 踩到的坑(都已写进 `docs/pitfalls/testing.md`)

1. **CI 的 AVD 逻辑屏幕只有 320×640**。用 `Align` 时子级拿到的是「0..屏幕宽」的松约束,
   `SizedBox(390×844)` 被压成 320×640 —— 第一轮 CI 生成出来的基准图就是 320×640。
   改 `OverflowBox`(给子级无界约束)后才稳定 390×844。**教训**:「固定视口」必须固定到
   子级拿到的**约束**,不是固定 SizedBox 的字面值。
2. **`GoldenFileComparator.getTestUri` 在 `version == null` 时原样返回 key**,不拼 basedir。
   拿它去 `File.fromUri` 会去 flutter_tools 的 cwd(`app/`)下找,永远「基准图不存在」。
   要按 `LocalFileComparator.basedir.resolveUri(key)` 解析。
3. `FutureOr` 不在 `flutter_test` 的导出面里(`只 export dart:async show Future`),
   `flutter_test_config.dart` 要自己 `import 'dart:async'`。
4. 设备侧**不能**替换 comparator:换了 `VmServiceProxyGoldenFileComparator` 就收不到截帧事件。
   所以配置文件里 `Platform.isAndroid/isIOS` 必须直接放行。

### 验证证据

- 本机三条路径:`--update-goldens` 出图(390×844,肉眼确认是登录页/发现页)→ 拿基准比对绿 →
  扰动 100 px(0.030%)绿、扰动 4000 px(1.215%)红,失败信息
  `Pixel test failed, 1.22%, 4000px diff detected. / 差异 1.215% 超过容差 0.10%`。
- CI:`workflow_dispatch(update_goldens=true)` 两次(run 42965263500 出 320×640 的图 → 修 → run
  42966342004 出 390×844 的图);PR 的 `app-ui` 轨用这两张基准比对绿。
- `flutter analyze`:No issues found;`flutter test`:659 例全绿。

### 遗留(交接)

1. golden 只覆盖两张图;深色模式与其他页面另开单。
2. golden **不进** `scripts/verify.sh app`(本机镜像与 CI 不同,本机比对必假红),判据只有 CI。
3. 换系统镜像(字体变了)必须重生成基准;换 AVD 尺寸**不用**。
