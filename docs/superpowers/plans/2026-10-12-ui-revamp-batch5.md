# UI 整改批次⑤:广场 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task(全局约定:superpowers 类任务一律内联执行,不派发子 agent)。Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按「心跳」规则整改广场 Tab、动态详情、我的动态三页,落地 §6.2 第二处 Hero 转场「动态卡 → 动态详情」(状态切换双保机制);278 既有测试适配后全绿 + analyze 零告警 + 模拟器手测。

**Architecture:** 纯前端视觉层迁移 + 一处交互机制:新组件 `CardHero`(`AvatarHero` 并列,处理 SDK 禁止 Hero 嵌套的约束);广场页用 `_cardHeroPostId` 状态在「头像 Hero 态 / 整卡 Hero 态」间切换;详情页经 `extra` 接收 `PostDetailArgs(heroTag, seed)`,provider 未加载时用 seed 渲染真卡,使 push 后下一帧末的 Hero 扫描能配对成飞。行为、provider、接口、路由路径零变化(已批准例外:我的动态空态新增「去发布」按钮;提示通道 SnackBar → AppToast)。

**Tech Stack:** Flutter 3.47(`../flutter/bin/flutter.bat`)、Riverpod、go_router、flutter_test(真实 provider + 假网络 `ScriptedAdapter` + 假 IM `FakeImClient`)。

**Spec:** `docs/superpowers/specs/2026-10-12-ui-revamp-batch5-design.md`(一切视觉细节以它 + 规则文档为准;§5 整卡 Hero 机制已经 SDK 核查修正)

## Global Constraints

- 所有视觉值走 token,**禁止新代码出现裸 hex / 裸字号 / 裸间距 / 裸圆角**(§1 铁律 3);确需新值先在组件内定义具名常量并注明附录条款。
- **SDK 硬约束(实现前已核查 `flutter/packages/flutter/lib/src/widgets/heroes.dart`)**:① Hero 不可嵌套(`:412` 运行时断言)——每张卡任意时刻至多一个 Hero;② Hero 扫描只在 push 后下一帧末进行一次(`:961-973`)——目标页首帧必须已有带相同 tag 的 Hero 才会飞。
- **Hero 互斥不变式**:广场普通态 `PostCard(heroTag: 'avatar-post-{id}', cardHeroTag: null)`;广场整卡态(仅其详情在栈顶期间)`PostCard(heroTag: null, cardHeroTag: 'card-post-{id}')`;详情页顶卡 `CardHero(tag: heroCardTag)` 内 `PostCard(heroTag: null)`(**必须 null**);我的动态/深链两端都无 Hero。
- **行为零变化**;已批准例外仅两处:① 我的动态空态新增「去发布」按钮;② 页面提示通道 SnackBar → AppToast(文案不变;删除确认 `AlertDialog` 不动,留⑥)。
- **无限动画纪律**:含 `AppSkeleton` / `BreathingDot` / `HeartRipple` 的用例**一律有限 pump**(`pumpFrames` 或显式 `pump`,禁 `pumpAndSettle`),见 `docs/pitfalls/testing.md`。
- **AppToast Timer 纪律**:`AppToast` 2s 自动消失的 Timer 会让 `testWidgets` 以 *A Timer is still pending* 失败——触发过 Toast 的用例收尾必须 `await drainToast(tester)`(Task 4 加进 harness)。
- 每任务收尾必须:全量 `../flutter/bin/flutter.bat analyze` 零告警 + 全量 `../flutter/bin/flutter.bat test` 绿 + 提交;所有 flutter/dart 命令 cwd = `app/`。
- **key 契约(不得改名/不得删)**:`square.fab`、`square.list`、`post.card.{id}`、`post.avatar.{id}`、`post.nickname.{id}`、`post.like.{id}`、`post.more.{id}`、`post.menu.delete`、`post.menu.report`、`post.image.{i}`、`post.comment.input`、`post.comment.send`、`post.comment.avatar.{id}`、`post.comment.nickname.{id}`、`post.delete.confirm`、`myPosts.list`、`my.row.posts`。
- **新增 key**:`square.compose`(空态发布按钮)、`square.skeleton`、`square.retry`、`post.back`、`post.skeleton`、`post.retry`、`myPosts.back`、`myPosts.skeleton`、`myPosts.retry`、`myPosts.compose`。
- **被删除的 key**:`square.refresh`(旧空态刷新按钮,无测试引用)。
- **被删除的文件**:`app/lib/features/presence/online_dot.dart`(Task 3,孤儿类,含违规裸 hex `#34C759`)。
- 提交信息中文,前缀沿用仓库风格(`feat(ui):` / `test(ui):` / `refactor(ui):` / `docs:`),尾行 `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`。
- 分支 `ui/batch5`(spec 提交 `926e8f4`、`0624899` 已在 master,切分支即含)。
- 本批**不动 `tokens.css`**;若实现中发现必须新增视觉 token,停下来先升规则文档再继续,并同步 web 侧跑双向比对。

---

### Task 0: 基线与分支

**Files:** 无代码改动

**Interfaces:**
- Produces: 分支 `ui/batch5`(后续全部任务在此分支提交)

- [ ] **Step 1: 建分支**

```bash
git checkout master && git merge --ff-only origin/master
git checkout -b ui/batch5
git log --oneline -3   # 应含 0624899(spec 修正)与 926e8f4(spec)
```

- [ ] **Step 2: 基线全绿**

```bash
cd app
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
```

Expected: analyze 零告警;278 全绿。红了先停下排查,别带病开工。

---

### Task 1: CardHero 组件(整卡 Hero 包装)

**Files:**
- Create: `app/lib/core/widgets/card_hero.dart`
- Test: `app/test/core/widgets/card_hero_test.dart`

**Interfaces:**
- Consumes: 无(与 `AvatarHero` 并列,不依赖它)
- Produces: `class CardHero extends StatelessWidget`,构造 `const CardHero({super.key, required this.tag, required this.child})`,`tag: String?`,`child: Widget`;`tag == null` 或 `MediaQuery.disableAnimationsOf(context)` 为真时直接返回 child,否则包 `Hero`(用框架默认 shuttle 与 `MaterialRectArcTween` 默认插值,不写 flightShuttleBuilder)。Task 7 的广场页/详情页依赖这个签名。

- [ ] **Step 1: 写失败测试**

```dart
// app/test/core/widgets/card_hero_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/card_hero.dart';

Widget _wrap(Widget child) => MaterialApp(home: Scaffold(body: child));

void main() {
  testWidgets('tag 为 null 时直接返回 child,不包 Hero', (tester) async {
    await tester.pumpWidget(_wrap(const CardHero(
      tag: null,
      child: SizedBox(width: 100, height: 50, child: Text('卡')),
    )));
    expect(find.byType(Hero), findsNothing);
    expect(find.text('卡'), findsOneWidget);
  });

  testWidgets('disableAnimations 时直接返回 child,不包 Hero', (tester) async {
    await tester.pumpWidget(_wrap(MediaQuery(
      data: const MediaQueryData(disableAnimations: true),
      child: const CardHero(
        tag: 'card-post-1',
        child: SizedBox(width: 100, height: 50, child: Text('卡')),
      ),
    )));
    expect(find.byType(Hero), findsNothing);
  });

  testWidgets('有 tag 时包 Hero,tag 一致', (tester) async {
    await tester.pumpWidget(_wrap(const CardHero(
      tag: 'card-post-1',
      child: SizedBox(width: 100, height: 50, child: Text('卡')),
    )));
    final hero = tester.widget<Hero>(find.byType(Hero));
    expect(hero.tag, 'card-post-1');
  });
}
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd app
../flutter/bin/flutter.bat test test/core/widgets/card_hero_test.dart
```

Expected: FAIL,`card_hero.dart` 不存在(编译错误)。

- [ ] **Step 3: 写实现**

```dart
// app/lib/core/widgets/card_hero.dart
import 'package:flutter/material.dart';

/// 整卡 Hero 包装(§6.2「动态卡 → 动态详情」,附录 D)。
///
/// 与 [AvatarHero] 并列:[tag] 为 null(我的动态/深链,无飞行源)或系统开启
/// 「减弱动态效果」时不包 Hero,静默降级;否则包 [Hero],shuttle 用框架默认
/// (飞行中渲染目标侧 child;两端同为 R20 白卡,无需圆角插值)。
///
/// 纪律(SDK `heroes.dart:412` 硬断言):Hero 的 child 及其后代不得再包含
/// Hero —— 整卡态下卡内头像 Hero 必须让位(调用方保证互斥,见 spec §5)。
class CardHero extends StatelessWidget {
  const CardHero({super.key, required this.tag, required this.child});

  final String? tag;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final heroTag = tag;
    if (heroTag == null || MediaQuery.disableAnimationsOf(context)) return child;
    return Hero(tag: heroTag, child: child);
  }
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
../flutter/bin/flutter.bat test test/core/widgets/card_hero_test.dart
```

Expected: 3 例 PASS。

- [ ] **Step 5: 全量门槛 + 提交**

```bash
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
git add app/lib/core/widgets/card_hero.dart app/test/core/widgets/card_hero_test.dart
git commit -m "feat(ui): CardHero 整卡 Hero 组件(禁嵌套/降级纪律内置)" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: PostImages 重构(1 张通栏 / 2–9 张 3 列)

**Files:**
- Modify: `app/lib/features/square/widgets/post_images.dart`(整文件重写,48 行)
- Test: `app/test/features/square/post_images_test.dart`(新建)

**Interfaces:**
- Consumes: `AppColors` / `AppRadius` / `AppSpacing`(token);`postJson(images: [...])` 造数
- Produces: `PostImages({required urls, onTap})` 对外签名不变,key `post.image.{i}` 不变;1 张 = 通栏固定高 **240**、R12;2–9 张 = 统一 3 列正方格、间距 8、R12;失败占位 `divider` 底 + `image_rounded`。Task 3 的 PostCard 与 Task 6 的详情页直接复用,无需再改。

- [ ] **Step 1: 写失败测试**

```dart
// app/test/features/square/post_images_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/square/widgets/post_images.dart';

// 测试面板宽 800;卡内(内外各 16+16)可用宽 736
Future<void> _pump(WidgetTester tester, int count) async {
  await tester.pumpWidget(MaterialApp(
    home: Scaffold(
      body: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: PostImages(urls: List.generate(count, (i) => 'http://x/$i.png')),
        ),
      ),
    ),
  ));
  await tester.pump(); // 触发假网络 400 → errorBuilder 占位
}

void main() {
  testWidgets('1 张:通栏大图,宽撑满、高 240、R12', (tester) async {
    await _pump(tester, 1);
    expect(find.byKey(const Key('post.image.0')), findsOneWidget);
    expect(find.byType(GridView), findsNothing); // 不走网格
    final size = tester.getSize(find.byKey(const Key('post.image.0')));
    expect(size.width, 736);
    expect(size.height, 240);
  });

  testWidgets('2 张(旧两列混排场景):同样 3 列网格,格宽 (736-16)/3', (tester) async {
    await _pump(tester, 2);
    expect(find.byType(GridView), findsOneWidget);
    final size = tester.getSize(find.byKey(const Key('post.image.0')));
    expect(size.width, closeTo((736 - 2 * 8.0) / 3, 0.5)); // 8 = AppSpacing.sm(间距 8,附录 D.2)
    expect(size.height, size.width); // AspectRatio 1 正方
  });

  testWidgets('5 张:3 列网格', (tester) async {
    await _pump(tester, 5);
    expect(find.byType(GridView), findsOneWidget);
    expect(find.byKey(const Key('post.image.4')), findsOneWidget);
  });

  testWidgets('图挂了:divider 底占位仍在(key 保留)', (tester) async {
    await _pump(tester, 1);
    expect(find.byIcon(Icons.image_rounded), findsOneWidget);
  });
}
```

- [ ] **Step 2: 跑测试确认失败**

```bash
../flutter/bin/flutter.bat test test/features/square/post_images_test.dart
```

Expected: FAIL(1 张现是 200×200、R6;2 张现是 2 列)。

- [ ] **Step 3: 重写实现**

```dart
// app/lib/features/square/widgets/post_images.dart 整文件替换
import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';

/// 动态配图(附录 D):1 张通栏大图(高 240);2–9 张统一 3 列正方格。
/// 假网络/断网时图挂 → divider 底内容占位(非空态)。
class PostImages extends StatelessWidget {
  const PostImages({super.key, required this.urls, this.onTap});

  final List<String> urls;
  final void Function(int index)? onTap;

  /// 1 张通栏的固定高(附录 D;屏宽自适应宽度)。
  static const _singleHeight = 240.0;

  @override
  Widget build(BuildContext context) {
    if (urls.isEmpty) return const SizedBox.shrink();
    if (urls.length == 1) {
      return GestureDetector(
        key: const Key('post.image.0'), // 单图分支补 key(原缺失,与网格分支对齐)
        onTap: () => onTap?.call(0),
        child: ClipRRect(
          borderRadius: BorderRadius.circular(AppRadius.image),
          child: SizedBox(
            width: double.infinity,
            height: _singleHeight,
            child: _image(0),
          ),
        ),
      );
    }
    return GridView.count(
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      crossAxisCount: 3,
      mainAxisSpacing: AppSpacing.sm,
      crossAxisSpacing: AppSpacing.sm,
      children: [
        for (var i = 0; i < urls.length; i++)
          GestureDetector(
            key: Key('post.image.$i'),
            onTap: () => onTap?.call(i),
            child: ClipRRect(
              borderRadius: BorderRadius.circular(AppRadius.image),
              child: _image(i),
            ),
          ),
      ],
    );
  }

  Widget _image(int index) => Image.network(
        urls[index],
        fit: BoxFit.cover,
        errorBuilder: (_, _, _) => const ColoredBox(
          color: AppColors.divider,
          child: Center(
            child: Icon(Icons.image_rounded, color: AppColors.text3),
          ),
        ),
      );
}
```

注意:key 在两个分支都挂 GestureDetector(`post.image.{i}` 命中不变;单图分支是**新增** key——原代码单图没有 key,测试既已断言就补齐);R12 挪进 ClipRRect。

- [ ] **Step 4: 跑测试确认通过**

```bash
../flutter/bin/flutter.bat test test/features/square/post_images_test.dart
```

Expected: 4 例 PASS。

- [ ] **Step 5: 全量门槛 + 提交**

```bash
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
git add app/lib/features/square/widgets/post_images.dart app/test/features/square/post_images_test.dart
git commit -m "feat(ui): 九宫格改版 — 1 张通栏 240 高、2-9 张统一 3 列 R12" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: PostCard 重构(圆头像/字阶/rounded 图标/点赞脉冲)+ 删除 OnlineDot

**Files:**
- Modify: `app/lib/features/square/widgets/post_card.dart`(整文件重写,222 行 → 约 200 行)
- Delete: `app/lib/features/presence/online_dot.dart`
- Modify: `app/test/features/square/square_page_test.dart`(import 与两处断言,见 Step 1)
- Test: `app/test/core/widgets/like_pulse_test.dart`(新建,独立测脉冲组件)

**Interfaces:**
- Consumes: `AppCard`、`AppAvatar(showOnlineDot:, fallbackText:)`、`AvatarHero`、`PostImages`(Task 2)、`AppText`/`AppColors`/`AppSpacing`/token
- Produces: `PostCard` 对外签名不变,新增可选参数 `cardHeroTag: String?`(Task 7 用;本任务先不传);内部删除 `_Avatar` 私有类;头像 Hero `fromRadius` 改 `AppRadius.full`(圆头像);点赞图标 `favorite_rounded`/`favorite_border_rounded`、评论 `mode_comment_rounded`(描边语义用同色 text3 表达,rounded 无 outlined 变体对);新增内部 `_PulseIcon`(脉冲封装)。全仓 `OnlineDot` 引用清零。

- [ ] **Step 1: 先改既有断言(让现状红)**

`app/test/features/square/square_page_test.dart` 适配(本任务只做 C 组——图标变体,与在线点 B 组——类型替换;A 组空态文案属 Task 4):

```dart
// 行 4 删除:
import 'package:chatapp_app/features/presence/online_dot.dart';
// 改为(顶部 import 区):
import 'package:chatapp_app/core/widgets/breathing_dot.dart';
// import 区补(AppColors 断言用):
import 'package:chatapp_app/core/theme/app_colors.dart';

// 「点赞乐观更新;失败回滚」用例(约 :59-64):
await tester.tap(find.byKey(const Key('post.like.1')));
await tester.pump();   // 乐观:马上变红
expect(tester.widget<Icon>(find.byIcon(Icons.favorite_rounded)).color,
    AppColors.brand);
await tester.pumpAndSettle();   // 请求失败 → 回滚
expect(find.byIcon(Icons.favorite_border_rounded), findsOneWidget);
await tester.pump(const Duration(seconds: 3)); // Task 4 起 AppToast 有 2s Timer,
                                // 先内联推时钟防 pending timer;Task 4 换 drainToast
// 文件顶部 import:support/harness.dart 已有
```

在线点用例(约 :152-183)整段替换断言部分:

```dart
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await pumpFrames(tester); // 呼吸点是无限动画,不能 pumpAndSettle
    await _openSquareWithFrames(tester); // 用下方 helper 替代 _openSquare

    expect(
        find.descendant(
            of: find.byKey(const Key('post.avatar.1')),
            matching: find.byType(BreathingDot)),
        findsOneWidget);
    expect(
        find.descendant(
            of: find.byKey(const Key('post.avatar.2')),
            matching: find.byType(BreathingDot)),
        findsNothing);
    // 查的正是两条动态的作者 id(不变)
    final request = adapter.log.lastWhere((r) => r.path == '/presence');
    expect(request.queryParameters['user_ids'], contains('9'));
    expect(request.queryParameters['user_ids'], contains('10'));
```

并在 `_openSquare` 旁加 helper(该文件 `_openSquare` 内是 `pumpAndSettle`,在线用例不能用):

```dart
Future<void> _openSquareWithFrames(WidgetTester tester) async {
  await tester.tap(navTab('广场'));
  await pumpFrames(tester);
}
```

注意:在线作者的呼吸点在 `pumpAndSettle` 下永不收敛,所以该用例从 `_openSquare`(settle)改走 `_openSquareWithFrames`;`_openSquare` 本身其他用例继续用(无在线点时 settle 安全)。

- [ ] **Step 2: 跑测试确认失败**

```bash
../flutter/bin/flutter.bat test test/features/square/square_page_test.dart
```

Expected: FAIL —— `favorite_rounded` 找不到(图标没换)、`BreathingDot` 找不到(头像没换)。

- [ ] **Step 3: 重写 PostCard**

```dart
// app/lib/features/square/widgets/post_card.dart 整文件替换
import 'package:flutter/material.dart';

import '../../../core/format.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_motion.dart';
import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/widgets/app_avatar.dart';
import '../../../core/widgets/app_card.dart';
import '../../../core/widgets/avatar_hero.dart';
import '../../../core/widgets/card_hero.dart';
import '../models.dart';
import 'post_images.dart';

/// 动态卡(附录 D):AppCard 白卡 R20;圆形头像(在线呼吸点)+ 昵称/时间/正文
/// + 九宫格 + 操作行(点赞带心跳脉冲);右上 ··· 菜单。
///
/// Hero 互斥(spec §5):[heroTag](头像)与 [cardHeroTag](整卡)至多传一个,
/// 同传在 debug 下触发 SDK 嵌套断言崩溃。
class PostCard extends StatelessWidget {
  const PostCard({
    super.key,
    required this.post,
    required this.isMine,
    this.online = false,
    this.onTapAuthor,
    this.onTap,
    this.onToggleLike,
    this.onOpenImage,
    this.menuAction,
    this.heroTag,
    this.cardHeroTag,
  });

  final Post post;
  final bool isMine;
  final bool online;
  final VoidCallback? onTapAuthor;
  final VoidCallback? onTap;
  final VoidCallback? onToggleLike;
  final void Function(int index)? onOpenImage;
  final void Function(String action)? menuAction;

  /// 头像 Hero tag(附录 C.7);null(我的动态/整卡态)不包。
  final String? heroTag;

  /// 整卡 Hero tag(附录 D);null(普通态)不包。与 [heroTag] 互斥。
  final String? cardHeroTag;

  @override
  Widget build(BuildContext context) {
    final card = AppCard(
      key: Key('post.card.${post.id}'),
      onTap: onTap,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          AvatarHero(
            tag: heroTag,
            imageUrl: post.author.avatarUrl,
            fromRadius: AppRadius.full,
            child: GestureDetector(
              key: Key('post.avatar.${post.id}'),
              behavior: HitTestBehavior.opaque,
              // null(自己/整卡态)= 空回调吞掉点击,不落到卡片的「进详情」
              onTap: onTapAuthor ?? () {},
              child: AppAvatar(
                imageUrl: post.author.avatarUrl,
                size: 40,
                showOnlineDot: online,
                fallbackText: post.author.nickname,
              ),
            ),
          ),
          const SizedBox(width: AppSpacing.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Align(
                        alignment: Alignment.centerLeft,
                        child: GestureDetector(
                          key: Key('post.nickname.${post.id}'),
                          behavior: HitTestBehavior.opaque,
                          onTap: onTapAuthor ?? () {},
                          child: Text(post.author.nickname,
                              style: AppText.subtitle
                                  .copyWith(color: AppColors.text1)),
                        ),
                      ),
                    ),
                    if (menuAction != null)
                      SizedBox(
                        width: 32,
                        height: 32,
                        child: PopupMenuButton<String>(
                          key: Key('post.more.${post.id}'),
                          padding: EdgeInsets.zero,
                          icon: const Icon(Icons.more_horiz_rounded,
                              size: 20, color: AppColors.text3),
                          onSelected: (value) => menuAction!(value),
                          itemBuilder: (context) => [
                            if (isMine)
                              const PopupMenuItem(
                                  key: Key('post.menu.delete'),
                                  value: 'delete',
                                  child: Text('删除'))
                            else
                              const PopupMenuItem(
                                  key: Key('post.menu.report'),
                                  value: 'report',
                                  child: Text('举报')),
                          ],
                        ),
                      ),
                  ],
                ),
                const SizedBox(height: 2),
                Text(formatPostTime(post.createdAt),
                    style: AppText.micro.copyWith(color: AppColors.text3)),
                if (post.text.isNotEmpty) ...[
                  const SizedBox(height: AppSpacing.xs),
                  Text(post.text, style: AppText.body.copyWith(color: AppColors.text1)),
                ],
                if (post.images.isNotEmpty) ...[
                  const SizedBox(height: AppSpacing.sm),
                  PostImages(urls: post.images, onTap: onOpenImage),
                ],
                const SizedBox(height: 2),
                Row(
                  children: [
                    _PulseIcon(
                      iconKey: Key('post.like.${post.id}'),
                      icon: post.likedByMe
                          ? Icons.favorite_rounded
                          : Icons.favorite_border_rounded,
                      color: post.likedByMe ? AppColors.brand : AppColors.text3,
                      count: post.likeCount,
                      pulse: !post.likedByMe, // didUpdateWidget 里只在「未赞→已赞」触发
                      onTap: onToggleLike,
                    ),
                    const SizedBox(width: AppSpacing.lg),
                    _ActionIcon(
                      icon: Icons.mode_comment_rounded,
                      color: AppColors.text3,
                      count: post.commentCount,
                      onTap: onTap,
                    ),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
    return CardHero(tag: cardHeroTag, child: card);
  }
}

/// 操作行图标 + 计数;[pulse] 由调用方按「本次点赞后是否已赞」传入。
class _ActionIcon extends StatelessWidget {
  const _ActionIcon({
    this.iconKey,
    required this.icon,
    required this.color,
    required this.count,
    this.onTap,
  });

  final Key? iconKey;
  final IconData icon;
  final Color color;
  final int count;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) => InkWell(
        key: iconKey,
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 2),
          child: Row(
            children: [
              Icon(icon, size: 20, color: color),
              const SizedBox(width: 4),
              Text('$count',
                  style: AppText.caption.copyWith(color: color)),
            ],
          ),
        ),
      );
}

/// 点赞心跳脉冲(§6.2 微交互):状态从未赞翻到已赞时 1→1.25→1(base)。
class _PulseIcon extends StatefulWidget {
  const _PulseIcon({
    this.iconKey,
    required this.icon,
    required this.color,
    required this.count,
    required this.pulse,
    this.onTap,
  });

  final Key? iconKey;
  final IconData icon;
  final Color color;
  final int count;
  final bool pulse;
  final VoidCallback? onTap;

  @override
  State<_PulseIcon> createState() => _PulseIconState();
}

class _PulseIconState extends State<_PulseIcon>
    with SingleTickerProviderStateMixin {
  late final AnimationController _c =
      AnimationController(vsync: this, duration: AppMotion.base);
  late final Animation<double> _scale = TweenSequence([
    TweenSequenceItem(tween: Tween(begin: 1.0, end: 1.25), weight: 0.5),
    TweenSequenceItem(tween: Tween(begin: 1.25, end: 1.0), weight: 0.5),
  ]).animate(CurvedAnimation(parent: _c, curve: AppMotion.easeOut));

  @override
  void didUpdateWidget(covariant _PulseIcon oldWidget) {
    super.didUpdateWidget(oldWidget);
    // 只在「未赞 → 已赞」翻带动效;取消赞不弹
    if (widget.pulse && !oldWidget.pulse) {
      if (MediaQuery.disableAnimationsOf(context)) return;
      _c.forward(from: 0);
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => InkWell(
        key: widget.iconKey,
        onTap: widget.onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 2),
          child: Row(
            children: [
              ScaleTransition(
                scale: _scale,
                child: Icon(widget.icon, size: 20, color: widget.color),
              ),
              const SizedBox(width: 4),
              Text('${widget.count}',
                  style: AppText.caption.copyWith(color: widget.color)),
            ],
          ),
        ),
      );
}
```

说明:`PostImages` 空列表分支(`SizedBox.shrink`)与 `_PulseIcon` 的引用关系:PostCard 只在 `post.images.isNotEmpty` 时渲染 PostImages;`_PulseIcon` 替代旧 `_ActionIcon` 的点赞位,评论位仍用 `_ActionIcon`(保留)。删除在线点导入与 `_Avatar` 私有类。

再删孤儿类:

```bash
git rm app/lib/features/presence/online_dot.dart
```

- [ ] **Step 4: 跑 square 测试确认通过**

```bash
../flutter/bin/flutter.bat test test/features/square/square_page_test.dart
../flutter/bin/flutter.bat test test/core
```

Expected: 全 PASS(含改过的点赞/在线点断言;详情页测试暂不动——`post_detail_page_test` 不 import OnlineDot,不受影响;hero_transition_test 不受影响)。

- [ ] **Step 5: 新增脉冲测试(TDD 补确认)**

```dart
// app/test/core/widgets/like_pulse_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/square/models.dart';
import 'package:chatapp_app/features/square/widgets/post_card.dart';

Post _post({required bool liked}) => Post(
      id: 1,
      author: const FeedAuthor(userId: 9, nickname: 'Alice'),
      text: '正文',
      images: const [],
      likeCount: liked ? 1 : 0,
      commentCount: 0,
      likedByMe: liked,
      createdAt: DateTime(2026, 9, 12, 20),
    );

void main() {
  testWidgets('点赞翻转触发心跳脉冲:scale 峰值 >1(有限 pump)', (tester) async {
    Post post = _post(liked: false);
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: StatefulBuilder(
          builder: (context, setState) => PostCard(
            post: post,
            isMine: false,
            onToggleLike: () => setState(() => post = _post(liked: !post.likedByMe)),
          ),
        ),
      ),
    ));
    await tester.pump();

    await tester.tap(find.byKey(const Key('post.like.1')));
    await tester.pump();                        // 乐观翻转 → 脉冲启动
    await tester.pump(const Duration(milliseconds: 80)); // 推到上升段

    // 只找点赞位的 ScaleTransition(评论位没有动画,find byType 可能多命中)
    final pulse = find.ancestor(
        of: find.byIcon(Icons.favorite_rounded),
        matching: find.byType(ScaleTransition));
    expect(pulse, findsOneWidget);
    final scale = tester.widget<ScaleTransition>(pulse.first).scale.value;
    expect(scale, greaterThan(1.0));

    await tester.pumpAndSettle();               // 脉冲收尾(有界)
  });

  testWidgets('取消赞不触发脉冲', (tester) async {
    Post post = _post(liked: true);
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: StatefulBuilder(
          builder: (context, setState) => PostCard(
            post: post,
            isMine: false,
            onToggleLike: () => setState(() => post = _post(liked: !post.likedByMe)),
          ),
        ),
      ),
    ));
    await tester.pump();

    await tester.tap(find.byKey(const Key('post.like.1')));
    await tester.pump(const Duration(milliseconds: 80));

    final pulse = find.ancestor(
        of: find.byIcon(Icons.favorite_border_rounded),
        matching: find.byType(ScaleTransition));
    expect(pulse, findsOneWidget);              // ScaleTransition 一直在(包着图标)
    final scale = tester.widget<ScaleTransition>(pulse.first).scale.value;
    expect(scale, 1.0);                         // 但没推过 1
  });
}
```

```bash
../flutter/bin/flutter.bat test test/core/widgets/like_pulse_test.dart
```

Expected: 2 例 PASS。

- [ ] **Step 6: 全量门槛 + 提交**

```bash
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
git add -A
git commit -m "feat(ui): 动态卡重构 — 圆形头像/字阶/rounded 图标/点赞心跳脉冲;删孤儿 OnlineDot" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: 广场页壳(大标题/骨架/空态/错误/AppToast/FAB)

**Files:**
- Create: `app/lib/features/square/widgets/square_skeleton.dart`
- Modify: `app/lib/features/square/square_page.dart`(整文件重写)
- Modify: `app/test/support/harness.dart`(加 `drainToast`)
- Modify: `app/lib/features/square/post_actions.dart`(SnackBar → AppToast)
- Modify: `app/test/features/square/square_page_test.dart`(空态文案 + 新用例)
- Modify: `app/test/features/shell/home_shell_test.dart`(空态文案)

**Interfaces:**
- Consumes: Task 3 的 `PostCard`、`AppEmptyState`/`HeartRipple`/`AppErrorView`/`AppSkeleton`/`AppToast`/`AppButton`、`apiMessageOf`
- Produces: `SquareSkeleton`(`const SquareSkeleton({super.key})`,根 key `square.skeleton`);`harness.dart` 新增 `Future<void> drainToast(WidgetTester tester) => tester.pump(const Duration(seconds: 3));`;`post_actions.dart` 的 `confirmDeletePost` / `reportPostFromSheet` 对外签名不变、内部提示走 `AppToast.show(context, message)`。Task 5 复用 `SquareSkeleton` 与 `drainToast`。

- [ ] **Step 1: 写失败测试**

`app/test/support/harness.dart` 尾部追加:

```dart
/// AppToast 的 2s 自动消失 Timer 会让 testWidgets 以 pending timer 失败:
/// 触发过 Toast 的用例收尾调用,把假时钟推过超时点。
Future<void> drainToast(WidgetTester tester) =>
    tester.pump(const Duration(seconds: 3));
```

`square_page_test.dart` 空态用例替换(A 组):

```dart
  testWidgets('空态:涟漪 + 文案 + 发布按钮,点按钮进发布页', (tester) async {
    final adapter = _adapter(pageJson([]));
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await pumpFrames(tester); // HeartRipple 无限动画,禁 settle
    await tester.tap(navTab('广场'));
    await pumpFrames(tester);

    expect(find.text('广场'), findsNWidgets(2)); // 底栏 tab + 页内大标题
    expect(find.text('还没有动态'), findsOneWidget);
    expect(find.text('发一条,让大家认识你'), findsOneWidget);

    await tester.tap(find.byKey(const Key('square.compose')));
    await pumpFrames(tester);
    expect(find.text('发布动态'), findsOneWidget); // 发布页 AppBar 标题(⑥才改)
  });
```

home_shell_test.dart:35:

```dart
    await tester.tap(navTab('广场'));
    await pumpFrames(tester);   // 空态涟漪无限动画(原 pumpAndSettle)
    expect(find.text('还没有动态'), findsOneWidget);
```

举报用例(square_page_test:67-87)断言后补收尾(AppToast timer):

```dart
    expect(find.text('已收到举报,我们会尽快处理'), findsOneWidget);
    await drainToast(tester);   // Toast Timer 收尾,否则 pending timer 报错
```

新增错误重试用例:

```dart
  testWidgets('加载失败 → AppErrorView,square.retry 重试成功', (tester) async {
    final adapter = _adapter(pageJson([]));
    adapter.routes['GET /posts'] = offline;
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await tester.tap(navTab('广场'));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('square.retry')), findsOneWidget);

    adapter.routes['GET /posts'] =
        (options) => ok(pageJson([postJson(id: 1, text: '恢复')]));
    await tester.tap(find.byKey(const Key('square.retry')));
    await tester.pumpAndSettle();
    expect(find.text('恢复'), findsOneWidget);
  });
```

新增 FAB 断言(并进首个「广场流渲染卡片」用例尾部):

```dart
    expect(find.byKey(const Key('square.fab')), findsOneWidget);
```

- [ ] **Step 2: 跑测试确认失败**

```bash
../flutter/bin/flutter.bat test test/features/square/square_page_test.dart test/features/shell/home_shell_test.dart
```

Expected: FAIL(文案仍旧、`square.compose`/`square.retry` 不存在)。

- [ ] **Step 3: 写 SquareSkeleton**

```dart
// app/lib/features/square/widgets/square_skeleton.dart
import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/widgets/app_skeleton.dart';

/// 广场/我的动态加载骨架(附录 D):3 张卡骨架 — 圆头像 + 两条文字 + 图块 + 操作行。
/// 呼吸动画为无限循环 — 可见它的测试只用有限 pump。
class SquareSkeleton extends StatelessWidget {
  const SquareSkeleton({super.key});

  @override
  Widget build(BuildContext context) => Column(
        key: key ?? const Key('square.skeleton'),
        children: [
          for (var i = 0; i < 3; i++) ...[
            if (i > 0) const SizedBox(height: AppSpacing.cardGap),
            Container(
              padding: const EdgeInsets.all(AppSpacing.lg),
              decoration: BoxDecoration(
                color: AppColors.bgCard,
                borderRadius: BorderRadius.circular(AppRadius.card),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      const AppSkeleton(
                          width: 40, height: 40, radius: AppRadius.full),
                      const SizedBox(width: AppSpacing.md),
                      Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          AppSkeleton(width: 120, height: 14),
                          const SizedBox(height: AppSpacing.xs),
                          AppSkeleton(width: 72, height: 12),
                        ],
                      ),
                    ],
                  ),
                  const SizedBox(height: AppSpacing.md),
                  const AppSkeleton(width: double.infinity, height: 14),
                  const SizedBox(height: AppSpacing.sm),
                  const AppSkeleton(width: 220, height: 14),
                  const SizedBox(height: AppSpacing.md),
                  const AppSkeleton(
                      width: double.infinity, height: 120, radius: AppRadius.image),
                  const SizedBox(height: AppSpacing.md),
                  const AppSkeleton(width: 140, height: 16),
                ],
              ),
            ),
          ],
        ],
      );
}
```

- [ ] **Step 4: 重写广场页**

```dart
// app/lib/features/square/square_page.dart 整文件替换
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_gradients.dart';
import '../../core/theme/app_shadows.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_button.dart';
import '../../core/widgets/app_empty_state.dart';
import '../../core/widgets/app_error_view.dart';
import '../../core/widgets/app_toast.dart';
import '../../core/widgets/heart_ripple.dart';
import '../chat/widgets/photo_viewer.dart';
import '../presence/presence_controller.dart';
import '../profile/profile_controller.dart';
import 'feed_repository.dart';
import 'models.dart';
import 'post_actions.dart';
import 'post_detail_args.dart';
import 'square_controller.dart';
import 'widgets/post_card.dart';
import 'widgets/square_skeleton.dart';

/// 广场 Tab(附录 D):大标题页壳 + 白卡流 + 渐变 FAB。
class SquarePage extends ConsumerStatefulWidget {
  const SquarePage({super.key});

  @override
  ConsumerState<SquarePage> createState() => _SquarePageState();
}

class _SquarePageState extends ConsumerState<SquarePage> {
  final _scroll = ScrollController();

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      if (_scroll.position.extentAfter < 300) {
        ref.read(squareProvider.notifier).loadMore();
      }
    });
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _toggleLike(Post post) async {
    try {
      await ref.read(squareProvider.notifier).toggleLike(post);
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    }
  }

  Future<void> _deletePost(Post post) async {
    final confirmed = await confirmDeletePost(context);
    if (!confirmed || !mounted) return;
    try {
      await ref.read(feedRepositoryProvider).deletePost(post.id);
      await ref.read(squareProvider.notifier).reload();
      ref.invalidate(myPostsProvider);
      if (mounted) AppToast.show(context, '已删除');
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final posts = ref.watch(squareProvider);
    final presenceById = ref.watch(presenceProvider);
    final myId = ref.watch(profileProvider).value?.userId;
    return Scaffold(
      backgroundColor: AppColors.bgPage,
      // FAB 上移 84:默认 endFloat 会压在悬浮胶囊底栏(64+10)上(附录 D)
      floatingActionButtonLocation: FloatingActionButtonLocation.endFloat,
      floatingActionButton: Padding(
        padding: const EdgeInsets.only(bottom: 84),
        child: _ComposeFab(
          onTap: () => context.push('/posts/compose'),
        ),
      ),
      body: SafeArea(
        bottom: false,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.pageH, AppSpacing.lg, AppSpacing.pageH, AppSpacing.md),
              child: Text('广场', style: AppText.display.copyWith(color: AppColors.text1)),
            ),
            Expanded(
              child: posts.when(
                loading: () => const Padding(
                  padding: EdgeInsets.symmetric(horizontal: AppSpacing.pageH),
                  child: SquareSkeleton(),
                ),
                error: (error, _) => AppErrorView(
                  message: apiMessageOf(error),
                  retryKey: const Key('square.retry'),
                  onRetry: () => ref.invalidate(squareProvider),
                ),
                data: (items) {
                  ref.read(presenceProvider.notifier).track(
                      'square', [for (final post in items) post.author.userId]);
                  return items.isEmpty
                      ? Center(
                          child: AppEmptyState(
                            mark: const HeartRipple(),
                            title: '还没有动态',
                            description: '发一条,让大家认识你',
                            action: AppButton(
                              key: const Key('square.compose'),
                              label: '发布第一条',
                              variant: AppButtonVariant.secondary,
                              onPressed: () => context.push('/posts/compose'),
                            ),
                          ),
                        )
                      : RefreshIndicator(
                          backgroundColor: AppColors.bgCard,
                          color: AppColors.brand,
                          onRefresh: () =>
                              ref.read(squareProvider.notifier).reload(),
                          child: ListView.separated(
                            key: const Key('square.list'),
                            controller: _scroll,
                            padding: const EdgeInsets.fromLTRB(
                                AppSpacing.pageH, AppSpacing.xs, AppSpacing.pageH, 96),
                            itemCount: items.length,
                            separatorBuilder: (_, _) =>
                                const SizedBox(height: AppSpacing.cardGap),
                            itemBuilder: (context, index) {
                              final post = items[index];
                              return PostCard(
                                post: post,
                                isMine: post.author.userId == myId,
                                online:
                                    presenceById[post.author.userId]?.online == true,
                                onTapAuthor: post.author.userId == myId
                                    ? null
                                    : () => context.push('/users/${post.author.userId}',
                                        extra: 'avatar-post-${post.id}'),
                                onToggleLike: () => _toggleLike(post),
                                onTap: () =>
                                    context.push('/posts/${post.id}'),
                                onOpenImage: (i) => openPhotoViewer(context,
                                    urls: post.images, initialIndex: i),
                                menuAction: (action) => action == 'delete'
                                    ? _deletePost(post)
                                    : reportPostFromSheet(context, ref, post.id),
                              );
                            },
                          ),
                        );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// 渐变圆钮 FAB(附录 D):56 圆 + gradientHeart + 主按钮阴影。
class _ComposeFab extends StatelessWidget {
  const _ComposeFab({required this.onTap});

  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Container(
        key: const Key('square.fab'),
        width: 56,
        height: 56,
        decoration: const BoxDecoration(
          shape: BoxShape.circle,
          gradient: AppGradients.heart,
          boxShadow: AppShadows.primaryButton,
        ),
        child: Material(
          color: Colors.transparent,
          child: InkWell(
            customBorder: const CircleBorder(),
            onTap: onTap,
            child: const Icon(Icons.add_rounded, size: 24, color: Colors.white),
          ),
        ),
      );
}
```

`post_actions.dart` 的 `show` 闭包替换(AppToast 化,签名/文案不变):

```dart
  if (result == null || !context.mounted) return;
  void show(String message) => AppToast.show(context, message);
```

(import 区补 `../../core/widgets/app_toast.dart`,删掉 `ScaffoldMessenger` 相关。)

- [ ] **Step 5: 跑测试确认通过**

```bash
../flutter/bin/flutter.bat test test/features/square/square_page_test.dart test/features/shell/home_shell_test.dart
```

Expected: 全 PASS。若「自己的动态点头像不打开资料页」(原 :136)失败:它用 `pumpAndSettle` + 数据页(无在线点)应该仍绿;若有「教练卡/底部溢出」报错,给列表 `padding.bottom` 保持 96 不变即可,报「A Timer is still pending」时检查是否漏了 `drainToast`。

- [ ] **Step 6: 全量门槛 + 提交**

```bash
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
git add -A
git commit -m "feat(ui): 广场页壳改版 — 大标题/涟漪空态/骨架/错误重试/渐变 FAB/AppToast" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 5: 我的动态页(顶栏/空态按钮/骨架/错误)

**Files:**
- Modify: `app/lib/features/square/my_posts_page.dart`(整文件重写,92 行)
- Modify: `app/test/features/square/my_posts_page_test.dart`(空态用例补按钮断言 + 新用例)

**Interfaces:**
- Consumes: Task 3 `PostCard`(heroTag 恒 null)、Task 4 `SquareSkeleton`/`drainToast`、`AppErrorView`/`AppToast`/`AppButton`
- Produces: 页面级改动,无对外接口。返回键 key `myPosts.back`(Navigator.maybePop)。

- [ ] **Step 1: 写失败测试**

`my_posts_page_test.dart` 空态用例替换:

```dart
  testWidgets('空列表:提示 + 去发布按钮进发布页', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson(nickname: '小明')),
      'GET /posts': (options) => ok(pageJson([])),
      'GET /posts/mine': (options) => ok(pageJson([])),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await tester.tap(navTab('我的'));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('my.row.posts')));
    await tester.pumpAndSettle();
    expect(find.text('还没发过动态'), findsOneWidget);

    await tester.tap(find.byKey(const Key('myPosts.compose')));
    await tester.pumpAndSettle();
    expect(find.text('发布动态'), findsOneWidget);
  });

  testWidgets('顶栏:标题与返回键存在', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson(nickname: '小明')),
      'GET /posts': (options) => ok(pageJson([])),
      'GET /posts/mine': (options) => ok(pageJson([
            postJson(id: 7, authorId: 7, nickname: '小明', text: '我发的'),
          ])),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await tester.tap(navTab('我的'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('my.row.posts')));
    await tester.pumpAndSettle();

    expect(find.text('我的动态'), findsOneWidget);
    expect(find.byKey(const Key('myPosts.back')), findsOneWidget);
  });
```

删除用例(原第一个)尾部补:

```dart
    expect(find.text('我发的'), findsNothing);
    await drainToast(tester);   // 删除成功弹 AppToast「已删除」
```

- [ ] **Step 2: 跑测试确认失败**

```bash
../flutter/bin/flutter.bat test test/features/square/my_posts_page_test.dart
```

Expected: FAIL(`myPosts.compose`/`myPosts.back` 不存在)。

- [ ] **Step 3: 重写页面**

```dart
// app/lib/features/square/my_posts_page.dart 整文件替换
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_button.dart';
import '../../core/widgets/app_empty_state.dart';
import '../../core/widgets/app_error_view.dart';
import '../../core/widgets/app_toast.dart';
import '../chat/widgets/photo_viewer.dart';
import 'models.dart';
import 'post_actions.dart';
import 'square_controller.dart';
import 'widgets/post_card.dart';
import 'widgets/square_skeleton.dart';

/// 我的动态(附录 D):二级页顶栏 + 复用动态卡(不参与 Hero)。
class MyPostsPage extends ConsumerStatefulWidget {
  const MyPostsPage({super.key});

  @override
  ConsumerState<MyPostsPage> createState() => _MyPostsPageState();
}

class _MyPostsPageState extends ConsumerState<MyPostsPage> {
  final _scroll = ScrollController();

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      if (_scroll.position.extentAfter < 300) {
        ref.read(myPostsProvider.notifier).loadMore();
      }
    });
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _deletePost(Post post) async {
    final confirmed = await confirmDeletePost(context);
    if (!confirmed || !mounted) return;
    try {
      await ref.read(myPostsProvider.notifier).remove(post.id);
      ref.invalidate(squareProvider);
      if (mounted) AppToast.show(context, '已删除');
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final posts = ref.watch(myPostsProvider);
    return Scaffold(
      backgroundColor: AppColors.bgPage,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            _SubPageBar(
              title: '我的动态',
              backKey: const Key('myPosts.back'),
            ),
            Expanded(
              child: posts.when(
                loading: () => const Padding(
                  padding: EdgeInsets.symmetric(horizontal: AppSpacing.pageH),
                  child: SquareSkeleton(key: Key('myPosts.skeleton')),
                ),
                error: (error, _) => AppErrorView(
                  message: apiMessageOf(error),
                  retryKey: const Key('myPosts.retry'),
                  onRetry: () => ref.invalidate(myPostsProvider),
                ),
                data: (items) => items.isEmpty
                    ? Center(
                        child: AppEmptyState(
                          emoji: '📝',
                          title: '还没发过动态',
                          description: '第一句想说的话,发在广场',
                          action: AppButton(
                            key: const Key('myPosts.compose'),
                            label: '去发布',
                            variant: AppButtonVariant.secondary,
                            onPressed: () => context.push('/posts/compose'),
                          ),
                        ),
                      )
                    : ListView.separated(
                        key: const Key('myPosts.list'),
                        controller: _scroll,
                        padding: const EdgeInsets.fromLTRB(AppSpacing.pageH,
                            AppSpacing.xs, AppSpacing.pageH, AppSpacing.xxl),
                        itemCount: items.length,
                        separatorBuilder: (_, _) =>
                            const SizedBox(height: AppSpacing.cardGap),
                        itemBuilder: (context, index) {
                          final post = items[index];
                          return PostCard(
                            post: post,
                            isMine: true,
                            // 从我的页进入无飞行源:不参与任何 Hero(附录 C.7)
                            onTap: () => context.push('/posts/${post.id}'),
                            onOpenImage: (i) => openPhotoViewer(context,
                                urls: post.images, initialIndex: i),
                            menuAction: (action) => action == 'delete'
                                ? _deletePost(post)
                                : reportPostFromSheet(context, ref, post.id),
                          );
                        },
                      ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// 二级页顶栏(§5.2):高 52,返回 + 居中标题(右侧等宽占位保持标题居中)。
class _SubPageBar extends StatelessWidget {
  const _SubPageBar({
    required this.title,
    required this.backKey,
  });

  final String title;
  final Key backKey;

  static const _height = 52.0;

  @override
  Widget build(BuildContext context) => SizedBox(
        height: _height,
        child: Stack(
          alignment: Alignment.center,
          children: [
            Text(title,
                style: AppText.subtitle.copyWith(
                    fontSize: 17, color: AppColors.text1)), // 17/w600(§5.2)
            Positioned(
              left: 0,
              top: 0,
              bottom: 0,
              child: IconButton(
                key: backKey,
                onPressed: () => Navigator.of(context).maybePop(),
                icon: const Icon(Icons.arrow_back_ios_new_rounded,
                    size: 22, color: AppColors.text1),
              ),
            ),
          ],
        ),
      );
}
```

`_SubPageBar` 是本页私有实现;Task 6 的详情页会复制同款顶栏(两页各自私有,不抽共享组件——两处共 20 行,避免过早抽象)。

- [ ] **Step 4: 跑测试确认通过**

```bash
../flutter/bin/flutter.bat test test/features/square/my_posts_page_test.dart
```

Expected: 全 PASS(删除用例的行消失断言不变)。

- [ ] **Step 5: 全量门槛 + 提交**

```bash
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
git add -A
git commit -m "feat(ui): 我的动态页改版 — 顶栏/空态发布按钮/骨架/错误/AppToast" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 6: 动态详情页改版(顶栏/评论/输入栏/骨架;暂不接 Hero)

**Files:**
- Create: `app/lib/features/square/widgets/post_detail_skeleton.dart`
- Modify: `app/lib/features/square/post_detail_page.dart`(整文件重写,264 行)
- Modify: `app/test/features/square/post_detail_page_test.dart`(补标题/返回键断言)

**Interfaces:**
- Consumes: Task 3 `PostCard`、Task 2 `PostImages`(卡内)、`AppAvatar`/`AppText`/token、`AppSkeleton`
- Produces: `PostDetailPage({required postId})` 签名**本任务不变**;Task 7 会加可选参数 `args`。页面内部:自绘顶栏(key `post.back`)、评论区(`post.comment.avatar.{id}` 圆形 28)、输入栏(高 44,R16 聚焦 1.5 brand + 光晕)、`PostDetailSkeleton`(key `post.skeleton`)、错误 `AppErrorView`(key `post.retry`)。

- [ ] **Step 1: 写失败测试**

`post_detail_page_test.dart` 首个用例后追加:

```dart
  testWidgets('顶栏:标题居中 + 返回键存在', (tester) async {
    final adapter = ScriptedAdapter({
      'GET /posts/1': (options) =>
          ok(postJson(id: 1, nickname: 'Alice', text: '正文')),
      'GET /posts/1/comments': (options) => ok(pageJson([])),
    });
    await pumpDetail(tester, adapter, postId: 1);
    await tester.pumpAndSettle();

    expect(find.text('动态详情'), findsOneWidget);
    expect(find.byKey(const Key('post.back')), findsOneWidget);
  });

  testWidgets('空评论:emoji 空态', (tester) async {
    final adapter = ScriptedAdapter({
      'GET /posts/1': (options) =>
          ok(postJson(id: 1, nickname: 'Alice', text: '正文')),
      'GET /posts/1/comments': (options) => ok(pageJson([])),
    });
    await pumpDetail(tester, adapter, postId: 1);
    await tester.pumpAndSettle();

    expect(find.text('还没有评论'), findsOneWidget);
    expect(find.text('来抢沙发'), findsOneWidget);
  });
```

- [ ] **Step 2: 跑测试确认失败**

```bash
../flutter/bin/flutter.bat test test/features/square/post_detail_page_test.dart
```

Expected: 新增 2 例 FAIL(无 `post.back` / 无空态文案)。

- [ ] **Step 3: 写 PostDetailSkeleton**

```dart
// app/lib/features/square/widgets/post_detail_skeleton.dart
import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/widgets/app_skeleton.dart';

/// 动态详情加载骨架(附录 D):1 张卡骨架 + 2 条评论行骨架。
class PostDetailSkeleton extends StatelessWidget {
  const PostDetailSkeleton({super.key});

  @override
  Widget build(BuildContext context) => Column(
        key: key ?? const Key('post.skeleton'),
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.all(AppSpacing.lg),
            decoration: BoxDecoration(
              color: AppColors.bgCard,
              borderRadius: BorderRadius.circular(AppRadius.card),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const AppSkeleton(width: 40, height: 40, radius: AppRadius.full),
                    const SizedBox(width: AppSpacing.md),
                    AppSkeleton(width: 120, height: 14),
                  ],
                ),
                const SizedBox(height: AppSpacing.md),
                AppSkeleton(width: double.infinity, height: 14),
                const SizedBox(height: AppSpacing.sm),
                AppSkeleton(width: 240, height: 14),
              ],
            ),
          ),
          const SizedBox(height: AppSpacing.lg),
          for (var i = 0; i < 2; i++) ...[
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.pageH),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const AppSkeleton(width: 28, height: 28, radius: AppRadius.full),
                  const SizedBox(width: AppSpacing.sm),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        AppSkeleton(width: 96, height: 12),
                        const SizedBox(height: AppSpacing.xs),
                        AppSkeleton(width: 200, height: 13),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: AppSpacing.lg),
          ],
        ],
      );
}
```

- [ ] **Step 4: 重写详情页**

```dart
// app/lib/features/square/post_detail_page.dart 整文件替换
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/format.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_radius.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_avatar.dart';
import '../../core/widgets/app_empty_state.dart';
import '../../core/widgets/app_error_view.dart';
import '../../core/widgets/app_toast.dart';
import '../../core/widgets/avatar_hero.dart';
import '../chat/widgets/photo_viewer.dart';
import '../presence/presence_controller.dart';
import '../profile/profile_controller.dart';
import 'feed_repository.dart';
import 'models.dart';
import 'post_actions.dart';
import 'post_detail_controller.dart';
import 'square_controller.dart';
import 'widgets/post_card.dart';
import 'widgets/post_detail_skeleton.dart';

/// 动态详情(附录 D):自绘顶栏 + 动态卡 + 评论流 + 底部紧凑输入栏(44)。
class PostDetailPage extends ConsumerStatefulWidget {
  const PostDetailPage({super.key, required this.postId});

  final int postId;

  @override
  ConsumerState<PostDetailPage> createState() => _PostDetailPageState();
}

class _PostDetailPageState extends ConsumerState<PostDetailPage> {
  final _input = TextEditingController();
  final _focus = FocusNode();
  bool _sending = false;

  @override
  void dispose() {
    _input.dispose();
    _focus.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final text = _input.text.trim();
    if (text.isEmpty) return;
    setState(() => _sending = true);
    try {
      await ref.read(commentsProvider(widget.postId).notifier).send(text);
      _input.clear();
      ref.invalidate(commentsProvider(widget.postId));      // 评论列表刷新
      ref.invalidate(postDetailProvider(widget.postId));    // 评论数 +1
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  Future<void> _toggleLike() async {
    try {
      await ref.read(postDetailProvider(widget.postId).notifier).toggleLike();
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    }
  }

  Future<void> _deletePost() async {
    final confirmed = await confirmDeletePost(context);
    if (!confirmed || !mounted) return;
    try {
      await ref.read(feedRepositoryProvider).deletePost(widget.postId);
      ref.invalidate(squareProvider);
      ref.invalidate(myPostsProvider);
      if (mounted) context.pop();
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final post = ref.watch(postDetailProvider(widget.postId));
    final comments = ref.watch(commentsProvider(widget.postId));
    final presenceById = ref.watch(presenceProvider);
    final myId = ref.watch(profileProvider).value?.userId;
    return Scaffold(
      backgroundColor: AppColors.bgPage,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            _DetailBar(
              backKey: const Key('post.back'),
            ),
            Expanded(
              child: post.when(
                loading: () => const Padding(
                  padding: EdgeInsets.symmetric(horizontal: AppSpacing.pageH),
                  child: PostDetailSkeleton(),
                ),
                error: (error, _) => AppErrorView(
                  message: apiMessageOf(error),
                  retryKey: const Key('post.retry'),
                  onRetry: () => ref.invalidate(postDetailProvider(widget.postId)),
                ),
                data: (data) {
                  ref.read(presenceProvider.notifier).track(
                      'post:${widget.postId}', [data.author.userId]);
                  return ListView(
                    padding: const EdgeInsets.fromLTRB(AppSpacing.pageH,
                        AppSpacing.xs, AppSpacing.pageH, AppSpacing.xxl),
                    children: [
                      PostCard(
                        post: data,
                        // 批次④行为保留:详情页作者头像参与「头像→资料页」转场
                        heroTag: 'avatar-post-${data.id}',
                        isMine: data.author.userId == myId,
                        online: presenceById[data.author.userId]?.online == true,
                        onTapAuthor: data.author.userId == myId
                            ? null
                            : () => context.push('/users/${data.author.userId}',
                                extra: 'avatar-post-${data.id}'),
                        onToggleLike: _toggleLike,
                        onOpenImage: (i) => openPhotoViewer(context,
                            urls: data.images, initialIndex: i),
                        menuAction: (action) => action == 'delete'
                            ? _deletePost()
                            : reportPostFromSheet(context, ref, data.id),
                        // 详情页里点卡不该再进详情
                        onTap: null,
                      ),
                      const SizedBox(height: AppSpacing.md),
                      comments.when(
                        loading: () => const Padding(
                          padding: EdgeInsets.all(AppSpacing.xxl),
                          child: Center(child: CircularProgressIndicator()),
                        ),
                        error: (error, _) => Padding(
                          padding: const EdgeInsets.all(AppSpacing.xxl),
                          child: AppErrorView(
                            message: apiMessageOf(error),
                            onRetry: () =>
                                ref.invalidate(commentsProvider(widget.postId)),
                          ),
                        ),
                        data: (items) => Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            if (items.isEmpty)
                              const Center(
                                child: AppEmptyState(
                                  emoji: '💬',
                                  title: '还没有评论',
                                  description: '来抢沙发',
                                ),
                              ),
                            for (var i = 0; i < items.length; i++) ...[
                              if (i > 0)
                                const Divider(
                                    height: 1, color: AppColors.divider),
                              _CommentTile(
                                comment: items[i],
                                heroTag: 'avatar-comment-${items[i].id}',
                                onTapAuthor: items[i].author.userId == myId
                                    ? null
                                    : () => context.push(
                                        '/users/${items[i].author.userId}',
                                        extra: 'avatar-comment-${items[i].id}'),
                              ),
                            ],
                          ],
                        ),
                      ),
                    ],
                  );
                },
              ),
            ),
            _CommentBar(
              input: _input,
              focus: _focus,
              sending: _sending,
              onSend: _send,
            ),
          ],
        ),
      ),
    );
  }
}

/// 详情页顶栏(§5.2,同 Task 5 的 _SubPageBar 规格)。
class _DetailBar extends StatelessWidget {
  const _DetailBar({required this.backKey});

  final Key backKey;

  static const _height = 52.0;

  @override
  Widget build(BuildContext context) => SizedBox(
        height: _height,
        child: Stack(
          alignment: Alignment.center,
          children: [
            Text('动态详情',
                style: AppText.subtitle.copyWith(fontSize: 17, color: AppColors.text1)),
            Positioned(
              left: 0,
              top: 0,
              bottom: 0,
              child: IconButton(
                key: backKey,
                onPressed: () => Navigator.of(context).maybePop(),
                icon: const Icon(Icons.arrow_back_ios_new_rounded,
                    size: 22, color: AppColors.text1),
              ),
            ),
          ],
        ),
      );
}

/// 评论行(附录 D):28 圆头像 + 昵称 13/w600 text2 + 正文 + 时间;行间 1px divider。
class _CommentTile extends StatelessWidget {
  const _CommentTile({required this.comment, this.onTapAuthor, this.heroTag});

  final PostCommentItem comment;
  final VoidCallback? onTapAuthor;
  final String? heroTag;

  @override
  Widget build(BuildContext context) {
    return Container(
      key: Key('post.comment.${comment.id}'),
      padding: const EdgeInsets.symmetric(
          horizontal: 0, vertical: 12), // 12 = AppSpacing.md(行上下留白)
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          AvatarHero(
            tag: heroTag,
            imageUrl: comment.author.avatarUrl,
            fromRadius: AppRadius.full,
            child: GestureDetector(
              key: Key('post.comment.avatar.${comment.id}'),
              behavior: HitTestBehavior.opaque,
              onTap: onTapAuthor ?? () {},
              child: AppAvatar(
                imageUrl: comment.author.avatarUrl,
                size: 28,
                fallbackText: comment.author.nickname,
              ),
            ),
          ),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                GestureDetector(
                  key: Key('post.comment.nickname.${comment.id}'),
                  behavior: HitTestBehavior.opaque,
                  onTap: onTapAuthor ?? () {},
                  child: Text(comment.author.nickname,
                      style: AppText.caption
                          .copyWith(fontWeight: FontWeight.w600, color: AppColors.text2)),
                ),
                const SizedBox(height: 2),
                Text(comment.text,
                    style: AppText.body.copyWith(color: AppColors.text1)),
                const SizedBox(height: 2),
                Text(formatPostTime(comment.createdAt),
                    style: AppText.micro.copyWith(color: AppColors.text3)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// 底部评论输入栏(附录 D;紧凑输入场景高 44,B.4 例外延伸):
/// R16 白底、1px divider、聚焦 1.5px brand + 光晕;发送纯图标随文字变色。
class _CommentBar extends StatelessWidget {
  const _CommentBar({
    required this.input,
    required this.focus,
    required this.sending,
    required this.onSend,
  });

  final TextEditingController input;
  final FocusNode focus;
  final bool sending;
  final VoidCallback onSend;

  static const _barHeight = 44.0; // 紧凑输入场景(附录 D 修订 B.4)

  @override
  Widget build(BuildContext context) => Container(
        color: AppColors.bgCard,
        child: SafeArea(
          top: false,
          child: Container(
            padding: const EdgeInsets.all(AppSpacing.sm),
            decoration: const BoxDecoration(
              border: Border(top: BorderSide(color: AppColors.divider)),
            ),
            child: Row(
              children: [
                Expanded(
                  child: ListenableBuilder(
                    listenable: Listenable.merge([focus, input]),
                    builder: (context, child) => Container(
                      height: _barHeight,
                      decoration: BoxDecoration(
                        color: AppColors.bgCard,
                        borderRadius: BorderRadius.circular(AppRadius.input),
                        border: Border.all(
                          color: focus.hasFocus ? AppColors.brand : AppColors.divider,
                          width: focus.hasFocus ? 1.5 : 1,
                        ),
                        boxShadow: focus.hasFocus
                            ? [
                                BoxShadow(
                                  color: AppColors.brand.withValues(alpha: .12),
                                  blurRadius: 12,
                                ),
                              ]
                            : null,
                      ),
                      child: child,
                    ),
                    child: TextField(
                      key: const Key('post.comment.input'),
                      controller: input,
                      focusNode: focus,
                      maxLength: 200,
                      style: AppText.body.copyWith(color: AppColors.text1),
                      decoration: InputDecoration(
                        hintText: '说点什么…',
                        hintStyle: AppText.body.copyWith(color: AppColors.text3),
                        counterText: '',
                        border: InputBorder.none,
                        isCollapsed: true,
                        contentPadding:
                            const EdgeInsets.symmetric(horizontal: 14),
                      ),
                      onSubmitted: (_) => onSend(),
                    ),
                  ),
                ),
                ListenableBuilder(
                  listenable: input,
                  builder: (context, _) => IconButton(
                    key: const Key('post.comment.send'),
                    onPressed: sending ? null : onSend,
                    icon: Icon(Icons.send_rounded,
                        size: 24,
                        color: input.text.trim().isEmpty
                            ? AppColors.text3
                            : AppColors.brand),
                  ),
                ),
              ],
            ),
          ),
        ),
      );
}
```

(`formatPostTime` 的 import:`../../core/format.dart`,已在上方整文件替换的 import 区补入;此处核对勿漏。)

- [ ] **Step 5: 跑测试确认通过**

```bash
../flutter/bin/flutter.bat test test/features/square/post_detail_page_test.dart test/features/square/hero_transition_test.dart
```

Expected: 全 PASS。`hero_transition_test` 的「作者与评论头像 tag」用例此时仍应绿(本任务详情页作者卡带 `heroTag: 'avatar-post-{id}'`、评论头像带 `avatar-comment-{id}`,与批次④行为一致);`post_detail_page_test` 首个用例的输入框断言(TextField controller text 为空)与 `post.comment.input` key 不变,照常成立。若「渲染动态与评论」用例因聚焦光晕相关 ListenableBuilder 报 pending timer,在用例尾部补 `await tester.pump(const Duration(milliseconds: 100))` 并 `focus.unfocus()`(通过测试内 `_CommentBar` 无引用——直接 `tester.tap` 页面空白处失焦即可,或给 TextField 加 `onSubmitted` 已有路径)。

- [ ] **Step 6: 全量门槛 + 提交**

```bash
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
git add -A
git commit -m "feat(ui): 动态详情页改版 — 顶栏/评论流/紧凑输入栏/骨架/AppToast" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 7: 整卡 Hero 接入(PostDetailArgs + seed + 状态切换双保)

**Files:**
- Create: `app/lib/features/square/post_detail_args.dart`
- Modify: `app/lib/router.dart`(`/posts/:id` 读 extra)
- Modify: `app/lib/features/square/post_detail_page.dart`(加 `args` 参数 + seed 渲染 + 顶卡 cardHeroTag)
- Modify: `app/lib/features/square/square_page.dart`(`_openDetail` 状态切换)
- Modify: `app/test/features/square/hero_transition_test.dart`(新 3 例)
- Test: `app/test/features/square/card_hero_flow_test.dart`(新建,端到端)

**Interfaces:**
- Consumes: Task 1 `CardHero`、Task 3 `PostCard(cardHeroTag:)`、Task 6 详情页
- Produces:
  - `class PostDetailArgs { const PostDetailArgs({required this.heroTag, required this.seed}); final String heroTag; final Post seed; }`
  - `PostDetailPage({required postId, PostDetailArgs? args})`(可选参数,既有调用/测试不破)
  - 广场页 `_openDetail(post)`:`_cardHeroPostId` 互斥状态 + `await push` + `finally` 还原
  - Hero 互斥不变式(全局约束)在广场页/详情页落地

- [ ] **Step 1: 写失败测试**

```dart
// app/test/features/square/card_hero_flow_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/avatar_hero.dart';
import 'package:chatapp_app/core/widgets/card_hero.dart';
import 'package:chatapp_app/features/square/post_detail_page.dart';
import 'package:chatapp_app/features/square/widgets/post_detail_skeleton.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

ScriptedAdapter _adapter() => ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /posts': (options) => ok(pageJson([
            postJson(id: 1, authorId: 9, nickname: 'Alice', text: '正文甲'),
            postJson(id: 2, authorId: 9, nickname: 'Alice', text: '正文乙'),
          ])),
      'GET /posts/1': (options) =>
          ok(postJson(id: 1, authorId: 9, nickname: 'Alice', text: '正文甲')),
      'GET /posts/1/comments': (options) => ok(pageJson([])),
      'GET /presence': (options) => ok({'results': []}),
    });

void main() {
  testWidgets('点卡:seed 首帧直出真卡(非骨架),args 带整卡 tag', (tester) async {
    final adapter = _adapter();
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await tester.tap(navTab('广场'));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('post.card.1')));
    await tester.pump(); // push 第一帧:provider 仍 loading

    // seed 直出:正文可见,没有骨架
    expect(find.text('正文甲'), findsWidgets);
    expect(find.byType(PostDetailSkeleton), findsNothing);

    await tester.pumpAndSettle();
    // 详情页顶卡是 CardHero 且 tag = card-post-1(限定详情页内找,列表页被盖仍在树里)
    final heroes = tester.widgetList<CardHero>(find.descendant(
        of: find.byType(PostDetailPage), matching: find.byType(CardHero)));
    expect(heroes.map((h) => h.tag), contains('card-post-1'));
    // 详情顶卡内头像 Hero 必须让位(嵌套断言不崩)
    expect(tester.takeException(), isNull);
  });

  testWidgets('互斥:飞行中的卡在列表里是整卡 Hero 态,头像 Hero 让位', (tester) async {
    final adapter = _adapter();
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await tester.tap(navTab('广场'));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('post.card.1')));
    await tester.pump(); // 飞行首帧

    // 列表卡 1 此时是整卡 Hero 态:头像让位(无 AvatarHero),整卡 CardHero 生效
    // (列表页被 push 盖住但仍在树里;卡 2 未飞行,仍是头像 Hero 态)
    expect(find.ancestor(
        of: find.byKey(const Key('post.avatar.1')),
        matching: find.byType(AvatarHero)), findsNothing);
    expect(find.ancestor(
        of: find.byKey(const Key('post.avatar.2')),
        matching: find.byType(AvatarHero)), findsOneWidget);

    await tester.pumpAndSettle();
  });

  testWidgets('返回后:列表卡还原头像 Hero 态,整卡 Hero 卸下', (tester) async {
    final adapter = _adapter();
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await tester.tap(navTab('广场'));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('post.card.1')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('post.back')));
    await tester.pumpAndSettle();

    expect(find.byType(PostDetailPage), findsNothing);
    expect(find.ancestor(
        of: find.byKey(const Key('post.avatar.1')),
        matching: find.byType(AvatarHero)), findsOneWidget);
    expect(find.byType(CardHero), findsNothing);
  });

  testWidgets('我的动态进详情:无 extra → 两端都不包 Hero', (tester) async {
    final adapter = _adapter();
    adapter.routes['GET /posts/mine'] =
        (options) => ok(pageJson([postJson(id: 7, authorId: 7, text: '我的')]));
    adapter.routes['GET /posts/7'] =
        (options) => ok(postJson(id: 7, authorId: 7, text: '我的'));
    adapter.routes['GET /posts/7/comments'] = (options) => ok(pageJson([]));
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await tester.tap(navTab('我的'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('my.row.posts')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('post.card.7')));
    await tester.pumpAndSettle();

    expect(find.byType(PostDetailPage), findsOneWidget);
    expect(find.byType(CardHero), findsNothing); // 无飞行源:两端都不包
  });
}

- [ ] **Step 2: 跑测试确认失败**

```bash
../flutter/bin/flutter.bat test test/features/square/card_hero_flow_test.dart
```

Expected: FAIL(`post_detail_args.dart` 不存在;`post.card.1` 点击后无 seed 直出)。

- [ ] **Step 3: 写 PostDetailArgs + 路由**

```dart
// app/lib/features/square/post_detail_args.dart
import 'models.dart';

/// 整卡 Hero 的跨页载荷(附录 D):经 go_router extra 传入。
/// [seed] 让详情页在 provider 未加载时用列表快照直出真卡 ——
/// Hero 只在 push 后下一帧末扫描一次,目标首帧必须有带相同 tag 的 Hero 才会飞。
class PostDetailArgs {
  const PostDetailArgs({required this.heroTag, required this.seed});

  final String heroTag;
  final Post seed;
}
```

`app/lib/router.dart` 的 `/posts/:id` 路由替换:

```dart
      GoRoute(
        path: '/posts/:id',
        builder: (context, state) {
          final args = state.extra is PostDetailArgs
              ? state.extra as PostDetailArgs
              : null; // 深链/无来源:extra 不是 PostDetailArgs(或为 null)
          return PostDetailPage(
            postId: int.parse(state.pathParameters['id']!),
            args: args,
          );
        },
      ),
```

(import 区补 `features/square/post_detail_args.dart`。)

- [ ] **Step 4: 详情页接 seed 与 CardHero**

`PostDetailPage` 构造加可选参数:

```dart
  const PostDetailPage({super.key, required this.postId, this.args});

  /// 整卡 Hero 载荷(附录 D);null(我的动态/深链)时无 Hero、骨架起步。
  final PostDetailArgs? args;
```

(import 区补 `post_detail_args.dart` 与 `card_hero.dart`。)

`build` 的 `post.when` 三分支改:`loading` 分支先看 `args?.seed` —— 有 seed 就调 `ref.read(presenceProvider.notifier).track('post:${widget.postId}', [seed.author.userId])` 后渲染 `_Body(post: seed, heroCardTag: args!.heroTag, presenceById: presenceById, myId: myId, comments: comments, onToggleLike: _toggleLike, onOpenImage: (post, i) => openPhotoViewer(context, urls: post.images, initialIndex: i), onMenu: (post, action) => action == 'delete' ? _deletePost() : reportPostFromSheet(context, ref, post.id))`;无 seed 渲染 `PostDetailSkeleton`。`data` 分支渲染 `_Body(post: data, heroCardTag: args?.heroTag, …同上)`。`error` 分支原样。

把原 `data` 分支内的 ListView 抽成页内私有 `_Body`(参数 `post: Post` / `heroCardTag: String?` / `presenceById: Map<int, Presence>` / `myId: int?` / `comments: AsyncValue<List<PostCommentItem>>` / `onToggleLike: VoidCallback` / `onOpenImage: void Function(Post, int)` / `onMenu: void Function(Post, String)`),其中顶卡改为:

```dart
                      CardHero(
                        tag: heroCardTag,
                        child: PostCard(
                          post: post,
                          // 整卡态:头像 Hero 必须让位(SDK 禁嵌套,spec §5)
                          heroTag: null,
                          isMine: post.author.userId == myId,
                          online: presenceById[post.author.userId]?.online == true,
                          onTapAuthor: post.author.userId == myId
                              ? null
                              : () => context.push('/users/${post.author.userId}',
                                  extra: 'avatar-post-${post.id}'),
                          onToggleLike: onToggleLike,
                          onOpenImage: (i) => onOpenImage(post, i),
                          menuAction: (action) => onMenu(post, action),
                          onTap: null,
                        ),
                      ),
```

(整卡 Hero 包在 PostCard 外侧由详情页负责:`PostCard.cardHeroTag` 保留但详情页不走它——避免「组件内 CardHero + 页面 CardHero 双包」歧义;`cardHeroTag` 参数供其他调用方使用。)

`avatar-comment-{id}` 评论头像 Hero 保持不变(评论区在卡外,无嵌套)。

- [ ] **Step 5: 广场页状态切换**

`square_page.dart` 加状态与方法(import 区补 `post_detail_args.dart`;替换原 `onTap: () => context.push('/posts/${post.id}')` 调用点):

```dart
  /// 正在飞整卡 Hero 的动态 id;null = 无飞行。
  /// 互斥不变式见 spec §5:飞行期间该卡头像 Hero 让位,返回后还原。
  int? _cardHeroPostId;

  Future<void> _openDetail(Post post) async {
    // 飞行中忽略新点击(防快速连点把飞行中的 Hero 卸载)
    if (_cardHeroPostId != null) return;
    setState(() => _cardHeroPostId = post.id);
    try {
      await context.push(
        '/posts/${post.id}',
        extra: PostDetailArgs(
          heroTag: 'card-post-${post.id}',
          seed: post,
        ),
      );
    } finally {
      if (mounted) setState(() => _cardHeroPostId = null);
    }
  }
```

列表 itemBuilder 的 `PostCard` 改(替换 `onTap`,加 `cardHeroTag`;该参数来自 Task 3 的 PostCard——组件内包 CardHero):

```dart
                                onTap: () => _openDetail(post),
                                cardHeroTag: _cardHeroPostId == post.id
                                    ? 'card-post-${post.id}'
                                    : null,
```

注意:头像/昵称的 `onTapAuthor` 不走 `_openDetail`(点头像仍直接进资料页,头像 Hero 不受影响)——现有 onTapAuthor 代码不动。

- [ ] **Step 6: 跑测试确认通过**

```bash
../flutter/bin/flutter.bat test test/features/square/card_hero_flow_test.dart test/features/square/hero_transition_test.dart test/features/square/square_page_test.dart test/features/square/post_detail_page_test.dart
```

Expected: 全 PASS。重点看:① `hero_transition_test` 的「头像→资料页」用例仍绿(广场列表普通态 onTapAuthor 未变);② 嵌套断言零异常(详情顶卡头像让位);③ 我的动态进详情无 CardHero;④ `hero_transition_test` 的「动态详情:作者与评论的头像 tag 各自独立」用例——该用例经广场点卡进详情,此时详情顶卡处于整卡 Hero 态(作者头像让位),但它断言的是详情页内 `avatar-comment-5` 与 `avatar-post-1` 的存在性:`avatar-post-1` 头像 Hero 在整卡态下**不存在于详情页**(让位),该用例断言需要适配:`containsAll(['avatar-post-1', 'avatar-comment-5'])` 改为只断言 `'avatar-comment-5'`,并在正文里记录「作者头像 tag 在整卡飞行态让位,返回列表后恢复」。

修改 `app/test/features/square/hero_transition_test.dart` 第三用例(约 :96-101):

```dart
    // 限定在详情页内:被盖住的广场页仍在树里,全局 find 会连它的一起算进来
    final tags = tester
        .widgetList<AvatarHero>(find.descendant(
            of: find.byType(PostDetailPage), matching: find.byType(AvatarHero)))
        .map((hero) => hero.tag)
        .toSet();
    // 批次⑤整卡 Hero:进详情走整卡态,作者头像让位(无 avatar-post-1 Hero),
    // 评论头像 tag 保留;返回列表后作者头像 Hero 恢复(互斥还原)
    expect(tags, contains('avatar-comment-5'));
    expect(tester.takeException(), isNull);
```

- [ ] **Step 7: 全量门槛 + 提交**

```bash
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
git add -A
git commit -m "feat(ui): 整卡 Hero 落地 — PostDetailArgs seed 直出 + 状态切换双保(§6.2 第二处)" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 8: 文档同步 + 手测准备

**Files:**
- Modify: `docs/superpowers/specs/2026-09-15-ui-design-language-design.md`(v1.3 → v1.4:附录 D + §6.2 完成态)
- Modify: `docs/pitfalls/frontend.md`(广场分节)
- Modify: `docs/pitfalls/testing.md`(AppToast Timer 条目)
- Modify: `CLAUDE.md`(里程碑表)
- Modify: `docs/superpowers/plans/2026-10-12-ui-revamp-batch5.md`(本文件,回填执行记录)

**Interfaces:**
- Consumes: Task 1–7 全部落地
- Produces: 文档与代码一致;release APK 上模拟器;手测清单(下方 Step 4)

- [ ] **Step 1: 规则文档升 v1.4**

头部状态行改 `v1.4(2026-10-12 增补附录 D:广场页落地补充,并修订 B.4 适用范围)…`;文末(附录 C 之后)追加:

```markdown
## 附录 D:广场页落地补充(2026-10-12,批次⑤)

本附录是 §9 边界流程的产出:以下场景规则正文未覆盖,经确认后定稿;后续页面遇同类场景以此为准。

### D.1 动态卡

- AppCard 白卡 R20、内边距 16、按压 scale .98;整卡可点进详情
- 头像 40 圆形(AppAvatar,首字占位 B.7)+ 在线呼吸点(§5.3);AvatarHero fromRadius = full
- 昵称 subtitle 16/w600;时间 micro text3;正文 body 15 text1
- 操作行:favorite_rounded / mode_comment_rounded 20,计数 caption text3;点赞未赞 text3、已赞 brand + 心跳脉冲 1→1.25→1(base,取消赞不弹)

### D.2 九宫格

- 1 张:通栏大图,宽撑满卡内、固定高 240,cover,R12
- 2–9 张:统一 3 列正方格(AspectRatio 1),间距 8,R12;废除旧 2–4 张两列混排
- 图挂:divider 底 + image_rounded text3(内容占位,非空态)

### D.3 广场页壳

- Tab 主页壳同 §5.2;FAB = 渐变圆钮 56(gradientHeart + add_rounded 白 24 + 主按钮阴影),bottom 外移 84 避开悬浮底栏;空态 = HeartRipple +「还没有动态」+ 次按钮;列表底部 padding 96

### D.4 整卡 Hero(§6.2「动态卡 → 动态详情」)

- tag:`card-post-{postId}`(由来源自身 id 派生;不用 userId,理由同 C.7)
- **SDK 硬约束**:Hero 不可嵌套(heroes.dart 运行时断言)→ 每张卡任意时刻至多一个 Hero:列表普通态 = 头像 Hero;点卡进详情时切「整卡态」(头像让位、CardHero 生效),pop 后还原
- **扫描时机**:push 后下一帧末仅扫一次 → 详情页首帧必须有同 tag Hero:extra 携带 `PostDetailArgs(heroTag, seed)`,provider loading 时用 seed 直出真卡
- 深链/我的动态进入(无 extra)→ 两端都不包 Hero;disableAnimations 不包;快速连点防护(飞行中忽略新点击)

### D.5 紧凑输入场景(修订 B.4 适用范围)

- B.4 的「输入框高 44」从聊天场景扩展为:**紧凑输入场景一律 44**(详情页评论框、后续列表页内输入);标准表单输入仍 52(§7)

### D.6 Toast 接入口径

- 页面内操作反馈(删除成功/点赞失败/举报结果)一律 AppToast(§7);表单校验类(⑥)沿用同口径;`AlertDialog` 确认弹窗不在此列
```

正文 §6.2 清单第 2 条改:

```markdown
2. **结构动效**:列表入场「上移 12px + 淡入」、逐项错峰 40ms(medium);页面 push 右滑入;Hero 转场 —— 头像→他人资料页、动态卡→动态详情(均已落地,见附录 C.7 / D.4)。
```

- [ ] **Step 2: 踩坑手册与 CLAUDE.md**

`docs/pitfalls/frontend.md` 广场分节(:30-35)改写:

```markdown
## 广场(`features/square/`)

- 页面:广场流 `square_page.dart`(白卡流/九宫格/点赞乐观更新+脉冲/滚底加载/整卡 Hero)、发布 `/posts/compose`(批次⑥改)、详情 `/posts/:id`(顶栏自绘+评论流+44 输入栏)、我的动态 `/my-posts`(复用动态卡,不参与 Hero);共用 `post_actions.dart`(删除确认 + 举报,提示走 AppToast)。
- ⚠️ **整卡 Hero 与头像 Hero 互斥**(SDK 禁 Hero 嵌套,debug 直接崩):列表卡普通态带头像 Hero,点卡进详情切整卡态(头像让位),pop 后还原;详情页顶卡内 PostCard 的 heroTag 必须 null。extra 载荷 `PostDetailArgs(heroTag, seed)`,seed 让详情页首帧直出真卡 —— Hero 只在 push 后下一帧末扫描一次,目标首帧没 Hero 就不飞。
- ⚠️ **在线点统一走 `AppAvatar(showOnlineDot:)`(内部 BreathingDot 呼吸动画)**:旧 `OnlineDot` 静态点已删(其 `#34C759` 也违反 §2.1 green);呼吸点可见的用例禁 pumpAndSettle。
- 测试 keys:`post.card.{id}` / `post.avatar.{id}` / `post.nickname.{id}` / `post.comment.avatar.{id}` / `post.comment.nickname.{id}` / `square.fab` / `square.compose` / `square.retry` / `post.back` / `myPosts.back` / `myPosts.compose`。
- ⚠️ 我的页行变多后,点靠下行的测试(想找的人/设置)要先 `tester.ensureVisible`。
```

`docs/pitfalls/testing.md` 前端分节追加一条:

```markdown
- ⚠️ **AppToast 的 2s 自动消失 Timer 会以 *A Timer is still pending* 弄挂用例**:触发过 Toast(删除成功/点赞失败/举报结果)的用例收尾必须 `await drainToast(tester)`(harness 提供,pump 3s 推过超时点)。
```

`CLAUDE.md` 里程碑表追加行(放在 2026-10-12 批次④行后):

```markdown
| 2026-10-12 | UI 整改批次⑤「广场」交付(页壳大标题+涟漪空态+骨架/动态卡圆头像+九宫格 3 列+点赞脉冲/详情页顶栏+44 评论栏/我的动态;**落地 §6.2 第二处整卡 Hero**——SDK 禁嵌套 → 状态切换双保 + seed 直出;规则文档升 v1.4 附录 D;删除孤儿 OnlineDot;N 测试绿) |
```

(N 以实测为准。)「下一步」段改为:批次⑤已交付,接下来 **⑥ 二级页**(编辑资料/想找的人/设置/登录/引导/发动态,表单控件规范在此批一次定)或启动上线合规轨。

- [ ] **Step 3: 全门槛 + 回归**

```bash
cd app
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
cd ../web
npm run test:run     # 不动 tokens.css,预期 303 全绿(纯回归确认)
```

Expected: analyze 零告警;flutter 全绿;web 303 全绿。

- [ ] **Step 4: 打包 + 装模拟器 + 手测清单**

```bash
cd app
../flutter/bin/flutter.bat build apk --release --dart-define=API_BASE=http://47.116.114.110/api/v1
adb devices
adb -s emulator-5554 install -r app/build/app/outputs/flutter-apk/app-release.apk
cd ../chatapp
python manage.py seed_fake_users --count 20    # 幂等,备手测数据
```

**手测清单(用户亲测)**:

- 广场页壳:大标题/骨架/空态(涟漪 + 发布按钮)/错误重试;FAB 渐变圆钮在悬浮底栏**上方**不重叠;下拉刷新;滚到底部最后一张卡不被底栏挡住
- 动态卡:圆形头像 + 在线呼吸点;九宫格 1 张通栏 / 3 张、9 张 3 列;点赞脉冲 + 变红;取消赞不弹;`···` 删除(确认弹窗 + Toast)/举报
- **整卡 Hero**:列表卡 → 详情飞行顺滑、无重影、图片不中途换图;返回反向飞行;飞行中快速连点不崩;从我的动态进详情**不飞**
- 详情页:顶栏标题/返回;评论 28 圆头像;输入框聚焦变粗变粉 + 光晕;发送钮空灰有字粉;发评论刷新
- 我的动态:空态「去发布」;顶栏返回
- 系统「减弱动态效果」开启:无 Hero/脉冲/涟漪,功能正常
- 窄屏(360dp):九宫格不溢出、卡内不截断
- 封禁账号:广场整屏不受影响(回归)
- 顺手检查:全 app 圆头像一致性(消息/聊天/广场/我的)

- [ ] **Step 5: 提交文档**

```bash
git add -A
git commit -m "docs: 规则文档 v1.4 附录 D + 踩坑册/CLAUDE.md 批次⑤同步" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 9: 待用户手测通过后收尾(另一步执行)

- [ ] **Step 1: 回填本文件执行记录**(测试数、任务提交表、手测结果)

- [ ] **Step 2: 合回 master**

```bash
git checkout master && git merge --ff-only ui/batch5
git push origin master
git branch -d ui/batch5 && git push origin --delete ui/batch5
```

- [ ] **Step 3: 更新会话记忆**(remember 流程)

---

## 执行记录(2026-10-12,分支 `ui/batch5`)

**交付结果**

| 门禁 | 结果 |
|---|---|
| `flutter analyze` | 0 告警 |
| `flutter test` | **296 全绿**(基线 278,本批 +18) |
| `npm run test:run`(web) | 303 全绿(未动 `tokens.css`,纯回归) |
| release APK | 已打包并覆盖安装到 `emulator-5554`,启动无异常(71.2MB,API_BASE=测试服) |
| 模拟器手测 | ⬜ **待用户执行**(见 Task 8 Step 4 清单) |
| 合回 master | ⬜ 待手测通过 |

**任务与提交**

| 任务 | 提交 | 内容 |
|---|---|---|
| Task 1 | `c8a9613` | `CardHero` 组件(禁嵌套/降级纪律内置)+ 3 例单测 |
| Task 2 | `a4c821c` | 九宫格:1 张通栏 240 高、2–9 张统一 3 列 R12 + 4 例单测 |
| Task 3 | `fb751be` | 动态卡重构(圆头像/字阶/rounded 图标/点赞脉冲)+ 删 `OnlineDot` + 脉冲单测 |
| Task 4 | `733f8e5` | 广场页壳(大标题/涟漪空态/骨架/错误重试/渐变 FAB/AppToast)+ `PostDetailArgs` |
| Task 5 | `f0cb8f3` | 我的动态页(顶栏/空态发布按钮/骨架/错误/AppToast) |
| Task 6 | `bb533c4` | 详情页(顶栏/评论流/44 紧凑输入栏/骨架/AppToast) |
| Task 7 | `497b273` | 整卡 Hero 接线(seed 直出 + 状态切换双保)+ 端到端 4 例 |
| Task 8 | `4b10fbd` | 文档同步(规则 v1.4 附录 D + 踩坑册 + CLAUDE.md)+ 打包上模拟器 |

**执行中的实测发现(已回填规则文档附录 D / 踩坑册)**

1. **Hero 不可嵌套**:`heroes.dart:412` 运行时断言 —— 实现前核查时发现,设计阶段「同页双 Hero 不冲突」的判断被证伪,改用「状态切换双保」(点卡时该卡头像 Hero 让位,`await push` 返回后还原)。**详情页顶卡在整卡态下 `heroTag` 必须 null**。
2. **Hero 只扫一次**:`heroes.dart:961-973` push 后仅下一帧末扫描目标路由;详情 provider 是 autoDispose → 首帧必为骨架屏,故 `extra` 带 `PostDetailArgs(heroTag, seed)` 用列表快照直出真卡。
3. **IndexedStack 隐藏页也跑动画**:广场空态 `HeartRipple` 会让「消息 Tab 角标」等无关用例 `pumpAndSettle` 超时(实测),相关用例改 `pumpFrames`。
4. **`find.byX` 默认 `skipOffstage: true`**:被 push 盖住的路由默认找不到,需显式 `skipOffstage: false`;`CardHero`/`AvatarHero` 是恒在包装(tag null 时只返回 child),判断「有没有 Hero」要看 `tag != null`。
5. **`AppToast` 的 2s Timer**:触发过 Toast 的用例收尾要推时钟(harness 新增 `drainToast`)。
6. **`SquareSkeleton` 溢出**:3 张卡总高 864 > 一屏,外包 `SingleChildScrollView` 免疫小屏。
7. 详情页无整卡 Hero 来源(深链/我的动态)时,**保留**批次④的「作者头像 → 资料页」转场(仅整卡态让位)。

