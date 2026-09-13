# 广场动态作者入口 + 在线绿点 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 广场列表与动态详情页中点作者头像/昵称可进公开资料页;作者头像右下角显示在线绿点;presence 控制器支持 >100 个 id 分片查询。

**Architecture:** 纯 Flutter 前端改动(后端零改动)。复用现成的 `features/presence` 共享控制器(`track()` 登记 + 合并去重 + 45s 刷新)与 `GET /users/{id}` 公开资料接口;`PostCard` 保持哑组件(数据由页面传入);在 `PresenceController.refresh()` 内按后端上限 100 分片请求。

**Tech Stack:** Flutter 3.47.2 / Riverpod 3.4 / go_router;测试 = `flutter test` + `test/support/` 的 `pumpApp`/`ScriptedAdapter` 假网络。

**Spec:** `docs/superpowers/specs/2026-09-13-square-profile-presence-design.md`

## Global Constraints

- 前端命令一律在 `app/` 目录下用 `../flutter/bin/flutter.bat`(Windows)。
- 每个任务结束前 `../flutter/bin/flutter.bat analyze` 必须**零告警**。
- 前端测试基线 **189 全绿**,本计划预计 +7~9 个新用例。
- 所有用户可见文案为中文;测试里断言中文文案时注意文件本身是 UTF-8。
- 后端零改动,**不要**动 `chatapp/` 下任何文件。
- 测试纪律(CLAUDE.md):有轮询/计时器的页面别用 `pumpAndSettle` 会卡死的场景此处不涉及;假网络没铺的路由返回 404。
- `onTapAuthor == null` 的语义:**吞掉点击**(`onTap: onTapAuthor ?? () {}` + `HitTestBehavior.opaque`)——自己的头像/昵称点了完全没反应(既不进资料页、也不触发外层卡片),卡片其他区域照常进动态详情。

---

## 文件结构(改动地图)

| 文件 | 责任 |
|---|---|
| `app/lib/features/presence/presence_controller.dart` | 修改:`refresh()` 内按 100 分片请求、合并后一次写 state |
| `app/lib/features/square/widgets/post_card.dart` | 修改:新增 `online`/`onTapAuthor` 参数;头像与昵称包可点手势;头像右下角绿点 |
| `app/lib/features/square/square_page.dart` | 修改:watch presence + `track('square', ids)`;逐卡传参 |
| `app/lib/features/square/post_detail_page.dart` | 修改:watch presence + `track('post:{id}', [作者])`;顶部卡片传参;`_CommentTile` 加点击 |
| `app/test/features/presence/presence_controller_test.dart` | 新增 2 个用例(分片合并 / 分片中途失败) |
| `app/test/features/square/square_page_test.dart` | 改 `_adapter` 补 `/presence`;新增点击与绿点用例 |
| `app/test/features/square/post_detail_page_test.dart` | 换 GoRouter harness;新增评论点击用例 |
| `CLAUDE.md` | 交付后补记(最后任务) |

---

### Task 1: PresenceController 按 100 分片

**Files:**
- Modify: `app/lib/features/presence/presence_controller.dart:58-70`
- Test: `app/test/features/presence/presence_controller_test.dart`

**Interfaces:**
- Consumes: `PresenceRepository.fetchPresence(List<int>) → Future<Map<int, Presence>>`(既有);后端单次上限 100(`chatapp/users/presence.py::PRESENCE_MAX_IDS`)。
- Produces: `PresenceController.refresh()` 语义不变(结果合并写 state、失败保留旧值);新增私有常量 `_batchSize = 100`。

- [ ] **Step 1: 写失败测试**

在 `app/test/features/presence/presence_controller_test.dart` 的 `main()` 里追加两个用例(放在文件末尾 `}` 之前;`waitFor`、`makeContainer`、`adapter`、`presenceRequests` 均为该文件已有成员):

```dart
  test('超过 100 个 id 拆片请求并合并结果', () async {
    adapter.routes['GET /presence'] = (options) {
      final ids = (options.queryParameters['user_ids'] as String).split(',');
      return ok({
        'results': [
          for (final id in ids)
            {'user_id': int.parse(id), 'online': true, 'last_active_at': null},
        ],
      });
    };
    final container = makeContainer();
    final ids = List<int>.generate(150, (i) => i + 1);

    container.read(presenceProvider.notifier).track('square', ids);
    await waitFor(() => container.read(presenceProvider).length == 150);

    final requests = adapter.log.where((r) => r.path == '/presence').toList();
    expect(requests, hasLength(2));
    expect((requests[0].queryParameters['user_ids'] as String).split(','), hasLength(100));
    expect((requests[1].queryParameters['user_ids'] as String).split(','), hasLength(50));
  });

  test('分片中途失败:整轮放弃,保留旧值', () async {
    final container = makeContainer();
    final notifier = container.read(presenceProvider.notifier);
    adapter.routes['GET /presence'] = (options) => ok({
          'results': [
            {'user_id': 1, 'online': true, 'last_active_at': null},
          ],
        });
    notifier.track('chats', [1]);
    await waitFor(() => container.read(presenceProvider).containsKey(1));

    var calls = 0;
    adapter.routes['GET /presence'] = (options) {
      calls += 1;
      if (calls == 1) return ok({'results': []});   // 第 1 片成功
      return offline(options);                       // 第 2 片失败
    };
    notifier.track('square', List<int>.generate(150, (i) => i + 2));
    await waitFor(() => calls >= 2);
    await Future<void>.delayed(const Duration(milliseconds: 50));

    final state = container.read(presenceProvider);
    expect(state.containsKey(1), isTrue);    // 旧值还在
    expect(state.containsKey(2), isFalse);   // 没有分片结果半更新进去
  });
```

- [ ] **Step 2: 跑测试确认红**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/presence/presence_controller_test.dart`
Expected: 第一个新用例 FAIL(`requests` 只有 1 个,`hasLength(2)` 不符);第二个用例 FAIL(旧实现第 1 片就整体成功/失败语义不同,`calls >= 2` 超时断言失败)。

- [ ] **Step 3: 最小实现**

`app/lib/features/presence/presence_controller.dart`:文件头 import 区加 `import 'dart:math' as math;`;把 `refresh()` 换成(其余方法不动):

```dart
  /// 后端单次查询上限(chatapp/users/presence.py::PRESENCE_MAX_IDS=100);
  /// 广场按翻页登记作者,id 数会超过上限,故按片请求、合并后一次写 state。
  static const _batchSize = 100;

  /// 拉一轮;失败保留旧值、下个周期再试(点缀信息,不弹提示)。
  Future<void> refresh() async {
    final ids = <int>{for (final list in _owners.values) ...list}.toList();
    if (ids.isEmpty) return;
    try {
      final repo = ref.read(presenceRepositoryProvider);
      final fresh = <int, Presence>{};
      for (var start = 0; start < ids.length; start += _batchSize) {
        final chunk = ids.sublist(start, math.min(start + _batchSize, ids.length));
        fresh.addAll(await repo.fetchPresence(chunk));
      }
      final next = Map<int, Presence>.from(state)
        ..removeWhere((id, _) => ids.contains(id));
      next.addAll(fresh);
      state = next;
    } catch (_) {
      // 网络抖动/任一片失败:整轮放弃,保持旧数据,别打扰用户
    }
  }
```

- [ ] **Step 4: 跑测试确认绿**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/presence`
Expected: 该目录全部 PASS(原 5 个用例 + 新 2 个)。

- [ ] **Step 5: 提交**

```bash
git add app/lib/features/presence/presence_controller.dart app/test/features/presence/presence_controller_test.dart
git commit -m "feat(presence): 批量查询按 100 分片,id 超上限不再整轮失败"
```

---

### Task 2: 广场列表卡片 —— 作者可点 + 在线绿点

**Files:**
- Modify: `app/lib/features/square/widgets/post_card.dart`
- Modify: `app/lib/features/square/square_page.dart:116-129`(itemBuilder)与 `data:` 分支
- Test: `app/test/features/square/square_page_test.dart`

**Interfaces:**
- Consumes: `presenceProvider`(`features/presence/presence_controller.dart`)、`OnlineDot`(`features/presence/online_dot.dart`)、`userProfileProvider`(`features/moderation/moderation_controller.dart`,由 `UserProfilePage` 内部使用)、路由 `/users/:id`(既有)。
- Produces: `PostCard` 新参数 `bool online = false`、`VoidCallback? onTapAuthor`;测试 keys `post.avatar.{postId}`、`post.nickname.{postId}`。Task 3 复用同一接口。

- [ ] **Step 1: 写失败测试**

`app/test/features/square/square_page_test.dart`:

(a) 顶部 import 区加:

```dart
import 'package:chatapp_app/features/presence/online_dot.dart';
```

(b) 把 `_adapter` 换成带 presence 的版本(原有 5 个用例自动受益,不再静默 404):

```dart
ScriptedAdapter _adapter(Map<String, dynamic> postsPage,
        {Map<String, dynamic>? presence}) =>
    ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson(nickname: '小明')),
      'GET /posts': (options) => ok(postsPage),
      'GET /presence': (options) => ok(presence ?? {'results': []}),
    });
```

(c) `main()` 末尾追加四个用例(登录用户 id=7,见 `_loggedIn`):

```dart
  testWidgets('点头像打开公开资料页', (tester) async {
    final adapter = _adapter(
        pageJson([postJson(id: 1, authorId: 9, nickname: 'Alice', text: '你好')]));
    adapter.routes['GET /users/9'] =
        (options) => ok(publicProfileJson(userId: 9, nickname: 'Alice'));

    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await _openSquare(tester);

    await tester.tap(find.byKey(const Key('post.avatar.1')));
    await tester.pumpAndSettle();

    expect(find.text('详细资料'), findsOneWidget);
    expect(find.text('ID:u9'), findsOneWidget);
  });

  testWidgets('点昵称打开公开资料页', (tester) async {
    final adapter = _adapter(
        pageJson([postJson(id: 1, authorId: 9, nickname: 'Alice', text: '你好')]));
    adapter.routes['GET /users/9'] =
        (options) => ok(publicProfileJson(userId: 9, nickname: 'Alice'));

    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await _openSquare(tester);

    await tester.tap(find.byKey(const Key('post.nickname.1')));
    await tester.pumpAndSettle();

    expect(find.text('详细资料'), findsOneWidget);
  });

  testWidgets('自己的动态点头像不打开资料页', (tester) async {
    final adapter =
        _adapter(pageJson([postJson(id: 3, authorId: 7, nickname: '小明', text: '我发的')]));

    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await _openSquare(tester);

    await tester.tap(find.byKey(const Key('post.avatar.3')));
    await tester.pumpAndSettle();

    // 完全没反应:既不进资料页,也不触发外层卡片进详情
    expect(find.text('详细资料'), findsNothing);
    expect(find.text('动态详情'), findsNothing);
  });

  testWidgets('作者在线时头像右下角显示绿点,离线不显示', (tester) async {
    final adapter = _adapter(
      pageJson([
        postJson(id: 1, authorId: 9, nickname: 'Alice', text: '在线的人'),
        postJson(id: 2, authorId: 10, nickname: 'Bob', text: '离线的人'),
      ]),
      presence: {
        'results': [
          {'user_id': 9, 'online': true, 'last_active_at': null},
          {'user_id': 10, 'online': false, 'last_active_at': '2026-09-13T10:00:00+08:00'},
        ],
      },
    );

    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await _openSquare(tester);
    await tester.pumpAndSettle();

    expect(
        find.descendant(
            of: find.byKey(const Key('post.avatar.1')), matching: find.byType(OnlineDot)),
        findsOneWidget);
    expect(
        find.descendant(
            of: find.byKey(const Key('post.avatar.2')), matching: find.byType(OnlineDot)),
        findsNothing);
    // 查的正是两条动态的作者 id
    final request = adapter.log.lastWhere((r) => r.path == '/presence');
    expect(request.queryParameters['user_ids'], contains('9'));
    expect(request.queryParameters['user_ids'], contains('10'));
  });
```

- [ ] **Step 2: 跑测试确认红**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/square/square_page_test.dart`
Expected: 4 个新用例 FAIL(找不到 `post.avatar.1` / `post.nickname.1` key;无绿点);原 5 个用例仍 PASS。

- [ ] **Step 3: 实现 PostCard**

`app/lib/features/square/widgets/post_card.dart`:

(a) import 区加 `import '../../presence/online_dot.dart';`

(b) 构造函数与字段加两个参数:

```dart
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
  });

  /// 作者是否在线 → 头像右下角绿点。
  final bool online;

  /// 点作者头像/昵称的回调;null(自己/不关心)= 不注册点击,落到卡片默认行为。
  final VoidCallback? onTapAuthor;
```

(c) `build` 里头像与昵称包手势(替换原 `_Avatar(...)` 行与昵称 `Text` 所在结构):

```dart
            GestureDetector(
              key: Key('post.avatar.${post.id}'),
              behavior: HitTestBehavior.opaque,
              // null(自己)= 空回调吞掉点击,不落到卡片的「进详情」
              onTap: onTapAuthor ?? () {},
              child: _Avatar(
                  url: post.author.avatarUrl, name: post.author.nickname, online: online),
            ),
            const SizedBox(width: 10),
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
                                style: const TextStyle(
                                    fontWeight: FontWeight.w600, fontSize: 15)),
                          ),
                        ),
                      ),
                      if (menuAction != null) ...原有菜单代码不动...
```

(d) `_Avatar` 加 `online` 参数与绿点:

```dart
class _Avatar extends StatelessWidget {
  const _Avatar({this.url, required this.name, this.online = false});

  final String? url;
  final String name;
  final bool online;

  @override
  Widget build(BuildContext context) {
    final placeholder = Center(
      child: Text(name.isEmpty ? '?' : name.substring(0, 1),
          style: const TextStyle(color: Colors.white)),
    );
    final avatar = Container(
      width: 40,
      height: 40,
      decoration: BoxDecoration(
        color: const Color(0xFFC9CDD4),
        borderRadius: BorderRadius.circular(6),
      ),
      clipBehavior: Clip.antiAlias,
      child: url == null || url!.isEmpty
          ? placeholder
          : Image.network(url!, fit: BoxFit.cover,
              errorBuilder: (c, e, s) => placeholder),
    );
    if (!online) return avatar;
    return Stack(
      clipBehavior: Clip.none,
      children: [
        avatar,
        const Positioned(right: 0, bottom: 0, child: OnlineDot(size: 11)),
      ],
    );
  }
}
```

- [ ] **Step 4: 实现 square_page 接线**

`app/lib/features/square/square_page.dart`:

(a) import 区加 `import '../presence/presence_controller.dart';`

(b) `build` 顶部加 watch:

```dart
    final posts = ref.watch(squareProvider);
    final presenceById = ref.watch(presenceProvider);
    final myId = ref.watch(profileProvider).value?.userId;
```

(c) `data:` 分支由三元表达式改为块体(登记 + 原逻辑):

```dart
        data: (items) {
          ref.read(presenceProvider.notifier).track(
              'square', [for (final post in items) post.author.userId]);
          return items.isEmpty
              ? Center( ...原有空态代码不动... )
              : RefreshIndicator( ...原有列表代码,见下... );
        },
```

(d) itemBuilder 里 PostCard 加两个参数:

```dart
                    return PostCard(
                      post: post,
                      isMine: post.author.userId == myId,
                      online: presenceById[post.author.userId]?.online == true,
                      onTapAuthor: post.author.userId == myId
                          ? null
                          : () => context.push('/users/${post.author.userId}'),
                      onToggleLike: () => _toggleLike(post),
                      onTap: () => context.push('/posts/${post.id}'),
                      onOpenImage: (i) =>
                          openPhotoViewer(context, urls: post.images, initialIndex: i),
                      menuAction: (action) => action == 'delete'
                          ? _deletePost(post)
                          : reportPostFromSheet(context, ref, post.id),
                    );
```

- [ ] **Step 5: 跑测试确认绿 + analyze**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/square && ../flutter/bin/flutter.bat analyze`
Expected: square 目录全 PASS(原 5 + 新 4);analyze 零告警。

- [ ] **Step 6: 提交**

```bash
git add app/lib/features/square/widgets/post_card.dart app/lib/features/square/square_page.dart app/test/features/square/square_page_test.dart
git commit -m "feat(square): 列表卡片作者头像/昵称可点进资料页,作者在线亮绿点"
```

---

### Task 3: 详情页 —— 顶部卡片同款 + 评论作者可点

**Files:**
- Modify: `app/lib/features/square/post_detail_page.dart`(`build` 的 `data:` 分支、`PostCard` 调用、`_CommentTile`)
- Test: `app/test/features/square/post_detail_page_test.dart`

**Interfaces:**
- Consumes: Task 2 的 `PostCard(online:, onTapAuthor:)`;`presenceProvider`;评论模型 `PostCommentItem.author.userId`。
- Produces: 评论测试 keys `post.comment.avatar.{commentId}`、`post.comment.nickname.{commentId}`。

- [ ] **Step 1: 写失败测试(含 harness 改造)**

`app/test/features/square/post_detail_page_test.dart`:该文件现在的 `pumpDetail` 用 `MaterialApp` 直接 push 页面,**没有 go_router,`context.push` 会抛错**,必须先换成 GoRouter harness:

(a) 顶部 import 加:

```dart
import 'package:go_router/go_router.dart';

import 'package:chatapp_app/features/profile/user_profile_page.dart';
```

(b) `pumpDetail` 整个替换为:

```dart
Future<void> pumpDetail(WidgetTester tester, ScriptedAdapter adapter,
    {required int postId}) async {
  SharedPreferences.setMockInitialValues({});
  final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
  final router = GoRouter(
    initialLocation: '/posts/$postId',
    routes: [
      GoRoute(
        path: '/posts/:id',
        builder: (context, state) =>
            PostDetailPage(postId: int.parse(state.pathParameters['id']!)),
      ),
      GoRoute(
        path: '/users/:id',
        builder: (context, state) =>
            UserProfilePage(userId: int.parse(state.pathParameters['id']!)),
      ),
    ],
  );
  await tester.pumpWidget(ProviderScope(
    overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(dio),
    ],
    child: MaterialApp.router(routerConfig: router),
  ));
  await tester.pumpAndSettle();
}
```

(c) 原有第 1 个用例的 adapter 补铺 `GET /presence`(现在详情页会 track 作者):

```dart
      'GET /presence': (options) => ok({'results': []}),
```

(d) `main()` 末尾追加三个用例(登录用户 id=7):

```dart
  testWidgets('点评论者头像打开公开资料页', (tester) async {
    final adapter = ScriptedAdapter({
      'GET /posts/1': (options) =>
          ok(postJson(id: 1, authorId: 9, nickname: 'Alice', text: '正文')),
      'GET /posts/1/comments': (options) =>
          ok(pageJson([commentJson(id: 5, authorId: 11, nickname: 'Bob', text: '好漂亮')])),
      'GET /users/11': (options) => ok(publicProfileJson(userId: 11, nickname: 'Bob')),
      'GET /presence': (options) => ok({'results': []}),
    });
    await pumpDetail(tester, adapter, postId: 1);
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('post.comment.avatar.5')));
    await tester.pumpAndSettle();

    expect(find.text('详细资料'), findsOneWidget);
    expect(find.text('ID:u11'), findsOneWidget);
  });

  testWidgets('点评论者昵称打开公开资料页', (tester) async {
    final adapter = ScriptedAdapter({
      'GET /posts/1': (options) =>
          ok(postJson(id: 1, authorId: 9, nickname: 'Alice', text: '正文')),
      'GET /posts/1/comments': (options) =>
          ok(pageJson([commentJson(id: 5, authorId: 11, nickname: 'Bob', text: '好漂亮')])),
      'GET /users/11': (options) => ok(publicProfileJson(userId: 11, nickname: 'Bob')),
      'GET /presence': (options) => ok({'results': []}),
    });
    await pumpDetail(tester, adapter, postId: 1);
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('post.comment.nickname.5')));
    await tester.pumpAndSettle();

    expect(find.text('详细资料'), findsOneWidget);
  });

  testWidgets('点自己的评论不打开资料页', (tester) async {
    final adapter = ScriptedAdapter({
      'GET /users/me': (options) => ok(profileJson(nickname: '小明', userId: 7)),
      'GET /posts/1': (options) =>
          ok(postJson(id: 1, authorId: 9, nickname: 'Alice', text: '正文')),
      'GET /posts/1/comments': (options) =>
          ok(pageJson([commentJson(id: 5, authorId: 7, nickname: '小明', text: '我评的')])),
      'GET /presence': (options) => ok({'results': []}),
    });
    await pumpDetail(tester, adapter, postId: 1);
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('post.comment.avatar.5')));
    await tester.pumpAndSettle();

    expect(find.text('详细资料'), findsNothing);
  });
```

- [ ] **Step 2: 跑测试确认红**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/square/post_detail_page_test.dart`
Expected: 新用例 FAIL(找不到 `post.comment.avatar.5` 等 key);原 2 个用例 PASS。

- [ ] **Step 3: 实现**

`app/lib/features/square/post_detail_page.dart`:

(a) import 区加 `import '../presence/presence_controller.dart';`

(b) `build` 顶部加:

```dart
    final presenceById = ref.watch(presenceProvider);
```

(c) `data:` 分支由 `(data) => ListView(...)` 改为块体,登记作者并返回原 ListView:

```dart
              data: (data) {
                ref.read(presenceProvider.notifier).track(
                    'post:${widget.postId}', [data.author.userId]);
                return ListView( ...原有 children 内容不动,但 PostCard 与 _CommentTile 按下文改... );
              },
```

(d) 顶部 PostCard 加参数:

```dart
                  PostCard(
                    post: data,
                    isMine: data.author.userId == myId,
                    online: presenceById[data.author.userId]?.online == true,
                    onTapAuthor: data.author.userId == myId
                        ? null
                        : () => context.push('/users/${data.author.userId}'),
                    onToggleLike: _toggleLike,
                    onOpenImage: (i) =>
                        openPhotoViewer(context, urls: data.images, initialIndex: i),
                    menuAction: (action) => action == 'delete'
                        ? _deletePost()
                        : reportPostFromSheet(context, ref, data.id),
                  ),
```

(e) 评论列表传点击回调:

```dart
                        for (final comment in items)
                          _CommentTile(
                            comment: comment,
                            onTapAuthor: comment.author.userId == myId
                                ? null
                                : () => context
                                    .push('/users/${comment.author.userId}'),
                          ),
```

(f) `_CommentTile` 加参数并包手势:

```dart
class _CommentTile extends StatelessWidget {
  const _CommentTile({required this.comment, this.onTapAuthor});

  final PostCommentItem comment;

  /// 点评论者的头像/昵称;null(自己)=> 空回调吞掉点击。
  final VoidCallback? onTapAuthor;

  @override
  Widget build(BuildContext context) {
    return Container(
      key: Key('post.comment.${comment.id}'),
      color: Colors.white,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          GestureDetector(
            key: Key('post.comment.avatar.${comment.id}'),
            behavior: HitTestBehavior.opaque,
            onTap: onTapAuthor ?? () {},
            child: Container( ...原有 28x28 头像代码不动... ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                GestureDetector(
                  key: Key('post.comment.nickname.${comment.id}'),
                  behavior: HitTestBehavior.opaque,
                  onTap: onTapAuthor ?? () {},
                  child: Text(comment.author.nickname,
                      style: const TextStyle(fontSize: 12, color: Color(0xFF999999))),
                ),
                ...评论正文/时间不动...
```

- [ ] **Step 4: 跑测试确认绿 + analyze**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/square && ../flutter/bin/flutter.bat analyze`
Expected: square 目录全 PASS(原 2 + 新 3);analyze 零告警。

- [ ] **Step 5: 提交**

```bash
git add app/lib/features/square/post_detail_page.dart app/test/features/square/post_detail_page_test.dart
git commit -m "feat(square): 详情页评论作者可点进资料页,顶部卡片补在线绿点"
```

---

### Task 4: 全量回归 + 文档 + 手测

**Files:**
- Modify: `CLAUDE.md`(「广场页(动态流)」章节补两行;「在线状态」章节补一句广场接入)
- Test: 全量

**Interfaces:**
- Consumes: Task 1-3 全部产出。
- Produces: 可安装的 relelease 包产物(手测用);CLAUDE.md 交付记录。

- [ ] **Step 1: 全量前端回归**

Run: `cd app && ../flutter/bin/flutter.bat analyze && ../flutter/bin/flutter.bat test`
Expected: analyze 零告警;测试全绿(基线 189 + 新增 7 = 约 196)。

- [ ] **Step 2: 更新 CLAUDE.md**

「广场页(动态流)」章节末尾补:

```
- **作者入口与在线标识(2026-09-13 追加)**:动态卡片与评论的头像/昵称可点进公开资料页(`/users/{id}`;自己的不注册点击,落到卡片默认行为);作者头像右下角在线绿点(仅在线时,`OnlineDot(size: 11)`),数据走 `presenceProvider.track('square', ids)` / `track('post:{id}', [作者])`。⚠️ presence 接口单次上限 100 个 id(`users/presence.py::PRESENCE_MAX_IDS`),`PresenceController.refresh` 内部分片;新增「会随翻页无限增长的登记源」时不用再操心上限
```

「在线状态(最后活跃)」章节「三处展示」句后补:`(2026-09-13 追加第四处:广场动态卡片作者头像绿点)`

- [ ] **Step 3: 双模拟器手测**

Run(先起后端栈:Redis 容器 + celery worker + runserver;见 CLAUDE.md 常用命令):

```bash
cd app && ../flutter/bin/flutter.bat build apk --release --dart-define=API_BASE=http://10.0.2.2:8000/api/v1
"$LOCALAPPDATA/Android/Sdk/platform-tools/adb.exe" -s emulator-5554 install -r build/app/outputs/flutter-apk/app-release.apk
"$LOCALAPPDATA/Android/Sdk/platform-tools/adb.exe" -s emulator-5556 install -r build/app/outputs/flutter-apk/app-release.apk
```

清单(当前两台:5554=u8、5556=u7;可任选一台改登 u39 刘亦菲——她有 5 条动态正好给对面看):
1. 广场列表点他人头像/昵称 → 资料页;点自己头像 → 进动态详情(不是资料页);点卡片正文 → 动态详情(回归)。
2. 另一端开着 App → 作者头像右下角绿点;另一端杀 App ≤2 分钟 → 绿点消失(≤45s 刷新周期)。
3. 动态详情页:点作者、点评论者 → 资料页;评论区没有绿点。
4. 消息页/发现页/聊天页绿点与文案照旧(回归)。

- [ ] **Step 4: 提交**

```bash
git add CLAUDE.md
git commit -m "docs: 广场作者入口与在线绿点交付记录(手测通过)"
```

---

## 交付线

- 后端零改动(全量 327 不受影响,执行本计划时不必跑后端测试即可)。
- 完成后按用户惯例:`finishing-a-development-branch` → 本地合回 master → 推 origin。
