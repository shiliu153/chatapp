# UI 整改批次④:我的页 + 他人资料页 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按「心跳」规则 v1.3 整改我的页(Tab 主页)与他人资料页(二级页),并首次落地 §6.2 的 Hero 转场;247 既有测试全绿 + analyze 零告警 + 模拟器手测。

**Architecture:** 视觉层迁移:tokens → 共享组件(`AvatarHero` 新) → 资料域新组件(完成度环、两个骨架、照片头图) → 两个页面逐块重排 → Hero 接入四处来源(广场卡/动态详情作者/评论/聊天顶栏)并靠路由 `extra` 传 tag。行为、provider、接口、key 契约一律不动(两处已批准的行为新增除外)。

**Tech Stack:** Flutter 3.47(`../flutter/bin/flutter.bat`)、Riverpod、go_router、flutter_test(真实 provider + 假网络 `ScriptedAdapter` + 假 IM `FakeImClient`)。

**Spec:** `docs/superpowers/specs/2026-10-12-ui-revamp-batch4-design.md`(一切视觉细节以它 + 规则文档 v1.3 附录 C 为准)

## Global Constraints

- 所有视觉值走 token,**禁止新代码出现裸 hex / 裸字号 / 裸间距 / 裸圆角**(§1 铁律 3);确需新值先在组件内定义具名常量并注明附录条款(如 `_headerHeight`),或在 token 文件新增。
- **行为零变化**;唯一两处已批准例外:① 他人资料页接入在线状态(`presenceProvider.track`);② 聊天页顶栏新增头像 32(修订附录 B.2)。
- 无限动画(骨架/呼吸点/完成度环)可见的测试**一律有限 pump**(`pumpFrames`),禁 `pumpAndSettle`(见 `docs/pitfalls/testing.md`)。
- 每任务收尾必须:全量 `flutter analyze` 零告警 + 全量 `flutter test` 绿 + 提交。
- 所有 flutter/dart 命令 cwd = `app/`。
- **key 契约(不得改名)**:`my.row.gender`、`my.row.birthday`、`my.row.city`、`my.row.bio`、`my.row.tags`、`my.row.posts`、`my.row.preference`、`my.row.settings`、`my.goOnboarding`、`user.more`、`user.report`、`user.block`、`user.block.confirm`、`user.retry`、`user.album.photo:{i}`、`post.avatar.{id}`、`post.nickname.{id}`、`post.comment.avatar.{id}`、`post.comment.nickname.{id}`、`chat.title`、`chat.back`、`chat.onlineDot`、`viewer.page`、`viewer.close`。
- **新增 key**:`my.card.identity`(替代被收敛的 `my.row.avatar` / `my.row.nickname` / `my.row.id`)、`my.ring`、`user.back`、`profile.skeleton`、`user.skeleton`。
- **被删除的 key**:`my.row.avatar`、`my.row.nickname`、`my.row.id`(三行合并进身份卡)。
- 提交信息中文,前缀沿用仓库风格(`feat(ui):` / `fix(ui):` / `test(ui):` / `docs:`),尾行 `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`。
- 分支 `ui/batch4`(已建,spec 已提交为 `10f195d`)。

---

### Task 0: 基线验证(已完成,记录备查)

**Files:** 无代码改动

**Interfaces:**
- Produces: 分支 `ui/batch4`(后续全部任务在此分支提交)

- [x] **Step 1: 建分支**

```bash
git checkout master && git merge --ff-only origin/master
git checkout -b ui/batch4
git cherry-pick 6e04e22   # spec 提交
```

- [x] **Step 2: 基线全绿**

```bash
cd app
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
```

实测结果:analyze `No issues found!`;test **247 全绿**;`git diff --stat 6e880ab..4a1c9e6 -- app/ chatapp/` 为空(与上次测试的提交零差异)。

---

### Task 1: 规则文档升 v1.3 + 附录 C(§9 边界流程,先于代码)

**Files:**
- Modify: `docs/superpowers/specs/2026-09-15-ui-design-language-design.md`(头部状态行 + 文末追加附录 C + 修订 B.2)

**Interfaces:**
- Produces: 附录 C 条款(后续任务所有新数值的规则依据:C.1 头像 72 / C.2 身份卡 / C.3 我的页行版式 / C.4 照片头图 / C.5 透明顶栏 / C.6 相册网格 / C.7 Hero tag 规约 / C.8 聊天顶栏补头像)

- [ ] **Step 1: 改头部状态行**

第 4 行原文:

```markdown
状态:**v1.2(2026-09-19 增补附录 B:消息/聊天页落地补充),设计内容已获用户批准**(浏览器视觉评审通过);本文件是**常驻规则文档**
```

改为:

```markdown
状态:**v1.3(2026-10-12 增补附录 C:我的/资料页落地补充,并修订 B.2),设计内容已获用户批准**;本文件是**常驻规则文档**
```

- [ ] **Step 2: 修订附录 B.2(聊天页顶栏补头像)**

把 B.2 第一条原文:

```markdown
- 高 **62**(§5.2 二级页 52 的**例外**,为「名字 + 状态」两行留空间);返回箭头 22 `text1`;右侧无按钮(资料入口 = 点名字)
```

改为:

```markdown
- 高 **62**(§5.2 二级页 52 的**例外**,为「名字 + 状态」两行留空间);返回箭头 22 `text1`;**头像 32 圆形**(2026-10-12 批次④ 增补,承载 Hero 转场,见 C.8);右侧无按钮(资料入口 = 点头像或名字)
```

- [ ] **Step 3: 文末追加附录 C(整段粘贴)**

```markdown
## 附录 C:我的/资料页落地补充(2026-10-12,批次④)

本附录是 §9 边界流程的产出:以下场景规则正文未覆盖,经确认后定稿;后续页面遇同类场景以此为准。

### C.1 头像 72 档

- §5.3 尺寸档扩为 **28/32/40/48/56/72/96**;72 用于「我的」页身份卡(自己看自己,尺寸介于列表头像 56 与资料大头像 96 之间)

### C.2 身份卡(我的页)

- 白卡 `bgCard` R20、内边距 16;头像 72 圆形(`AppAvatar`,`fallbackText` 首字占位见 B.7)+ 昵称 20/w700 `text1` + `ID:u{user_id}` 12 `text3`
- 资料不完整时,卡内下段(上边 1px `divider`)补:完成度环 44 + 「还差:{缺项}」13 `text2` + 文字按钮「去完善」
- **完成度环**:44×44;底环 3px `divider`;进度弧 3px `gradientHeart`;中央 `done/total` 12 `text1`;它是本页唯一渐变高音(§2.2)

### C.3 我的页行版式

- 行高 56;标签 13 `text2` 定宽 72;取值 15 `text1`;右侧 `chevron_right_rounded` 20 `text3`;行间 1px `divider`;水平内边距 16
- 入口行(我的动态/想找的人/设置)左侧为 rounded 图标 22 `text2`

### C.4 资料页照片头图

- 全出血,高 `min(屏宽 × 1.15, 420)`;`BoxFit.cover`;无照片 → `divider` 底 + `person_rounded` 64 `text3`(内容占位,非空态)
- 底部 scrim 同 A.2(`Colors.transparent → AppColors.photoScrim`),内边距 `(16, 46, 16, 14)`
- 叠字白系:昵称·年龄 32/w800 白(格式「昵称,年龄」,无年龄不带逗号);城市 13 白 72%;在线 = 11 呼吸点(白描边)+「在线」13 白 88%;离线不渲染该行
- 顶部另叠一层 `Colors.transparent → 黑 45%` scrim,供透明顶栏兜底可读性

### C.5 资料页透明顶栏

- 高 52;返回 22 白(`arrow_back_ios_new_rounded`);右侧 `more_horiz_rounded` 24 白;**无标题**(照片与名字已承载身份)

### C.6 相册网格

- 3 列、间距 8、图片 R12(§5.3「相册不是头像」的落地参数)

### C.7 Hero 转场 tag 规约

- tag 由**来源自身 id** 派生:`avatar-post-{postId}` / `avatar-comment-{commentId}` / `avatar-chat-{peerId}`
- **不得用 `avatar-{userId}`**:Hero 要求同一路由内 tag 唯一,同作者多卡/多评论会同屏重复 → debug 直接抛 `There are multiple heroes that share the same tag`
- 跨页经 go_router 的 `extra` 传递;无来源(`extra == null`,如深链)时**两端都不包 Hero**,静默不飞、不报错
- 飞行用 `flightShuttleBuilder` 渲染同一张图(`fit: cover`,对任意尺寸自适应),圆角自来源半径线性插值到 0(目标是全出血直角头图)
- `MediaQuery.disableAnimations` 为真时不包 Hero(§6.3 降级)

### C.8 聊天页顶栏补头像(修订 B.2)

- 左侧改为「返回 + 头像 32 圆形」;头像带 Hero(tag `avatar-chat-{peerId}`);点头像或名字均进资料页
- 标题区仍两行居中;右侧仍无按钮;为保持名字视觉居中,左右两侧占位等宽
```

- [ ] **Step 4: 提交**

```bash
git add docs/superpowers/specs/2026-09-15-ui-design-language-design.md
git commit -m "$(cat <<'EOF'
docs: 「心跳」规则升 v1.3,新增附录 C(我的/资料页落地:头像 72/身份卡/照片头图/透明顶栏/Hero tag 规约)并修订 B.2 聊天顶栏补头像

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `AvatarHero` 共享组件

**Files:**
- Create: `app/lib/core/widgets/avatar_hero.dart`
- Test: `app/test/core/widgets/avatar_hero_test.dart`

**Interfaces:**
- Consumes: `AppRadius.chip`(8)
- Produces: `AvatarHero({Key? key, required String? tag, required String? imageUrl, required Widget child, double fromRadius = AppRadius.chip})` —— 后续 Task 7/8 消费

- [ ] **Step 1: 写失败测试**

创建 `app/test/core/widgets/avatar_hero_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/avatar_hero.dart';

Widget wrap(Widget child, {bool disableAnimations = false}) => MaterialApp(
      home: MediaQuery(
        data: MediaQueryData(disableAnimations: disableAnimations),
        child: Scaffold(body: Center(child: child)),
      ),
    );

void main() {
  testWidgets('tag 非空 → 包一层 Hero', (tester) async {
    await tester.pumpWidget(wrap(const AvatarHero(
      tag: 'avatar-post-1',
      imageUrl: null,
      child: SizedBox(width: 40, height: 40),
    )));

    final hero = tester.widget<Hero>(find.byType(Hero));
    expect(hero.tag, 'avatar-post-1');
  });

  testWidgets('tag 为 null → 不包 Hero(无来源/深链)', (tester) async {
    await tester.pumpWidget(wrap(const AvatarHero(
      tag: null,
      imageUrl: null,
      child: SizedBox(width: 40, height: 40),
    )));

    expect(find.byType(Hero), findsNothing);
    expect(find.byType(SizedBox), findsWidgets); // child 仍在
  });

  testWidgets('减弱动态效果 → 不包 Hero', (tester) async {
    await tester.pumpWidget(wrap(
      const AvatarHero(
        tag: 'avatar-post-1',
        imageUrl: null,
        child: SizedBox(width: 40, height: 40),
      ),
      disableAnimations: true,
    ));

    expect(find.byType(Hero), findsNothing);
  });

  testWidgets('child 正常渲染', (tester) async {
    await tester.pumpWidget(wrap(const AvatarHero(
      tag: 'avatar-post-1',
      imageUrl: null,
      child: Text('头像占位'),
    )));

    expect(find.text('头像占位'), findsOneWidget);
  });
}
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd app
../flutter/bin/flutter.bat test test/core/widgets/avatar_hero_test.dart
```

Expected: 编译失败 `Target of URI doesn't exist: 'package:chatapp_app/core/widgets/avatar_hero.dart'`。

- [ ] **Step 3: 写最小实现**

创建 `app/lib/core/widgets/avatar_hero.dart`:

```dart
import 'package:flutter/material.dart';

import '../theme/app_radius.dart';

/// 「心跳」附录 C.7:Hero 转场包装。
///
/// [tag] 为 null(无来源/深链)或系统开启「减弱动态效果」时**不包 Hero**,
/// 静默降级为普通渲染——两端不同时存在时不会报错。
///
/// [imageUrl] 是飞行途中显示的图。两端取的是**同一张**(后端两侧都取该用户
/// 第一张已过审照片),故对 push/pop 两个方向都正确;为 null 时回退到 child。
class AvatarHero extends StatelessWidget {
  const AvatarHero({
    super.key,
    required this.tag,
    required this.imageUrl,
    required this.child,
    this.fromRadius = AppRadius.chip,
  });

  final String? tag;
  final String? imageUrl;
  final Widget child;

  /// 来源侧圆角;飞行时线性插值到 0(目标是全出血直角头图)。
  final double fromRadius;

  @override
  Widget build(BuildContext context) {
    final heroTag = tag;
    if (heroTag == null || MediaQuery.disableAnimationsOf(context)) return child;
    return Hero(
      tag: heroTag,
      flightShuttleBuilder: (flightContext, animation, direction, fromContext, toContext) {
        // t=0 对应来源(小头像,带圆角),t=1 对应目标(头图,直角)
        final t = direction == HeroFlightDirection.push ? animation.value : 1 - animation.value;
        final url = imageUrl;
        final Widget shuttle = (url == null || url.isEmpty)
            ? (direction == HeroFlightDirection.push
                ? (toContext.widget as Hero).child
                : (fromContext.widget as Hero).child)
            : Image.network(
                url,
                fit: BoxFit.cover,
                errorBuilder: (_, _, _) => const ColoredBox(color: Color(0x00000000)),
              );
        return ClipRRect(
          borderRadius: BorderRadius.circular(fromRadius * (1 - t)),
          child: shuttle,
        );
      },
      child: child,
    );
  }
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd app
../flutter/bin/flutter.bat test test/core/widgets/avatar_hero_test.dart
```

Expected: 4 用例 PASS。

- [ ] **Step 5: 全量门槛 + 提交**

```bash
cd app
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
git add app/lib/core/widgets/avatar_hero.dart app/test/core/widgets/avatar_hero_test.dart
git commit -m "$(cat <<'EOF'
feat(ui): 新增 AvatarHero(Hero 转场包装:tag 为空或减弱动效时不包 Hero,飞行圆角插值到 0)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `CompletionRing` 完成度环

**Files:**
- Create: `app/lib/features/profile/widgets/completion_ring.dart`
- Test: `app/test/features/profile/completion_ring_test.dart`

**Interfaces:**
- Consumes: `AppColors`、`AppGradients.heart`、`AppText.micro`
- Produces: `CompletionRing({Key? key, required int done, required int total, double size = 44})` —— Task 6 消费

- [ ] **Step 1: 写失败测试**

创建 `app/test/features/profile/completion_ring_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/profile/widgets/completion_ring.dart';

Widget wrap(Widget child) => MaterialApp(home: Scaffold(body: Center(child: child)));

void main() {
  testWidgets('渲染 done/total 文案', (tester) async {
    await tester.pumpWidget(wrap(const CompletionRing(done: 4, total: 6)));
    expect(find.text('4/6'), findsOneWidget);
  });

  testWidgets('done=0 不崩且显示 0/6', (tester) async {
    await tester.pumpWidget(wrap(const CompletionRing(done: 0, total: 6)));
    expect(find.text('0/6'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('done=total(满弧)不崩', (tester) async {
    await tester.pumpWidget(wrap(const CompletionRing(done: 6, total: 6)));
    expect(find.text('6/6'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('total=0 不除零', (tester) async {
    await tester.pumpWidget(wrap(const CompletionRing(done: 0, total: 0)));
    expect(tester.takeException(), isNull);
  });

  testWidgets('尺寸可覆盖', (tester) async {
    await tester.pumpWidget(wrap(const CompletionRing(done: 1, total: 6, size: 64)));
    final box = tester.getSize(find.byType(CompletionRing));
    expect(box.width, 64);
  });
}
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd app
../flutter/bin/flutter.bat test test/features/profile/completion_ring_test.dart
```

Expected: 编译失败 `Target of URI doesn't exist`。

- [ ] **Step 3: 写最小实现**

创建 `app/lib/features/profile/widgets/completion_ring.dart`:

```dart
import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_gradients.dart';
import '../../../core/theme/app_typography.dart';

/// 「心跳」附录 C.2 完成度环:底环 3px divider + 渐变进度弧 3px + 中央 done/total。
/// 它是「我的」页唯一的渐变高音,把视线引到「去完善」。
class CompletionRing extends StatelessWidget {
  const CompletionRing({
    super.key,
    required this.done,
    required this.total,
    this.size = 44,
  });

  final int done;
  final int total;
  final double size;

  static const _stroke = 3.0;

  @override
  Widget build(BuildContext context) {
    // total=0 时不画弧,避免除零
    final progress = total <= 0 ? 0.0 : (done / total).clamp(0.0, 1.0);
    return SizedBox.square(
      key: const Key('my.ring'),
      dimension: size,
      child: Stack(
        alignment: Alignment.center,
        children: [
          CustomPaint(
            size: Size.square(size),
            painter: _RingPainter(progress: progress, stroke: _stroke),
          ),
          Text('$done/$total', style: AppText.micro.copyWith(color: AppColors.text1)),
        ],
      ),
    );
  }
}

class _RingPainter extends CustomPainter {
  const _RingPainter({required this.progress, required this.stroke});

  final double progress;
  final double stroke;

  @override
  void paint(Canvas canvas, Size size) {
    final rect = Rect.fromLTWH(stroke / 2, stroke / 2, size.width - stroke, size.height - stroke);
    final base = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = stroke
      ..color = AppColors.divider;
    canvas.drawArc(rect, 0, math.pi * 2, false, base);

    if (progress <= 0) return;
    final arc = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = stroke
      ..strokeCap = StrokeCap.round
      ..shader = const SweepGradient(
        colors: [AppColors.brand, AppColors.heartOrange],
      ).createShader(rect);
    // 从 12 点方向起画,顺时针
    canvas.drawArc(rect, -math.pi / 2, math.pi * 2 * progress, false, arc);
  }

  @override
  bool shouldRepaint(_RingPainter old) =>
      old.progress != progress || old.stroke != stroke;
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd app
../flutter/bin/flutter.bat test test/features/profile/completion_ring_test.dart
```

Expected: 5 用例 PASS。

- [ ] **Step 5: 全量门槛 + 提交**

```bash
cd app
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
git add app/lib/features/profile/widgets/completion_ring.dart app/test/features/profile/completion_ring_test.dart
git commit -m "$(cat <<'EOF'
feat(ui): 新增 CompletionRing 完成度环(渐变进度弧 + done/total,附录 C.2)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: 两个页面骨架屏

**Files:**
- Create: `app/lib/features/profile/widgets/profile_skeleton.dart`(我的页)
- Create: `app/lib/features/profile/widgets/user_profile_skeleton.dart`(他人资料页)
- Test: `app/test/features/profile/profile_skeleton_test.dart`

**Interfaces:**
- Consumes: `AppSkeleton({width, height, radius})`、`AppRadius.full` / `AppRadius.card`、`AppSpacing`
- Produces: `ProfileSkeleton({Key? key})`(key `profile.skeleton`)、`UserProfileSkeleton({Key? key})`(key `user.skeleton`) —— Task 6/7 消费

- [ ] **Step 1: 写失败测试**

创建 `app/test/features/profile/profile_skeleton_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/app_skeleton.dart';
import 'package:chatapp_app/features/profile/widgets/profile_skeleton.dart';
import 'package:chatapp_app/features/profile/widgets/user_profile_skeleton.dart';

import '../../support/harness.dart';

Widget wrap(Widget child) => MaterialApp(home: Scaffold(body: child));

void main() {
  // 骨架是无限呼吸动画:一律有限 pump,禁 pumpAndSettle
  testWidgets('ProfileSkeleton 渲染身份卡 + 行骨架', (tester) async {
    await tester.pumpWidget(wrap(const ProfileSkeleton()));
    await pumpFrames(tester, frames: 3);

    expect(find.byKey(const Key('profile.skeleton')), findsOneWidget);
    expect(find.byType(AppSkeleton), findsWidgets);
  });

  testWidgets('UserProfileSkeleton 渲染头图 + 行骨架', (tester) async {
    await tester.pumpWidget(wrap(const UserProfileSkeleton()));
    await pumpFrames(tester, frames: 3);

    expect(find.byKey(const Key('user.skeleton')), findsOneWidget);
    expect(find.byType(AppSkeleton), findsWidgets);
  });
}
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd app
../flutter/bin/flutter.bat test test/features/profile/profile_skeleton_test.dart
```

Expected: 编译失败 `Target of URI doesn't exist`。

- [ ] **Step 3: 写最小实现**

创建 `app/lib/features/profile/widgets/profile_skeleton.dart`:

```dart
import 'package:flutter/material.dart';

import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/widgets/app_skeleton.dart';

/// 「我的」页骨架:身份卡(72 圆块 + 两条文字条)+ 5 行行骨架。
/// 呼吸动画为无限循环——可见它的测试只用有限 pump。
class ProfileSkeleton extends StatelessWidget {
  const ProfileSkeleton({super.key});

  @override
  Widget build(BuildContext context) => ListView(
        key: const Key('profile.skeleton'),
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.pageH),
        children: [
          Row(
            children: const [
              AppSkeleton(width: 72, height: 72, radius: AppRadius.full),
              SizedBox(width: AppSpacing.lg),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    AppSkeleton(width: 120, height: 20),
                    SizedBox(height: AppSpacing.sm),
                    AppSkeleton(width: 72, height: 12),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.xxl),
          for (var i = 0; i < 5; i++) ...[
            const AppSkeleton(width: double.infinity, height: 16),
            const SizedBox(height: AppSpacing.xl),
          ],
        ],
      );
}
```

创建 `app/lib/features/profile/widgets/user_profile_skeleton.dart`:

```dart
import 'package:flutter/material.dart';

import '../../../core/theme/app_spacing.dart';
import '../../../core/widgets/app_skeleton.dart';

/// 他人资料页骨架:头图等大骨架 + 3 行行骨架。
/// 呼吸动画为无限循环——可见它的测试只用有限 pump。
class UserProfileSkeleton extends StatelessWidget {
  const UserProfileSkeleton({super.key});

  /// 与附录 C.4 的头图比例一致(屏宽 × 1.15,封顶 420)。
  static const _headerRatio = 1.15;
  static const _headerMax = 420.0;

  @override
  Widget build(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width;
    final headerHeight =
        width * _headerRatio > _headerMax ? _headerMax : width * _headerRatio;
    return Column(
      key: const Key('user.skeleton'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        AppSkeleton(width: double.infinity, height: headerHeight, radius: 0),
        const SizedBox(height: AppSpacing.lg),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.pageH),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              for (var i = 0; i < 3; i++) ...[
                const AppSkeleton(width: double.infinity, height: 16),
                const SizedBox(height: AppSpacing.xl),
              ],
            ],
          ),
        ),
      ],
    );
  }
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd app
../flutter/bin/flutter.bat test test/features/profile/profile_skeleton_test.dart
```

Expected: 2 用例 PASS。

- [ ] **Step 5: 全量门槛 + 提交**

```bash
cd app
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
git add app/lib/features/profile/widgets/profile_skeleton.dart app/lib/features/profile/widgets/user_profile_skeleton.dart app/test/features/profile/profile_skeleton_test.dart
git commit -m "$(cat <<'EOF'
feat(ui): 新增我的页/他人资料页骨架屏(替换 CircularProgressIndicator)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `ProfilePhotoHeader` 照片头图

**Files:**
- Create: `app/lib/features/profile/widgets/profile_photo_header.dart`
- Test: `app/test/features/profile/profile_photo_header_test.dart`

**Interfaces:**
- Consumes: `AvatarHero`(Task 2)、`BreathingDot`、`AppColors.photoScrim`、`AppText.display/caption/micro`
- Produces: `ProfilePhotoHeader({Key? key, required String? photoUrl, required String nickname, int? age, String city = '', bool online = false, String? heroTag})` —— Task 7 消费

- [ ] **Step 1: 写失败测试**

创建 `app/test/features/profile/profile_photo_header_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/avatar_hero.dart';
import 'package:chatapp_app/features/profile/widgets/profile_photo_header.dart';

import '../../support/harness.dart';

Widget wrap(Widget child) => MaterialApp(home: Scaffold(body: child));

void main() {
  testWidgets('有照片:渲染网络图 + 昵称·年龄 + 城市', (tester) async {
    await tester.pumpWidget(wrap(const ProfilePhotoHeader(
      photoUrl: 'http://test/media/photos/1.png',
      nickname: '小红',
      age: 25,
      city: '上海',
    )));
    await pumpFrames(tester, frames: 3);

    expect(find.byType(Image), findsWidgets);
    expect(find.text('小红,25'), findsOneWidget);
    expect(find.text('上海'), findsOneWidget);
  });

  testWidgets('无年龄:昵称不带逗号', (tester) async {
    await tester.pumpWidget(wrap(const ProfilePhotoHeader(
      photoUrl: null,
      nickname: '小红',
      age: null,
    )));
    await pumpFrames(tester, frames: 3);

    expect(find.text('小红'), findsOneWidget);
  });

  testWidgets('无照片:走 person 占位(非空态)', (tester) async {
    await tester.pumpWidget(wrap(const ProfilePhotoHeader(
      photoUrl: null,
      nickname: '小红',
    )));
    await pumpFrames(tester, frames: 3);

    expect(find.byIcon(Icons.person_rounded), findsOneWidget);
  });

  testWidgets('在线:渲染呼吸点 + 「在线」', (tester) async {
    await tester.pumpWidget(wrap(const ProfilePhotoHeader(
      photoUrl: null,
      nickname: '小红',
      online: true,
    )));
    await pumpFrames(tester, frames: 3);

    expect(find.text('在线'), findsOneWidget);
    expect(find.byKey(const Key('user.onlineDot')), findsOneWidget);
  });

  testWidgets('离线:不渲染在线行', (tester) async {
    await tester.pumpWidget(wrap(const ProfilePhotoHeader(
      photoUrl: null,
      nickname: '小红',
      online: false,
    )));
    await pumpFrames(tester, frames: 3);

    expect(find.text('在线'), findsNothing);
  });

  testWidgets('heroTag 非空 → 包 AvatarHero', (tester) async {
    await tester.pumpWidget(wrap(const ProfilePhotoHeader(
      photoUrl: 'http://test/media/photos/1.png',
      nickname: '小红',
      heroTag: 'avatar-post-1',
    )));
    await pumpFrames(tester, frames: 3);

    final hero = tester.widget<AvatarHero>(find.byType(AvatarHero));
    expect(hero.tag, 'avatar-post-1');
  });
}
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd app
../flutter/bin/flutter.bat test test/features/profile/profile_photo_header_test.dart
```

Expected: 编译失败 `Target of URI doesn't exist`。

- [ ] **Step 3: 写最小实现**

创建 `app/lib/features/profile/widgets/profile_photo_header.dart`:

```dart
import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/widgets/avatar_hero.dart';
import '../../../core/widgets/breathing_dot.dart';

/// 「心跳」附录 C.4 资料页照片头图:全出血照片 + 底部 scrim 叠字 + 顶部 scrim
/// 供透明顶栏(C.5)兜底可读性。无照片时走内容占位(非空态)。
class ProfilePhotoHeader extends StatelessWidget {
  const ProfilePhotoHeader({
    super.key,
    required this.photoUrl,
    required this.nickname,
    this.age,
    this.city = '',
    this.online = false,
    this.heroTag,
  });

  final String? photoUrl;
  final String nickname;
  final int? age;
  final String city;
  final bool online;

  /// Hero tag(C.7);为 null(无来源/深链)时不包 Hero。
  final String? heroTag;

  static const _ratio = 1.15; // 屏宽 × 1.15
  static const _maxHeight = 420.0;
  static const _topScrimAlpha = 0.45;

  @override
  Widget build(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width;
    final height = width * _ratio > _maxHeight ? _maxHeight : width * _ratio;
    final url = photoUrl;
    return SizedBox(
      height: height,
      width: double.infinity,
      child: Stack(
        fit: StackFit.expand,
        children: [
          AvatarHero(
            tag: heroTag,
            imageUrl: url,
            child: url == null || url.isEmpty
                ? const ColoredBox(
                    color: AppColors.divider,
                    child: Center(
                      child: Icon(Icons.person_rounded, size: 64, color: AppColors.text3),
                    ),
                  )
                : Image.network(
                    url,
                    fit: BoxFit.cover,
                    errorBuilder: (_, _, _) => const ColoredBox(
                      color: AppColors.divider,
                      child: Center(
                        child: Icon(Icons.person_rounded, size: 64, color: AppColors.text3),
                      ),
                    ),
                  ),
          ),
          // 顶部 scrim:透明顶栏(返回/⋯ 为白色图标)在浅色照片上的可读性兜底
          const DecoratedBox(
            decoration: BoxDecoration(
              gradient: LinearGradient(
                begin: Alignment.topCenter,
                end: Alignment.bottomCenter,
                colors: [Color(0x73000000), Colors.transparent],
              ),
            ),
          ),
          // 底部 scrim:叠字对比度(与附录 A.2 同源)
          Positioned(
            left: 0,
            right: 0,
            bottom: 0,
            child: Container(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.lg, 46, AppSpacing.lg, 14),
              decoration: const BoxDecoration(
                gradient: LinearGradient(
                  begin: Alignment.topCenter,
                  end: Alignment.bottomCenter,
                  colors: [Colors.transparent, AppColors.photoScrim],
                ),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    age == null ? nickname : '$nickname,$age',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: AppText.display.copyWith(color: Colors.white),
                  ),
                  if (online) ...[
                    const SizedBox(height: AppSpacing.xs),
                    Row(
                      children: [
                        const BreathingDot(
                          key: Key('user.onlineDot'),
                          size: 11,
                          borderColor: Colors.white,
                        ),
                        const SizedBox(width: AppSpacing.sm),
                        Text('在线',
                            style: AppText.micro.copyWith(
                                color: Colors.white.withValues(alpha: 0.88))),
                      ],
                    ),
                  ],
                  if (city.isNotEmpty) ...[
                    const SizedBox(height: AppSpacing.xs),
                    Text(city,
                        style: AppText.caption
                            .copyWith(color: Colors.white.withValues(alpha: 0.72))),
                  ],
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
```

**注意**:`Color(0x73000000)` 是「黑 45%」。§2.1 无对应 token 且 A.2 的先例是「起点直接用 `Colors.transparent`」;此处为新增半透明黑,按 §9 已在附录 C.4 登记,故允许就地写具名常量。若审查要求零裸 hex,可改为 `Colors.black.withValues(alpha: _topScrimAlpha)` —— **实现时用后者**(`_topScrimAlpha` 常量已定义)。

- [ ] **Step 4: 跑测试确认通过**

```bash
cd app
../flutter/bin/flutter.bat test test/features/profile/profile_photo_header_test.dart
```

Expected: 6 用例 PASS。

- [ ] **Step 5: 全量门槛 + 提交**

```bash
cd app
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
git add app/lib/features/profile/widgets/profile_photo_header.dart app/test/features/profile/profile_photo_header_test.dart
git commit -m "$(cat <<'EOF'
feat(ui): 新增 ProfilePhotoHeader(照片头图 + 双向 scrim 叠字 + 在线呼吸点,附录 C.4)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: 我的页重排

**Files:**
- Modify: `app/lib/features/profile/my_profile_page.dart`(整体重写)
- Modify: `app/test/features/profile/my_profile_page_test.dart`
- Modify: `app/test/features/shell/home_shell_test.dart:40`
- Modify: `app/test/features/profile/profile_edit_page_test.dart:23,48`

**Interfaces:**
- Consumes: `CompletionRing`(T3)、`ProfileSkeleton`(T4)、`AppAvatar`、`AppErrorView`、`apiMessageOf`、`missingFieldLabel`
- Produces: 页面 key `my.card.identity` / `my.ring` / `my.goOnboarding`;行 key 同前

- [ ] **Step 1: 先改既有测试(它们描述新契约)**

`app/test/features/profile/my_profile_page_test.dart` 第 28、32 行:

```dart
    expect(find.text('u7'), findsOneWidget); // ID 行用 u{user_id}
```

改为:

```dart
    expect(find.text('ID:u7'), findsOneWidget); // 身份卡里 ID 自带前缀
```

第 32 行:

```dart
    expect(find.byKey(const Key('my.row.id')), findsOneWidget);
```

改为:

```dart
    expect(find.byKey(const Key('my.card.identity')), findsOneWidget);
```

`app/test/features/shell/home_shell_test.dart` 第 40 行:

```dart
    expect(find.byKey(const Key('my.row.nickname')), findsOneWidget); // 资料行即编辑入口
```

改为:

```dart
    expect(find.byKey(const Key('my.card.identity')), findsOneWidget); // 身份卡即编辑入口
```

`app/test/features/profile/profile_edit_page_test.dart` 第 23 与 48 行的 `find.byKey(const Key('my.row.nickname'))` 均改为 `find.byKey(const Key('my.card.identity'))`。

- [ ] **Step 2: 跑测试确认失败**

```bash
cd app
../flutter/bin/flutter.bat test test/features/profile/my_profile_page_test.dart
```

Expected: FAIL —— `my.card.identity` 找不到(`findsNothing`)。

- [ ] **Step 3: 重写页面**

整体替换 `app/lib/features/profile/my_profile_page.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_radius.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_avatar.dart';
import '../../core/widgets/app_card.dart';
import '../../core/widgets/app_error_view.dart';
import 'models.dart';
import 'profile_controller.dart';
import 'widgets/completion_ring.dart';
import 'widgets/profile_skeleton.dart';

/// 资料完善度的总项数:昵称/性别/生日/城市/简介/照片(与后端 missing_fields 同源)。
const _profileFieldCount = 6;

class MyProfilePage extends ConsumerWidget {
  const MyProfilePage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final profile = ref.watch(profileProvider);
    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.pageH, AppSpacing.lg, AppSpacing.pageH, AppSpacing.md),
              child: Text('我的',
                  style: AppText.display.copyWith(color: AppColors.text1)),
            ),
            Expanded(
              child: profile.when(
                loading: () => const ProfileSkeleton(),
                error: (error, _) => AppErrorView(
                  message: apiMessageOf(error),
                  onRetry: () => ref.read(profileProvider.notifier).reload(),
                ),
                data: (data) => _ProfileBody(profile: data),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ProfileBody extends StatelessWidget {
  const _ProfileBody({required this.profile});

  final Profile profile;

  @override
  Widget build(BuildContext context) => ListView(
        padding: const EdgeInsets.fromLTRB(
            AppSpacing.pageH, 0, AppSpacing.pageH, AppSpacing.xxl),
        children: [
          _IdentityCard(profile: profile),
          const SizedBox(height: AppSpacing.md),
          _Group(children: [
            _InfoRow(
              rowKey: 'my.row.gender',
              label: '性别',
              value: _genderLabel(profile.gender),
              onTap: () => context.push('/profile/edit'),
            ),
            _InfoRow(
              rowKey: 'my.row.birthday',
              label: '生日',
              value: profile.birthday ?? '',
              onTap: () => context.push('/profile/edit'),
            ),
            _InfoRow(
              rowKey: 'my.row.city',
              label: '城市',
              value: profile.city,
              onTap: () => context.push('/profile/edit'),
            ),
            _InfoRow(
              rowKey: 'my.row.bio',
              label: '简介',
              value: profile.bio,
              onTap: () => context.push('/profile/edit'),
            ),
            _InfoRow(
              rowKey: 'my.row.tags',
              label: '标签',
              value: profile.tags.map((tag) => tag.name).join('、'),
              onTap: () => context.push('/profile/edit'),
            ),
          ]),
          const SizedBox(height: AppSpacing.md),
          _Group(children: [
            _InfoRow(
              rowKey: 'my.row.posts',
              label: '我的动态',
              icon: Icons.grid_view_rounded,
              onTap: () => context.push('/my-posts'),
            ),
            _InfoRow(
              rowKey: 'my.row.preference',
              label: '想找的人',
              icon: Icons.favorite_rounded,
              onTap: () => context.push('/preference'),
            ),
            _InfoRow(
              rowKey: 'my.row.settings',
              label: '设置',
              icon: Icons.settings_rounded,
              onTap: () => context.push('/settings'),
            ),
          ]),
        ],
      );
}

String _genderLabel(String? gender) => switch (gender) {
      'male' => '男',
      'female' => '女',
      _ => '',
    };

/// 附录 C.2 身份卡:身份区(整段可点进编辑)+ 完成度区(仅资料不完整时)。
/// 分两段是为了避免可点区域嵌套(内层「去完善」不能被外层吞掉)。
class _IdentityCard extends StatelessWidget {
  const _IdentityCard({required this.profile});

  final Profile profile;

  @override
  Widget build(BuildContext context) {
    final missing = profile.missingFields;
    final done = (_profileFieldCount - missing.length).clamp(0, _profileFieldCount);
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          GestureDetector(
            key: const Key('my.card.identity'),
            behavior: HitTestBehavior.opaque,
            onTap: () => context.push('/profile/edit'),
            child: Row(
              children: [
                AppAvatar(
                  imageUrl: profile.avatar?.url,
                  size: 72,
                  fallbackText: profile.nickname,
                ),
                const SizedBox(width: AppSpacing.lg),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        profile.nickname,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: AppText.title.copyWith(color: AppColors.text1),
                      ),
                      const SizedBox(height: AppSpacing.xs),
                      Text('ID:u${profile.userId}',
                          style: AppText.micro.copyWith(color: AppColors.text3)),
                    ],
                  ),
                ),
              ],
            ),
          ),
          if (missing.isNotEmpty) ...[
            const SizedBox(height: AppSpacing.lg),
            const Divider(height: 1, thickness: 1, color: AppColors.divider),
            const SizedBox(height: AppSpacing.md),
            Row(
              children: [
                CompletionRing(done: done, total: _profileFieldCount),
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  child: Text(
                    '还差:${missing.map(missingFieldLabel).join('、')}',
                    style: AppText.caption.copyWith(color: AppColors.text2),
                  ),
                ),
                TextButton(
                  key: const Key('my.goOnboarding'),
                  onPressed: () => context.go('/onboarding'),
                  child: Text('去完善',
                      style: AppText.body
                          .copyWith(color: AppColors.brand, fontWeight: FontWeight.w600)),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

/// 白底分组:组与组之间露出页面底色。
class _Group extends StatelessWidget {
  const _Group({required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) => Container(
        decoration: BoxDecoration(
          color: AppColors.bgCard,
          borderRadius: BorderRadius.circular(AppRadius.card),
        ),
        clipBehavior: Clip.antiAlias,
        child: Column(children: children),
      );
}

/// 附录 C.3 行:标签 13 text2 定宽 72 + 取值 15 text1 + chevron;空值显示「未填」。
class _InfoRow extends StatelessWidget {
  const _InfoRow({
    required this.rowKey,
    required this.label,
    this.value,
    this.icon,
    this.onTap,
  });

  final String rowKey;
  final String label;
  final String? value;
  final IconData? icon;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    // value == null:纯入口行,不显示取值;空串:数据字段未填
    final text = value == null ? '' : (value!.isEmpty ? '未填' : value!);
    final leading = icon;
    return InkWell(
      key: Key(rowKey),
      onTap: onTap,
      child: Container(
        constraints: const BoxConstraints(minHeight: 56),
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
        decoration: const BoxDecoration(
          border: Border(bottom: BorderSide(color: AppColors.divider)),
        ),
        child: Row(
          children: [
            if (leading != null) ...[
              Icon(leading, size: 22, color: AppColors.text2),
              const SizedBox(width: AppSpacing.md),
            ],
            SizedBox(
              width: 72,
              child: Text(label,
                  style: AppText.caption.copyWith(color: AppColors.text2)),
            ),
            Expanded(
              child: Text(
                text,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: AppText.body.copyWith(color: AppColors.text1),
              ),
            ),
            const Icon(Icons.chevron_right_rounded, color: AppColors.text3, size: 20),
          ],
        ),
      ),
    );
  }
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd app
../flutter/bin/flutter.bat test test/features/profile/my_profile_page_test.dart test/features/profile/profile_edit_page_test.dart test/features/shell/home_shell_test.dart
```

Expected: 全部 PASS。

- [ ] **Step 5: 补新增用例**

在 `app/test/features/profile/my_profile_page_test.dart` 末尾(`main()` 内)追加:

```dart
  testWidgets('资料不完整 → 完成度环 + 还差 + 去完善跳引导页', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) =>
          ok(profileJson(nickname: '小雨', city: '', bio: '', missing: ['city', 'bio', 'photos'])),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await tester.tap(navTab('我的'));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('my.ring')), findsOneWidget);
    expect(find.text('3/6'), findsOneWidget);            // 6 - 3 缺项
    expect(find.text('还差:城市、简介、照片'), findsOneWidget);

    await tester.tap(find.byKey(const Key('my.goOnboarding')));
    await tester.pumpAndSettle();
    expect(find.text('第 1 步 / 共 3 步'), findsOneWidget);
  });

  testWidgets('资料完整 → 不显示完成度区', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson(nickname: '小雨')),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await tester.tap(navTab('我的'));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('my.ring')), findsNothing);
    expect(find.byKey(const Key('my.goOnboarding')), findsNothing);
    expect(find.textContaining('还差'), findsNothing);
  });

  testWidgets('点身份卡 → 进编辑资料页', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /users/tags': (options) => ok([tagJson(1, '运动')]),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await tester.tap(navTab('我的'));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('my.card.identity')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('edit.nickname')), findsOneWidget);
  });
```

- [ ] **Step 6: 跑测试确认通过**

```bash
cd app
../flutter/bin/flutter.bat test test/features/profile/my_profile_page_test.dart
```

Expected: 6 用例 PASS(3 既有 + 3 新增)。

- [ ] **Step 7: 全量门槛 + 提交**

```bash
cd app
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
git add app/lib/features/profile/my_profile_page.dart app/test/features/profile/my_profile_page_test.dart app/test/features/shell/home_shell_test.dart app/test/features/profile/profile_edit_page_test.dart
git commit -m "$(cat <<'EOF'
feat(ui): 我的页改身份卡 + 资料行 + 入口组(行数 8→5,完成度环并进身份卡,加载/错误态换骨架与 AppErrorView)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: 他人资料页重排

**Files:**
- Modify: `app/lib/features/profile/user_profile_page.dart`(整体重写)
- Modify: `app/test/features/profile/user_profile_page_test.dart`
- Modify: `app/test/features/square/square_page_test.dart:115,132,147`
- Modify: `app/test/features/square/post_detail_page_test.dart:98,117,135`

**Interfaces:**
- Consumes: `ProfilePhotoHeader`(T5)、`UserProfileSkeleton`(T4)、`AppErrorView`、`presenceProvider`、`openPhotoViewer`
- Produces: 页面 key `user.back` / `user.more` / `user.retry` / `user.album.photo:{i}`;新增构造参数 `heroTag`

- [ ] **Step 1: 先改既有测试(删标题的直接后果 + 新契约)**

**`app/test/features/square/square_page_test.dart`**:第 115 行 `expect(find.text('详细资料'), findsOneWidget);` → `expect(find.byType(UserProfilePage), findsOneWidget);`;第 132 行同样改;第 147 行 `expect(find.text('详细资料'), findsNothing);` → `expect(find.byType(UserProfilePage), findsNothing);`。

文件顶部 import 区加:

```dart
import 'package:chatapp_app/features/profile/user_profile_page.dart';
```

**`app/test/features/square/post_detail_page_test.dart`**:第 98、117、135 行同样替换(`findsOneWidget` ×2、`findsNothing` ×1),并加同样的 import。

- [ ] **Step 2: 跑测试确认失败**

```bash
cd app
../flutter/bin/flutter.bat test test/features/square/square_page_test.dart
```

Expected: FAIL —— `UserProfilePage` 未找到 / 类型不匹配(页面仍是旧结构)。

- [ ] **Step 3: 重写页面**

整体替换 `app/lib/features/profile/user_profile_page.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_radius.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_card.dart';
import '../../core/widgets/app_error_view.dart';
import '../../im/im_manager.dart';
import '../chat/conversations_controller.dart';
import '../chat/widgets/photo_viewer.dart';
import '../moderation/models.dart';
import '../moderation/moderation_controller.dart';
import '../moderation/moderation_repository.dart';
import '../moderation/widgets/report_sheet.dart';
import '../presence/presence_controller.dart';
import 'widgets/profile_photo_header.dart';
import 'widgets/user_profile_skeleton.dart';

class UserProfilePage extends ConsumerWidget {
  const UserProfilePage({super.key, required this.userId, this.heroTag});

  final int userId;

  /// Hero tag(附录 C.7);来自路由 extra。null(深链/无来源)时不包 Hero。
  final String? heroTag;

  void _snack(BuildContext context, String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _report(BuildContext context, WidgetRef ref) async {
    final result = await showModalBottomSheet<({String type, String detail})>(
      context: context,
      isScrollControlled: true,
      builder: (context) => const ReportSheet(),
    );
    if (result == null) return;
    try {
      await ref.read(moderationRepositoryProvider).report(
          targetUserId: userId, type: result.type, detail: result.detail);
      if (context.mounted) _snack(context, '已收到举报,我们会尽快处理');
    } on ApiException catch (error) {
      if (context.mounted) _snack(context, error.message);
    }
  }

  Future<void> _block(BuildContext context, WidgetRef ref) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('拉黑这位用户?'),
        content: const Text('拉黑后你们将互相不可见,本机聊天记录会被清除'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('取消')),
          FilledButton(
            key: const Key('user.block.confirm'),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('拉黑'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await ref.read(moderationRepositoryProvider).block(userId);
    } on ApiException catch (error) {
      if (context.mounted) _snack(context, error.message);
      return;
    }
    // 黑名单列表是全局缓存的:拉黑后不失效,设置里再打开还是旧列表(2026-09-11 手测 bug)
    ref.invalidate(blockedUsersProvider);
    try {
      // 拉黑已生效,清本机会话只是收尾:失败不打断流程(对方消息已被 IM 黑名单拦)
      await ref.read(imClientProvider).deleteConversation('u$userId');
      await ref.read(conversationsProvider.notifier).reload();
    } catch (_) {}
    if (context.mounted) {
      _snack(context, '已拉黑');
      context.pop();
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final profile = ref.watch(userProfileProvider(userId));
    // 在线状态是公开信息(不依赖配对):与广场/动态详情同款写法
    ref.read(presenceProvider.notifier).track('user:$userId', [userId]);
    final online = ref.watch(presenceProvider)[userId]?.online ?? false;
    return Scaffold(
      body: profile.when(
        loading: () => const UserProfileSkeleton(),
        error: (error, _) => SafeArea(
          child: AppErrorView(
            message: apiMessageOf(error),
            retryKey: const Key('user.retry'),
            onRetry: () => ref.invalidate(userProfileProvider(userId)),
          ),
        ),
        data: (data) => _ProfileBody(
          profile: data,
          heroTag: heroTag,
          online: online,
          onBack: () => Navigator.of(context).maybePop(),
          onMore: (value) =>
              value == 'report' ? _report(context, ref) : _block(context, ref),
        ),
      ),
    );
  }
}

class _ProfileBody extends StatelessWidget {
  const _ProfileBody({
    required this.profile,
    required this.heroTag,
    required this.online,
    required this.onBack,
    required this.onMore,
  });

  final UserProfile profile;
  final String? heroTag;
  final bool online;
  final VoidCallback onBack;
  final ValueChanged<String> onMore;

  static const _topBarHeight = 52.0; // §5.2 二级页

  @override
  Widget build(BuildContext context) {
    final photos = profile.photos.map((photo) => photo.url).toList();
    return Stack(
      children: [
        ListView(
          padding: EdgeInsets.zero,
          children: [
            ProfilePhotoHeader(
              photoUrl: photos.isEmpty ? null : photos.first,
              nickname: profile.nickname,
              age: profile.age,
              city: profile.city,
              online: online,
              heroTag: heroTag,
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.pageH, AppSpacing.md, AppSpacing.pageH, AppSpacing.xxl),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  AppCard(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        _LabeledBlock(label: '个性签名', value: profile.bio),
                        if (profile.tags.isNotEmpty) ...[
                          const SizedBox(height: AppSpacing.lg),
                          // 纯标签用 _FieldLabel:不能用 _LabeledBlock(它会在空值时补「未填」)
                          _FieldLabel(label: '标签'),
                          const SizedBox(height: AppSpacing.sm),
                          Wrap(
                            spacing: AppSpacing.sm,
                            runSpacing: AppSpacing.sm,
                            children: [
                              for (final tag in profile.tags)
                                Container(
                                  padding: const EdgeInsets.symmetric(
                                      horizontal: AppSpacing.sm, vertical: 3),
                                  decoration: BoxDecoration(
                                    color: AppColors.divider,
                                    borderRadius: BorderRadius.circular(AppRadius.chip),
                                  ),
                                  child: Text(tag.name,
                                      style: AppText.micro
                                          .copyWith(color: AppColors.text1)),
                                ),
                            ],
                          ),
                        ],
                      ],
                    ),
                  ),
                  if (photos.isNotEmpty) ...[
                    const SizedBox(height: AppSpacing.md),
                    AppCard(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('相册',
                              style: AppText.caption.copyWith(color: AppColors.text2)),
                          const SizedBox(height: AppSpacing.md),
                          GridView.count(
                            shrinkWrap: true,
                            physics: const NeverScrollableScrollPhysics(),
                            crossAxisCount: 3,
                            mainAxisSpacing: AppSpacing.sm,
                            crossAxisSpacing: AppSpacing.sm,
                            children: [
                              for (var i = 0; i < photos.length; i++)
                                GestureDetector(
                                  key: Key('user.album.photo:$i'),
                                  onTap: () => openPhotoViewer(context,
                                      urls: photos, initialIndex: i),
                                  child: ClipRRect(
                                    borderRadius: BorderRadius.circular(AppRadius.image),
                                    child: Image.network(
                                      photos[i],
                                      fit: BoxFit.cover,
                                      errorBuilder: (c, e, s) => const ColoredBox(
                                        color: AppColors.divider,
                                        child: Icon(Icons.image_rounded,
                                            color: AppColors.text3),
                                      ),
                                    ),
                                  ),
                                ),
                            ],
                          ),
                        ],
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
        // 透明顶栏浮在照片上(附录 C.5)
        SafeArea(
          bottom: false,
          child: SizedBox(
            height: _topBarHeight,
            child: Row(
              children: [
                IconButton(
                  key: const Key('user.back'),
                  onPressed: onBack,
                  icon: const Icon(Icons.arrow_back_ios_new_rounded,
                      size: 22, color: Colors.white),
                ),
                const Spacer(),
                PopupMenuButton<String>(
                  key: const Key('user.more'),
                  icon: const Icon(Icons.more_horiz_rounded, size: 24, color: Colors.white),
                  onSelected: onMore,
                  itemBuilder: (context) => const [
                    PopupMenuItem(key: Key('user.report'), value: 'report', child: Text('举报')),
                    PopupMenuItem(key: Key('user.block'), value: 'block', child: Text('拉黑')),
                  ],
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

/// 白卡里的「标签 + 取值」块;取值为空显示「未填」。
class _LabeledBlock extends StatelessWidget {
  const _LabeledBlock({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _FieldLabel(label: label),
          const SizedBox(height: AppSpacing.xs),
          Text(value.isEmpty ? '未填' : value,
              style: AppText.body.copyWith(color: AppColors.text1)),
        ],
      );
}

/// 只有标签、内容自带渲染的块(如标签 chip 组):**不会**在空值时补「未填」。
class _FieldLabel extends StatelessWidget {
  const _FieldLabel({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) =>
      Text(label, style: AppText.caption.copyWith(color: AppColors.text2));
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd app
../flutter/bin/flutter.bat test test/features/profile/user_profile_page_test.dart test/features/square/square_page_test.dart test/features/square/post_detail_page_test.dart
```

Expected: 全部 PASS。

- [ ] **Step 5: 补新增用例**

在 `app/test/features/profile/user_profile_page_test.dart` 的 `pumpProfile` 之后追加参数支持与用例。把 `pumpProfile` 签名改为:

```dart
  Future<void> pumpProfile(WidgetTester tester, {int userId = 9, String? heroTag}) async {
```

并把路由 builder 改为:

```dart
        GoRoute(
          path: '/users/:id',
          builder: (context, state) => UserProfilePage(
            userId: int.parse(state.pathParameters['id']!),
            heroTag: state.extra as String?,
          ),
        ),
```

在 `main()` 末尾追加:

```dart
  testWidgets('照片头图:渲染昵称·年龄/城市,不显示「详细资料」标题', (tester) async {
    adapter.routes['GET /users/9'] = (options) => ok(publicProfileJson(
        nickname: '小红', age: 25, city: '上海'));
    await pumpProfile(tester);

    expect(find.text('小红,25'), findsOneWidget);
    expect(find.text('上海'), findsOneWidget);
    expect(find.text('详细资料'), findsNothing); // 标题已删(身份由头图承载)
    expect(find.byKey(const Key('user.back')), findsOneWidget);
  });

  testWidgets('无照片:头图走 person 占位且不渲染相册', (tester) async {
    adapter.routes['GET /users/9'] =
        (options) => ok(publicProfileJson(photos: const []));
    await pumpProfile(tester);

    expect(find.byIcon(Icons.person_rounded), findsOneWidget);
    expect(find.text('相册'), findsNothing);
    expect(find.byKey(const Key('user.album.photo:0')), findsNothing);
  });

  testWidgets('在线 → 头图显示呼吸点与「在线」', (tester) async {
    adapter.routes['GET /users/9'] = (options) => ok(publicProfileJson());
    adapter.routes['GET /presence'] = (options) => ok({
          'results': [
            {'user_id': 9, 'online': true, 'last_active_at': null}
          ]
        });
    await pumpProfile(tester);

    expect(find.text('在线'), findsOneWidget);
    expect(find.byKey(const Key('user.onlineDot')), findsOneWidget);
  });

  testWidgets('离线 → 不显示在线行', (tester) async {
    adapter.routes['GET /users/9'] = (options) => ok(publicProfileJson());
    adapter.routes['GET /presence'] = (options) => ok({
          'results': [
            {'user_id': 9, 'online': false, 'last_active_at': null}
          ]
        });
    await pumpProfile(tester);

    expect(find.text('在线'), findsNothing);
  });

  testWidgets('heroTag 由路由 extra 传入 → 头图包 Hero', (tester) async {
    adapter.routes['GET /users/9'] = (options) => ok(publicProfileJson());
    await pumpProfile(tester, heroTag: 'avatar-post-1');

    final hero = tester.widget<AvatarHero>(find.byType(AvatarHero));
    expect(hero.tag, 'avatar-post-1');
  });

  testWidgets('无 heroTag(深链)→ 不包 Hero', (tester) async {
    adapter.routes['GET /users/9'] = (options) => ok(publicProfileJson());
    await pumpProfile(tester);

    expect(find.byType(Hero), findsNothing);
  });

  testWidgets('点返回键 → 回到上一页', (tester) async {
    adapter.routes['GET /users/9'] = (options) => ok(publicProfileJson());
    await pumpProfile(tester);

    await tester.tap(find.byKey(const Key('user.back')));
    await tester.pumpAndSettle();
    expect(find.text('首页'), findsOneWidget);
  });
```

文件顶部 import 区加:

```dart
import 'package:chatapp_app/core/widgets/avatar_hero.dart';
```

**注意**:`user_profile_page_test.dart` 的 `pumpProfile` 用的 `ProviderContainer` 没有 override `presenceRefreshIntervalProvider`,而 `PresenceController` 的默认间隔是 45s —— `pumpAndSettle` 不会因为它超时(定时器不产生帧),但为稳妥在该文件的 `container` overrides 里加:

```dart
      presenceRefreshIntervalProvider.overrideWithValue(null),
```

(import `package:chatapp_app/features/presence/presence_controller.dart`。)

- [ ] **Step 6: 跑测试确认通过**

```bash
cd app
../flutter/bin/flutter.bat test test/features/profile/user_profile_page_test.dart
```

Expected: 13 用例 PASS(6 既有 + 7 新增)。

- [ ] **Step 7: 全量门槛 + 提交**

```bash
cd app
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
git add app/lib/features/profile/user_profile_page.dart app/test/features/profile/user_profile_page_test.dart app/test/features/square/square_page_test.dart app/test/features/square/post_detail_page_test.dart
git commit -m "$(cat <<'EOF'
feat(ui): 他人资料页改照片头图 + 透明顶栏 + 卡片化资料与相册 R12,接入在线状态

删「详细资料」标题(身份由头图承载),同步改广场/动态详情两处断言载体。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Hero 接入四处来源 + 路由 extra

**Files:**
- Modify: `app/lib/router.dart:43-47`(`/users/:id` 读 extra)
- Modify: `app/lib/features/square/widgets/post_card.dart`(加 `heroTag`)
- Modify: `app/lib/features/square/square_page.dart:129`
- Modify: `app/lib/features/square/post_detail_page.dart:108,136`(作者 + 评论)
- Modify: `app/lib/features/chat/chat_page.dart`(`_ChatHeader` 加头像 + Hero;`_openProfile` 传 extra)
- Test: `app/test/features/square/hero_transition_test.dart`(新)

**Interfaces:**
- Consumes: `AvatarHero`(T2)、`UserProfilePage.heroTag`(T7)
- Produces: tag 命名 `avatar-post-{postId}` / `avatar-comment-{commentId}` / `avatar-chat-{peerId}`

- [ ] **Step 1: 写失败测试**

创建 `app/test/features/square/hero_transition_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/avatar_hero.dart';
import 'package:chatapp_app/features/profile/user_profile_page.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

void main() {
  testWidgets('广场:头像 Hero tag 为 avatar-post-{id};跳资料页后 tag 一致', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /posts': (options) => ok(pageJson([
            postJson(id: 1, authorId: 9, nickname: 'Alice', text: '你好'),
          ])),
      'GET /users/9': (options) => ok(publicProfileJson(userId: 9, nickname: 'Alice')),
      'GET /presence': (options) => ok({'results': []}),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await tester.tap(navTab('广场'));
    await tester.pumpAndSettle();

    // 来源侧:头像被 AvatarHero 包住,tag 用来源自身 id(不是 userId)
    final source = tester.widget<AvatarHero>(
        find.ancestor(
            of: find.byKey(const Key('post.avatar.1')),
            matching: find.byType(AvatarHero)));
    expect(source.tag, 'avatar-post-1');

    await tester.tap(find.byKey(const Key('post.avatar.1')));
    await tester.pumpAndSettle();

    // 目标侧:同一 tag 落在资料页头图上(限定在目标页内查找——
    // 被 push 盖住的广场页仍在树里,全局 find 会撞到它自己的 AvatarHero)
    expect(find.byType(UserProfilePage), findsOneWidget);
    final target = tester.widget<AvatarHero>(find.descendant(
        of: find.byType(UserProfilePage), matching: find.byType(AvatarHero)));
    expect(target.tag, 'avatar-post-1');
  });

  testWidgets('广场:同作者两条动态 → tag 不重复(否则 Hero 抛重复 tag)', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /posts': (options) => ok(pageJson([
            postJson(id: 1, authorId: 9, nickname: 'Alice', text: '第一条'),
            postJson(id: 2, authorId: 9, nickname: 'Alice', text: '第二条'),
          ])),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await tester.tap(navTab('广场'));
    await tester.pumpAndSettle();

    // 两个 Hero tag 必须不同(用 userId 派生会撞,debug 下直接抛异常)
    final tags = tester
        .widgetList<AvatarHero>(find.byType(AvatarHero))
        .map((hero) => hero.tag)
        .toList();
    expect(tags.length, 2);
    expect(tags.toSet().length, tags.length);
    expect(tester.takeException(), isNull);
  });

  testWidgets('动态详情:作者与评论的头像 tag 各自独立', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /posts': (options) => ok(pageJson([
            postJson(id: 1, authorId: 9, nickname: 'Alice', text: '正文'),
          ])),
      'GET /posts/1': (options) =>
          ok(postJson(id: 1, authorId: 9, nickname: 'Alice', text: '正文')),
      'GET /posts/1/comments': (options) => ok(pageJson([
            commentJson(id: 5, authorId: 11, nickname: 'Bob', text: '好漂亮'),
          ])),
      'GET /presence': (options) => ok({'results': []}),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await tester.tap(navTab('广场'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('post.card.1')));
    await tester.pumpAndSettle();

    // 限定在详情页内:被盖住的广场页仍在树里,全局 find 会连它的一起算进来
    final tags = tester
        .widgetList<AvatarHero>(find.descendant(
            of: find.byType(PostDetailPage), matching: find.byType(AvatarHero)))
        .map((hero) => hero.tag)
        .toSet();
    expect(tags, containsAll(<String>['avatar-post-1', 'avatar-comment-5']));
    expect(tester.takeException(), isNull);
  });
}
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd app
../flutter/bin/flutter.bat test test/features/square/hero_transition_test.dart
```

Expected: FAIL —— 找不到 `AvatarHero`(尚未接入)。

- [ ] **Step 3: 路由读 extra**

`app/lib/router.dart` 第 43-47 行改为:

```dart
      GoRoute(
        path: '/users/:id',
        builder: (context, state) => UserProfilePage(
          userId: int.parse(state.pathParameters['id']!),
          heroTag: state.extra as String?,
        ),
      ),
```

- [ ] **Step 4: `PostCard` 加 `heroTag`**

`app/lib/features/square/widgets/post_card.dart`:

构造器加参数(在 `menuAction` 之后):

```dart
  /// Hero tag(附录 C.7);为 null(如广场列表)时不包 Hero。
  final String? heroTag;
```

并在构造函数参数表加 `this.heroTag,`。把第 50-57 行的头像 `GestureDetector` 包进 `AvatarHero`:

```dart
            AvatarHero(
              tag: heroTag,
              imageUrl: post.author.avatarUrl,
              child: GestureDetector(
                key: Key('post.avatar.${post.id}'),
                behavior: HitTestBehavior.opaque,
                // null(自己)= 空回调吞掉点击,不落到卡片的「进详情」
                onTap: onTapAuthor ?? () {},
                child: _Avatar(
                    url: post.author.avatarUrl, name: post.author.nickname, online: online),
              ),
            ),
```

顶部加 import:

```dart
import '../../../core/widgets/avatar_hero.dart';
```

- [ ] **Step 5: 广场与动态详情传 tag**

`app/lib/features/square/square_page.dart` 第 123-137 行的 `PostCard(...)`:

**列表页也要传 `heroTag`** —— tag 用 `postId` 派生(不是 `userId`),所以同一作者的多条动态各得一个不同 tag,**不会重复**;这正是 C.7 用来源 id 而不用 userId 的原因(第 2 条用例守住这一点)。同时把 tag 经 `extra` 传给目标页,两端才配得上:

```dart
                      return PostCard(
                        post: post,
                        heroTag: 'avatar-post-${post.id}',
                        isMine: post.author.userId == myId,
                        online: presenceById[post.author.userId]?.online == true,
                        onTapAuthor: post.author.userId == myId
                            ? null
                            : () => context.push('/users/${post.author.userId}',
                                extra: 'avatar-post-${post.id}'),
                        onToggleLike: () => _toggleLike(post),
                        onTap: () => context.push('/posts/${post.id}'),
                        onOpenImage: (i) =>
                            openPhotoViewer(context, urls: post.images, initialIndex: i),
                        menuAction: (action) => action == 'delete'
                            ? _deletePost(post)
                            : reportPostFromSheet(context, ref, post.id),
                      );
```

`app/lib/features/square/post_detail_page.dart` 第 102-115 行的 `PostCard(...)` 加 `heroTag: 'avatar-post-${data.id}',`,并把第 108 行与第 136 行的 push 都带上 extra:

```dart
                    onTapAuthor: data.author.userId == myId
                        ? null
                        : () => context.push('/users/${data.author.userId}',
                            extra: 'avatar-post-${data.id}'),
```

```dart
                            onTapAuthor: comment.author.userId == myId
                                ? null
                                : () => context.push('/users/${comment.author.userId}',
                                    extra: 'avatar-comment-${comment.id}'),
```

`_CommentTile` 加 `heroTag` 参数并包住头像 `GestureDetector`:

```dart
class _CommentTile extends StatelessWidget {
  const _CommentTile({required this.comment, this.onTapAuthor, this.heroTag});
  ...
  final String? heroTag;
```

```dart
          AvatarHero(
            tag: heroTag,
            imageUrl: comment.author.avatarUrl,
            child: GestureDetector(
              key: Key('post.comment.avatar.${comment.id}'),
              behavior: HitTestBehavior.opaque,
              onTap: onTapAuthor ?? () {},
              child: Container(
                ... 原样保留 ...
              ),
            ),
          ),
```

调用处加 `heroTag: 'avatar-comment-${comment.id}',`。

- [ ] **Step 6: 聊天页顶栏加头像 + Hero**

`app/lib/features/chat/chat_page.dart`:

`_openProfile` 改为带 extra:

```dart
  void _openProfile(BuildContext context, Map<String, MatchEntry> cache) {
    // 优先用 matches 缓存里的真实 id;缓存没有(如刚被清)就按 u9 → 9 兜底
    final userId =
        cache[widget.peerId]?.userId ?? int.tryParse(widget.peerId.replaceFirst('u', ''));
    if (userId == null) return;
    context.push('/users/$userId', extra: 'avatar-chat-${widget.peerId}');
  }
```

`_ChatHeader` 加 `avatarUrl` 与 `heroTag` 参数:

```dart
class _ChatHeader extends StatelessWidget {
  const _ChatHeader({
    required this.name,
    required this.presence,
    required this.onTapTitle,
    this.avatarUrl,
    this.heroTag,
  });

  final String name;
  final Presence? presence;
  final VoidCallback onTapTitle;
  final String? avatarUrl;
  final String? heroTag;
```

`build` 里把 `Row` 的 `children` 改为(保留 `chat.title` 覆盖头像 + 名字,既有「点名字进资料页」用例仍通过):

```dart
        children: [
          IconButton(
            key: const Key('chat.back'),
            onPressed: () => Navigator.of(context).maybePop(),
            icon: const Icon(Icons.arrow_back_ios_new_rounded,
                size: 22, color: AppColors.text1),
          ),
          Expanded(
            child: GestureDetector(
              key: const Key('chat.title'),
              behavior: HitTestBehavior.opaque,
              onTap: onTapTitle,
              child: Row(
                children: [
                  AvatarHero(
                    tag: heroTag,
                    imageUrl: avatarUrl,
                    child: AppAvatar(
                      imageUrl: avatarUrl,
                      size: 32,
                      fallbackText: name,
                    ),
                  ),
                  const SizedBox(width: AppSpacing.sm),
                  Expanded(
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Text(name,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: AppText.subtitle
                                .copyWith(fontSize: 17, color: AppColors.text1)),
                        if (statusLabel != null) ...[
                          const SizedBox(height: 1),
                          Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              if (online) ...[
                                const BreathingDot(
                                    key: Key('chat.onlineDot'),
                                    size: 8,
                                    borderColor: AppColors.bgPage),
                                const SizedBox(width: AppSpacing.xs),
                              ],
                              Text(statusLabel,
                                  style: AppText.micro.copyWith(color: AppColors.text2)),
                            ],
                          ),
                        ],
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
          // 与左侧返回键(48)等宽,保证「头像 + 名字」整块在屏幕上居中
          // (头像是 Expanded 内部的一部分,不参与这里的配平)
          const SizedBox(width: 48),
        ],
```

调用处(`build` 内 `_ChatHeader(...)`)加:

```dart
            avatarUrl: peerAvatarUrl,
            heroTag: 'avatar-chat-${widget.peerId}',
```

import 加:

```dart
import '../../core/widgets/app_avatar.dart';
import '../../core/widgets/avatar_hero.dart';
```

- [ ] **Step 7: 跑测试确认通过**

```bash
cd app
../flutter/bin/flutter.bat test test/features/square/ test/features/chat/ test/features/profile/
```

Expected: 全部 PASS(含新增 Hero 用例)。

- [ ] **Step 8: 全量门槛 + 提交**

```bash
cd app
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
git add app/lib/router.dart app/lib/features/square/ app/lib/features/chat/chat_page.dart app/test/features/square/ app/test/features/chat/chat_page_test.dart
git commit -m "$(cat <<'EOF'
feat(ui): Hero 转场接入四处来源(广场卡/详情作者/详情评论/聊天顶栏),tag 按来源自身 id 派生经路由 extra 传递

tag 不用 userId:同作者多卡会同屏重复,debug 下 Hero 直接抛异常。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: 门槛验证 + 打包上模拟器(手测准备)

**Files:** 无代码改动(产物 = 模拟器上的 release APK + 手测清单)

**Interfaces:**
- Consumes: 前 8 个任务全部产出

- [ ] **Step 1: 全量门槛**

```bash
cd app
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
```

Expected: analyze 零告警;全量用例绿(247 基线 + 本批新增)。

- [ ] **Step 2: 打 release 包(连测试服务器)**

```bash
cd app
../flutter/bin/flutter.bat build apk --release --dart-define=API_BASE=http://47.116.114.110/api/v1
```

- [ ] **Step 3: 装模拟器**

```bash
adb devices
adb -s emulator-5554 install -r app/build/app/outputs/flutter-apk/app-release.apk
```

- [ ] **Step 4: 备好手测数据**

```bash
cd chatapp
python manage.py seed_fake_users --count 20    # 幂等
```

- [ ] **Step 5: 汇报手测清单(用户亲测)**

- **我的页**:完整账号(身份卡 + 5 行,无完成度区);不完整账号(完成度环数字、「还差:…」、点「去完善」进引导页);点身份卡进编辑资料;三个入口行(我的动态/想找的人/设置)
- **他人资料页**:有照片(头图 + 叠字昵称·年龄/城市);无照片(person 占位);在线/离线两种叠字;相册 R12 点开大图左右滑;返回键;`⋯` 举报与拉黑(拉黑后确认返回上一页)
- **Hero 转场四处**:广场卡头像 → 资料页;动态详情作者头像 → 资料页;详情评论头像 → 资料页;聊天页顶栏头像 → 资料页。观察飞行是否顺滑、**图片有没有中途换图**
- **回归**:从发现卡滑到的人点聊天 → 顶栏头像与名字正常;消息页横滑条不受影响
- 系统「减弱动态效果」开启:无转场但功能正常
- 窄屏(360dp):头图叠字不截断;聊天顶栏名字不被头像挤没
- 封禁账号:整屏不受影响(回归)

- [ ] **Step 6: 待用户手测通过后收尾(另一步执行)**

用户确认观感后:更新 `CLAUDE.md` 里程碑(批次④交付 + 测试数 + 下一步改「⑤ 广场」)→ 提交 → `ui/batch4` 合回 `master`(ff)→ 删分支 → `git push origin master`。

---

## 计划自查记录

**Spec 覆盖**

| Spec 章节 | 落点 |
|---|---|
| §1 我的页(页壳/身份卡/资料组/入口组/加载/错误) | T4(骨架)+ T6 |
| §2 他人资料页(头图/叠字/透明顶栏/资料卡/相册/加载/错误/在线) | T4 + T5 + T7 |
| §3 Hero 体系(tag 派生/extra 传递/四处接入/shuttle/降级) | T2 + T8 |
| §4 新组件 5 个 | T2(`AvatarHero`)、T3(`CompletionRing`)、T4(两骨架)、T5(`ProfilePhotoHeader`) |
| §5 附录 C 回填 8 条 | T1 |
| 测试与验收:4 类既有断言更新 | T6(`my.card.identity` ×3 文件)、T7(`详细资料` ×2 文件、`ID:u7`) |
| 测试与验收:新增用例 | T2–T8 各带 |
| 门槛:analyze + 全量 test + 手测 | 每任务收尾 + T9 |

**类型/命名一致性**

- `AvatarHero({tag, imageUrl, child, fromRadius})` —— T2 定义,T5/T8 消费。
- `CompletionRing({done, total, size})` —— T3 定义,T6 消费。
- `ProfileSkeleton` / `UserProfileSkeleton` —— T4 定义,T6/T7 消费。
- `ProfilePhotoHeader({photoUrl, nickname, age, city, online, heroTag})` —— T5 定义,T7 消费。
- `UserProfilePage({userId, heroTag})` —— T7 定义,T8 路由消费。
- `PostCard.heroTag` —— T8 定义并消费。
- key:`my.card.identity` / `my.ring` / `my.goOnboarding`(T3/T6)、`user.back` / `user.onlineDot`(T5/T7)、`profile.skeleton` / `user.skeleton`(T4)。

**占位符扫描**:无 TBD/TODO;每个代码步骤都给了可直接粘贴的实现。

**自检抓到并已修正的 4 处缺陷**

1. **`_LabeledBlock` 会被误用于「标签」标题** —— 它空值补「未填」,而标签行下面是 chip 组、不是文本。拆出 `_FieldLabel`(纯标签,不补「未填」),T7 的标签块改用它。
2. **`AppColors.page` 不存在** —— T8 的 `_ChatHeader` 代码块里写错了 token(正确是 `AppColors.bgPage`)。已直接改对,并删掉多余的「注意」段落。
3. **T8 Step 5 自相矛盾** —— 先写「列表不传 heroTag」又写「改成列表传」,读起来像思考过程而不是指令。已重写为单一口径:**列表也传 `heroTag`**(tag 按 `postId` 派生,同作者多卡不重复),并给出完整可粘贴的 `PostCard(...)` 调用。
4. **T8 的 2 条用例是空壳**(只 `pumpAndSettle` 不断言)—— 已补成真实断言;并修正两处 finder 作用域 bug:被 push 盖住的页面仍在 widget 树里,全局 `find.byType(AvatarHero)` 会连来源页的一起找到,故一律用 `find.descendant(of: 目标页, ...)` 限定。

**已知风险**

- **`find.text('我的')` 双命中**:T6 给「我的」页加了大标题后,页面标题与底栏 tab 同名。既有用例一律走 `navTab('我的')`(descendant 限定),不受影响;但**新增用例若写裸 `find.text('我的')` 会双命中**,实现时用 `navTab`。
- **聊天页顶栏配平**:头像在 `Expanded` 内部,右侧占位与左侧返回键等宽(48)即可让「头像 + 名字」整块居中;窄屏(360dp)下名字可用宽度约 200dp,`maxLines: 1 + ellipsis` 兜底。
- **`AppAvatar` 在 `_ChatHeader` 里被 `AvatarHero` 包裹**:飞行中显示的是 shuttle(纯 `Image.network`),不是 `AppAvatar` 自身;无图账号(`avatarUrl == null`)时 shuttle 回退到 child,`fallbackText` 首字仍可见。
- **`post_detail_page_test` 的详情页同时有作者与评论两个 `AvatarHero`**:断言必须用 tag 集合,不能 `findsOneWidget`。
- **Hero 与 `pumpAndSettle`**:Hero 是有限动画(380ms),`pumpAndSettle` 可达终态;但若目标页含呼吸点(在线),仍须有限 `pump`(T7 新增用例已注意)。
