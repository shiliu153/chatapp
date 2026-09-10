# M2b 发现卡片流与配对动效 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把「发现」Tab 的占位换成真正的卡片流:批量拉候选、拖拽/按钮滑卡(like/pass)、快见底时自动续拉,互相喜欢时弹配对动效。

**Architecture:** 沿用 M2a 的分层——repository(纯 IO,JSON → 模型)→ Riverpod controller(卡组状态)→ widget。手势和动画全部自绘,**不引第三方卡组包**:`SwipeDeck` 自己管位移与飞出动画,滑卡结果通过 `onDecide` 回调交给页面;页面把结果交给 `DiscoveryController`(先乐观移卡,失败放回队首)并在 `matched` 时弹 `MatchOverlay`。所有网络图片一律带 `errorBuilder`/`onBackgroundImageError`(测试的假网络对图片一律 400)。

**Tech Stack:** Flutter 3.47.2 / Dart 3.13、flutter_riverpod 3.4.3、go_router 18、dio 5.11;测试沿用 `app/test/support/`(`ScriptedAdapter` 假网络 + `pumpApp` 起整个 App)。

## Global Constraints

- **不新增任何 pub 依赖**(卡组/动效全自绘)。现有依赖:`flutter_riverpod 3.4.3`、`go_router 18`、`dio 5.11`、`shared_preferences`、`image_picker`。
- Riverpod 3.4:`AsyncValue.valueOrNull` 已移除,一律用 `.value`(可空)。
- 命令都在 `app/` 下跑:`../flutter/bin/flutter.bat analyze`(必须零告警)、`../flutter/bin/flutter.bat test`。
- 后端不动;接口沿用 M1b 已实现的:
  - `GET /discovery/candidates?limit=N` → 数组,字段 `user_id/nickname/gender/age/city/bio/tags/photos`(photos 只含已过审)
  - `POST /discovery/swipe {target_user_id, action: "like"|"pass"}` → `{"matched": bool}`(幂等;互喜才 matched)
  - 失败一律 `{"code": <HTTP码>, "message": "<中文>"}`,前端统一 `ApiException(message)`。
- 中文文案、注释风格、文件组织沿用现有代码;每个任务一个 commit。
- 测试纪律:`Image.network` 必须有 `errorBuilder`,`CircleAvatar` 必须有 `onBackgroundImageError`,否则假网络的 400 会让测试失败。
- 工作分支:`m2b-discovery-matching`;收尾走 superpowers:finishing-a-development-branch。

---

## 文件清单

| 文件 | 动作 | 职责 |
|---|---|---|
| `app/lib/features/discovery/models.dart` | 创建 | `Candidate` 模型(JSON → 对象) |
| `app/lib/features/discovery/discovery_repository.dart` | 创建 | 拉候选 / 提交滑卡(纯 IO) |
| `app/lib/features/discovery/discovery_controller.dart` | 创建 | 卡组状态:加载、移卡、失败放回、自动续拉 |
| `app/lib/features/discovery/widgets/profile_card.dart` | 创建 | 单张候选卡(照片切换 + 资料区) |
| `app/lib/features/discovery/widgets/swipe_deck.dart` | 创建 | 卡组:拖拽手势 + 飞出/弹回动画 + ♥/✕ 按钮 |
| `app/lib/features/discovery/widgets/match_overlay.dart` | 创建 | 配对成功动效(全屏遮罩 + 双方头像) |
| `app/lib/features/discovery/discovery_page.dart` | 重写 | 组装:资料不全 → 引导卡;完善 → 卡组 |
| `app/lib/features/settings/settings_page.dart` | 修改 | 退出登录时顺带清空卡组(别把上一个号的卡留给下一个号) |
| `app/test/support/sample_data.dart` | 修改 | 加 `candidateJson()` 造数据助手 |
| `app/test/features/discovery/discovery_repository_test.dart` | 创建 | 仓库层测试 |
| `app/test/features/discovery/discovery_controller_test.dart` | 创建 | 控制器测试(ProviderContainer) |
| `app/test/features/discovery/profile_card_test.dart` | 创建 | 卡片组件测试 |
| `app/test/features/discovery/swipe_deck_test.dart` | 创建 | 手势/动画测试 |
| `app/test/features/discovery/match_overlay_test.dart` | 创建 | 配对动效测试 |
| `app/test/features/discovery/discovery_page_test.dart` | 创建 | 页面组装 + 端到端 wiring 测试 |

**本计划不做(留给 M2c):** IM SDK 登录、会话列表、聊天页、match_notice 灰条渲染、`GET /matches` 预热缓存、退出登录时的 IM 登出。「对方资料卡 + 举报/拉黑」按 M2a 计划末尾约定留给 M3。

---

### Task 1: Candidate 模型 + DiscoveryRepository

**Files:**
- Create: `app/lib/features/discovery/models.dart`
- Create: `app/lib/features/discovery/discovery_repository.dart`
- Modify: `app/test/support/sample_data.dart`(追加 `candidateJson`)
- Test: `app/test/features/discovery/discovery_repository_test.dart`

**Interfaces:**
- Consumes: `chatapp_app/features/profile/models.dart` 的 `Tag.fromJson` / `Photo.fromJson`;`chatapp_app/core/providers.dart` 的 `apiClientProvider`;`chatapp_app/core/api_client.dart` 的 `ApiClient.get/post`。
- Produces:
  - `class Candidate { int userId; String nickname; int? age; String city; String bio; List<Tag> tags; List<Photo> photos; }` + `Candidate.fromJson(Map<String, dynamic>)`
  - `class DiscoveryRepository { Future<List<Candidate>> fetchCandidates({int limit = 10}); Future<bool> swipe({required int targetUserId, required bool like}); }`
  - `final discoveryRepositoryProvider = Provider<DiscoveryRepository>(...)`
  - 测试助手 `Map<String, dynamic> candidateJson({...})`(放 `app/test/support/sample_data.dart`)

> 说明:`Candidate` **只解析 UI 用得到的字段**(不含 `gender`)——接口里多给的字段不解析,保持模型干净。

- [x] **Step 1: 先加测试数据助手**

在 `app/test/support/sample_data.dart` 末尾追加:

```dart
/// 造一份 GET /discovery/candidates 里的候选;字段可覆盖。
Map<String, dynamic> candidateJson({
  int userId = 9,
  String nickname = '小红',
  int? age = 25,
  String city = '上海',
  String bio = '喜欢爬山',
  List<Map<String, dynamic>> tags = const [],
  List<Map<String, dynamic>>? photos,
}) =>
    {
      'user_id': userId,
      'nickname': nickname,
      'age': age,
      'city': city,
      'bio': bio,
      'tags': tags,
      'photos': photos ?? [photoJson(userId * 100)],
    };
```

- [x] **Step 2: 写失败的仓库层测试**

创建 `app/test/features/discovery/discovery_repository_test.dart`:

```dart
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/api_client.dart';
import 'package:chatapp_app/features/discovery/discovery_repository.dart';

import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

void main() {
  late ScriptedAdapter adapter;
  late DiscoveryRepository repository;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    adapter = ScriptedAdapter({});
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    repository = DiscoveryRepository(ApiClient(dio));
  });

  test('fetchCandidates 解析候选列表并带上 limit', () async {
    adapter.routes['GET /discovery/candidates'] = (options) => ok([
          candidateJson(userId: 9, nickname: '小红', tags: [tagJson(1, '运动')]),
          candidateJson(userId: 10, nickname: '小刚'),
        ]);

    final candidates = await repository.fetchCandidates();

    expect(candidates.map((item) => item.nickname), ['小红', '小刚']);
    expect(candidates.first.userId, 9);
    expect(candidates.first.tags.map((tag) => tag.name), ['运动']);
    expect(candidates.first.photos, hasLength(1));
    expect(adapter.log.last.queryParameters, {'limit': 10});
  });

  test('like → POST 动作是 like,matched 原样返回', () async {
    adapter.routes['POST /discovery/swipe'] = (options) => ok({'matched': true});

    final matched = await repository.swipe(targetUserId: 9, like: true);

    expect(matched, isTrue);
    expect(adapter.log.last.data, {'target_user_id': 9, 'action': 'like'});
  });

  test('pass → POST 动作是 pass', () async {
    adapter.routes['POST /discovery/swipe'] = (options) => ok({'matched': false});

    final matched = await repository.swipe(targetUserId: 10, like: false);

    expect(matched, isFalse);
    expect(adapter.log.last.data, {'target_user_id': 10, 'action': 'pass'});
  });
}
```

- [x] **Step 3: 跑测试确认失败**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/discovery/discovery_repository_test.dart`
Expected: 编译失败,`discovery_repository.dart` / `models.dart` 不存在。

- [x] **Step 4: 实现模型与仓库**

创建 `app/lib/features/discovery/models.dart`:

```dart
// 候选卡片数据;字段与后端 GET /discovery/candidates 的响应一一对应(只取 UI 用得到的)。

import '../profile/models.dart';

class Candidate {
  const Candidate({
    required this.userId,
    required this.nickname,
    required this.age,
    required this.city,
    required this.bio,
    required this.tags,
    required this.photos,
  });

  factory Candidate.fromJson(Map<String, dynamic> json) => Candidate(
        userId: json['user_id'] as int,
        nickname: (json['nickname'] ?? '') as String,
        age: json['age'] as int?,
        city: (json['city'] ?? '') as String,
        bio: (json['bio'] ?? '') as String,
        tags: ((json['tags'] ?? const []) as List<dynamic>)
            .map((item) => Tag.fromJson(item as Map<String, dynamic>))
            .toList(),
        photos: ((json['photos'] ?? const []) as List<dynamic>)
            .map((item) => Photo.fromJson(item as Map<String, dynamic>))
            .toList(),
      );

  final int userId;
  final String nickname;
  final int? age;
  final String city;
  final String bio;
  final List<Tag> tags;
  final List<Photo> photos;
}
```

创建 `app/lib/features/discovery/discovery_repository.dart`:

```dart
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import 'models.dart';

class DiscoveryRepository {
  DiscoveryRepository(this._api);

  final ApiClient _api;

  Future<List<Candidate>> fetchCandidates({int limit = 10}) async {
    final data =
        await _api.get('/discovery/candidates', query: {'limit': limit}) as List<dynamic>;
    return data.map((item) => Candidate.fromJson(item as Map<String, dynamic>)).toList();
  }

  /// 滑一张卡;返回是否配对成功。
  Future<bool> swipe({required int targetUserId, required bool like}) async {
    final data = await _api.post('/discovery/swipe',
        data: {'target_user_id': targetUserId, 'action': like ? 'like' : 'pass'});
    return (data as Map<String, dynamic>)['matched'] == true;
  }
}

final discoveryRepositoryProvider = Provider<DiscoveryRepository>(
    (ref) => DiscoveryRepository(ref.watch(apiClientProvider)));
```

- [x] **Step 5: 跑测试确认通过**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/discovery/discovery_repository_test.dart`
Expected: `All tests passed!`(3 个)

- [x] **Step 6: 提交**

```bash
git add app/lib/features/discovery/models.dart app/lib/features/discovery/discovery_repository.dart app/test/support/sample_data.dart app/test/features/discovery/discovery_repository_test.dart
git commit -m "feat: discovery candidate model + repository (M2b)"
```

---

### Task 2: DiscoveryController 卡组状态

**Files:**
- Create: `app/lib/features/discovery/discovery_controller.dart`
- Test: `app/test/features/discovery/discovery_controller_test.dart`

**Interfaces:**
- Consumes: Task 1 的 `Candidate`、`discoveryRepositoryProvider`(`fetchCandidates({int limit})` / `swipe({required int targetUserId, required bool like})`)。
- Produces: `class DiscoveryController extends AsyncNotifier<List<Candidate>>`:`build()`、`Future<void> reload()`、`Future<bool> decide(Candidate candidate, {required bool like})`;`final discoveryProvider = AsyncNotifierProvider<DiscoveryController, List<Candidate>>(...)`。

> 状态就是「还没滑的候选列表」(`List<Candidate>`,顶层 = `first`),不另外包状态类。
> 行为约定:`decide` 先同步把卡从列表移除(乐观),再调接口;失败把卡放回队首并原样抛异常(页面负责弹提示);成功且剩余 ≤3 张时**不阻塞地**续拉下一批(失败静默,空态里有「刷新」兜底)。

- [x] **Step 1: 写失败的控制器测试**

创建 `app/test/features/discovery/discovery_controller_test.dart`:

```dart
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/api_exception.dart';
import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/discovery/discovery_controller.dart';

import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

void main() {
  late ScriptedAdapter adapter;

  ProviderContainer makeContainer() {
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    final refreshDio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    return ProviderContainer(overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(refreshDio),
    ]);
  }

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    adapter = ScriptedAdapter({});
  });

  test('build 拉第一车候选', () async {
    adapter.routes['GET /discovery/candidates'] =
        (options) => ok([candidateJson(userId: 9), candidateJson(userId: 10)]);
    final container = makeContainer();
    addTearDown(container.dispose);

    final candidates = await container.read(discoveryProvider.future);

    expect(candidates.map((item) => item.userId), [9, 10]);
    expect(adapter.log.last.queryParameters, {'limit': 10});
  });

  test('decide like → 提交后端并移除卡;matched 原样返回', () async {
    var calls = 0;
    adapter.routes['GET /discovery/candidates'] = (options) {
      calls += 1;
      return calls == 1
          ? ok([candidateJson(userId: 9), candidateJson(userId: 10)])
          : ok([]);
    };
    adapter.routes['POST /discovery/swipe'] = (options) => ok({'matched': true});
    final container = makeContainer();
    addTearDown(container.dispose);
    final candidates = await container.read(discoveryProvider.future);

    final matched = await container
        .read(discoveryProvider.notifier)
        .decide(candidates.first, like: true);

    expect(matched, isTrue);
    expect(container.read(discoveryProvider).value!.map((item) => item.userId), [10]);
    final request = adapter.log.lastWhere((item) => item.method == 'POST');
    expect(request.data, {'target_user_id': 9, 'action': 'like'});
  });

  test('decide 失败 → 卡放回队首并抛 ApiException', () async {
    adapter.routes['GET /discovery/candidates'] =
        (options) => ok([candidateJson(userId: 9)]);
    adapter.routes['POST /discovery/swipe'] =
        (options) => jsonError(429, '操作太快了,休息一下吧');
    final container = makeContainer();
    addTearDown(container.dispose);
    final candidates = await container.read(discoveryProvider.future);

    await expectLater(
      container.read(discoveryProvider.notifier).decide(candidates.first, like: true),
      throwsA(isA<ApiException>()),
    );

    expect(container.read(discoveryProvider).value!.map((item) => item.userId), [9]);
  });

  test('滑到剩 3 张自动续拉', () async {
    var calls = 0;
    adapter.routes['GET /discovery/candidates'] = (options) {
      calls += 1;
      return calls == 1
          ? ok(List.generate(4, (index) => candidateJson(userId: 9 + index)))
          : ok([candidateJson(userId: 20)]);
    };
    adapter.routes['POST /discovery/swipe'] = (options) => ok({'matched': false});
    final container = makeContainer();
    addTearDown(container.dispose);
    final candidates = await container.read(discoveryProvider.future);

    await container.read(discoveryProvider.notifier).decide(candidates.first, like: false);
    await pumpEventQueue(); // 续拉是 fire-and-forget,等它跑完

    expect(calls, 2);
    expect(container.read(discoveryProvider).value!.map((item) => item.userId),
        [10, 11, 12, 20]);
  });

  test('卡还多的时候不续拉', () async {
    var calls = 0;
    adapter.routes['GET /discovery/candidates'] = (options) {
      calls += 1;
      return ok(List.generate(10, (index) => candidateJson(userId: 9 + index)));
    };
    adapter.routes['POST /discovery/swipe'] = (options) => ok({'matched': false});
    final container = makeContainer();
    addTearDown(container.dispose);
    final candidates = await container.read(discoveryProvider.future);

    await container.read(discoveryProvider.notifier).decide(candidates.first, like: false);
    await pumpEventQueue();

    expect(calls, 1);
    expect(container.read(discoveryProvider).value, hasLength(9));
  });
}
```

- [x] **Step 2: 跑测试确认失败**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/discovery/discovery_controller_test.dart`
Expected: 编译失败,`discovery_controller.dart` 不存在。

- [x] **Step 3: 实现控制器**

创建 `app/lib/features/discovery/discovery_controller.dart`:

```dart
import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'discovery_repository.dart';
import 'models.dart';

const _batchSize = 10;

/// 卡组剩这么少就开始悄悄续拉。
const _preloadThreshold = 3;

class DiscoveryController extends AsyncNotifier<List<Candidate>> {
  bool _loadingMore = false;

  @override
  Future<List<Candidate>> build() => _fetch();

  Future<List<Candidate>> _fetch() =>
      ref.read(discoveryRepositoryProvider).fetchCandidates(limit: _batchSize);

  Future<void> reload() async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(_fetch);
  }

  /// 处理一次滑卡:先把卡从卡组移除(界面立刻响应),再提交后端。
  /// 失败把卡放回队首并原样抛出(页面弹提示);返回是否配对成功。
  Future<bool> decide(Candidate candidate, {required bool like}) async {
    final current = state.value ?? const <Candidate>[];
    state = AsyncValue.data(
        current.where((item) => item.userId != candidate.userId).toList());
    try {
      final matched = await ref
          .read(discoveryRepositoryProvider)
          .swipe(targetUserId: candidate.userId, like: like);
      unawaited(_preloadIfLow());
      return matched;
    } catch (_) {
      final now = state.value ?? const <Candidate>[];
      state = AsyncValue.data([candidate, ...now]);
      rethrow;
    }
  }

  /// 卡组快见底时续拉下一批;失败不打扰用户(空态里有「刷新」可以重来)。
  Future<void> _preloadIfLow() async {
    final current = state.value;
    if (_loadingMore || current == null || current.length > _preloadThreshold) return;
    _loadingMore = true;
    try {
      final batch = await _fetch();
      final now = state.value;
      if (now != null && batch.isNotEmpty) {
        state = AsyncValue.data([...now, ...batch]);
      }
    } catch (_) {
      // 忽略:下次滑卡会自动再试
    } finally {
      _loadingMore = false;
    }
  }
}

final discoveryProvider = AsyncNotifierProvider<DiscoveryController, List<Candidate>>(
  DiscoveryController.new,
  // Riverpod 3 默认失败重试(200ms 起指数退避);页面已有手动「重试」按钮,关掉更可预期
  retry: (retryCount, error) => null,
);
```

- [x] **Step 4: 跑测试确认通过**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/discovery/discovery_controller_test.dart`
Expected: `All tests passed!`(5 个)

- [x] **Step 5: 提交**

```bash
git add app/lib/features/discovery/discovery_controller.dart app/test/features/discovery/discovery_controller_test.dart
git commit -m "feat: discovery deck controller with optimistic swipe (M2b)"
```

---

### Task 3: ProfileCard 候选资料卡

**Files:**
- Create: `app/lib/features/discovery/widgets/profile_card.dart`
- Test: `app/test/features/discovery/profile_card_test.dart`

**Interfaces:**
- Consumes: Task 1 的 `Candidate`。
- Produces: `class ProfileCard extends StatefulWidget { const ProfileCard({super.key, required Candidate candidate}); }`
- 约定的 Key:`card.photo.{photoId}`(当前显示的照片)、`card.prevPhoto` / `card.nextPhoto`(左右点击区,单张时不存在)、`card.dots`(多张时的圆点,单张时不存在)。

- [x] **Step 1: 写失败的组件测试**

创建 `app/test/features/discovery/profile_card_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/discovery/models.dart';
import 'package:chatapp_app/features/discovery/widgets/profile_card.dart';

import '../../support/sample_data.dart';

Widget _wrap(Candidate candidate) => MaterialApp(
      home: Scaffold(
        body: Center(
          child: SizedBox(width: 360, height: 560, child: ProfileCard(candidate: candidate)),
        ),
      ),
    );

void main() {
  testWidgets('展示昵称、年龄、城市、简介和标签', (tester) async {
    final candidate = Candidate.fromJson(candidateJson(
      nickname: '小红',
      age: 25,
      city: '上海',
      bio: '喜欢爬山',
      tags: [tagJson(1, '运动'), tagJson(2, '音乐')],
    ));

    await tester.pumpWidget(_wrap(candidate));
    await tester.pump();

    expect(find.text('小红,25'), findsOneWidget);
    expect(find.text('上海'), findsOneWidget);
    expect(find.text('喜欢爬山'), findsOneWidget);
    expect(find.text('运动'), findsOneWidget);
    expect(find.text('音乐'), findsOneWidget);
  });

  testWidgets('没有年龄时只显示昵称', (tester) async {
    final candidate = Candidate.fromJson(candidateJson(nickname: '小红', age: null));

    await tester.pumpWidget(_wrap(candidate));
    await tester.pump();

    expect(find.text('小红'), findsOneWidget);
  });

  testWidgets('多张照片:点右侧下一张、点左侧上一张,首尾循环', (tester) async {
    final candidate = Candidate.fromJson(
        candidateJson(photos: [photoJson(1), photoJson(2), photoJson(3)]));

    await tester.pumpWidget(_wrap(candidate));
    await tester.pump();

    expect(find.byKey(const ValueKey('card.photo.1')), findsOneWidget);
    expect(find.byKey(const Key('card.dots')), findsOneWidget);

    await tester.tap(find.byKey(const Key('card.nextPhoto')));
    await tester.pump();
    expect(find.byKey(const ValueKey('card.photo.2')), findsOneWidget);

    await tester.tap(find.byKey(const Key('card.nextPhoto')));
    await tester.pump();
    expect(find.byKey(const ValueKey('card.photo.3')), findsOneWidget);

    await tester.tap(find.byKey(const Key('card.nextPhoto')));
    await tester.pump();
    expect(find.byKey(const ValueKey('card.photo.1')), findsOneWidget); // 循环回第一张

    await tester.tap(find.byKey(const Key('card.prevPhoto')));
    await tester.pump();
    expect(find.byKey(const ValueKey('card.photo.3')), findsOneWidget); // 上一张也是循环
  });

  testWidgets('单张照片:没有切换区也没有圆点', (tester) async {
    final candidate = Candidate.fromJson(candidateJson(photos: [photoJson(1)]));

    await tester.pumpWidget(_wrap(candidate));
    await tester.pump();

    expect(find.byKey(const Key('card.nextPhoto')), findsNothing);
    expect(find.byKey(const Key('card.prevPhoto')), findsNothing);
    expect(find.byKey(const Key('card.dots')), findsNothing);
  });

  testWidgets('一张照片都没有:显示占位图标,不崩', (tester) async {
    final candidate = Candidate.fromJson(candidateJson(photos: []));

    await tester.pumpWidget(_wrap(candidate));
    await tester.pump();

    expect(find.byIcon(Icons.person_outline), findsOneWidget);
  });
}
```

- [x] **Step 2: 跑测试确认失败**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/discovery/profile_card_test.dart`
Expected: 编译失败,`profile_card.dart` 不存在。

- [x] **Step 3: 实现卡片组件**

创建 `app/lib/features/discovery/widgets/profile_card.dart`:

```dart
import 'package:flutter/material.dart';

import '../models.dart';

/// 单张候选卡:照片区(多张时点左右两侧切换)+ 底部资料区。
class ProfileCard extends StatefulWidget {
  const ProfileCard({super.key, required this.candidate});

  final Candidate candidate;

  @override
  State<ProfileCard> createState() => _ProfileCardState();
}

class _ProfileCardState extends State<ProfileCard> {
  int _photoIndex = 0;

  @override
  void didUpdateWidget(covariant ProfileCard oldWidget) {
    super.didUpdateWidget(oldWidget);
    // 换成另一个人的卡了,照片从第一张重新看起
    if (oldWidget.candidate.userId != widget.candidate.userId) _photoIndex = 0;
  }

  void _shiftPhoto(int delta) {
    final count = widget.candidate.photos.length;
    if (count < 2) return;
    setState(() => _photoIndex = (_photoIndex + delta + count) % count);
  }

  @override
  Widget build(BuildContext context) {
    final candidate = widget.candidate;
    final photos = candidate.photos;
    final photo = photos.isEmpty ? null : photos[_photoIndex];
    return Material(
      elevation: 2,
      borderRadius: BorderRadius.circular(16),
      clipBehavior: Clip.antiAlias,
      child: Stack(
        fit: StackFit.expand,
        children: [
          if (photo == null)
            const ColoredBox(
              color: Colors.black12,
              child: Center(child: Icon(Icons.person_outline, size: 64)),
            )
          else
            Image.network(
              photo.url,
              key: ValueKey('card.photo.${photo.id}'),
              fit: BoxFit.cover,
              errorBuilder: (context, error, stack) => const ColoredBox(
                color: Colors.black12,
                child: Center(child: Icon(Icons.broken_image_outlined, size: 48)),
              ),
            ),
          if (photos.length > 1) ...[
            Positioned(
              left: 0,
              top: 0,
              bottom: 0,
              width: 56,
              child: GestureDetector(
                key: const Key('card.prevPhoto'),
                behavior: HitTestBehavior.translucent,
                onTap: () => _shiftPhoto(-1),
              ),
            ),
            Positioned(
              right: 0,
              top: 0,
              bottom: 0,
              width: 56,
              child: GestureDetector(
                key: const Key('card.nextPhoto'),
                behavior: HitTestBehavior.translucent,
                onTap: () => _shiftPhoto(1),
              ),
            ),
            Positioned(
              top: 8,
              left: 0,
              right: 0,
              child: Row(
                key: const Key('card.dots'),
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  for (var i = 0; i < photos.length; i++)
                    Container(
                      width: 8,
                      height: 8,
                      margin: const EdgeInsets.symmetric(horizontal: 3),
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: i == _photoIndex ? Colors.white : Colors.white38,
                      ),
                    ),
                ],
              ),
            ),
          ],
          Positioned(
            left: 0,
            right: 0,
            bottom: 0,
            child: Container(
              padding: const EdgeInsets.fromLTRB(16, 32, 16, 16),
              decoration: const BoxDecoration(
                gradient: LinearGradient(
                  begin: Alignment.topCenter,
                  end: Alignment.bottomCenter,
                  colors: [Colors.transparent, Colors.black87],
                ),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    candidate.age == null
                        ? candidate.nickname
                        : '${candidate.nickname},${candidate.age}',
                    style: const TextStyle(
                        color: Colors.white, fontSize: 22, fontWeight: FontWeight.bold),
                  ),
                  if (candidate.city.isNotEmpty)
                    Text(candidate.city,
                        style: const TextStyle(color: Colors.white70, fontSize: 13)),
                  if (candidate.bio.isNotEmpty) ...[
                    const SizedBox(height: 6),
                    Text(
                      candidate.bio,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(color: Colors.white, fontSize: 14),
                    ),
                  ],
                  if (candidate.tags.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 6,
                      runSpacing: 6,
                      children: [
                        for (final tag in candidate.tags)
                          Container(
                            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                            decoration: BoxDecoration(
                              color: Colors.white24,
                              borderRadius: BorderRadius.circular(12),
                            ),
                            child: Text(tag.name,
                                style: const TextStyle(color: Colors.white, fontSize: 12)),
                          ),
                      ],
                    ),
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

- [x] **Step 4: 跑测试确认通过**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/discovery/profile_card_test.dart`
Expected: `All tests passed!`(5 个)

- [x] **Step 5: 提交**

```bash
git add app/lib/features/discovery/widgets/profile_card.dart app/test/features/discovery/profile_card_test.dart
git commit -m "feat: candidate profile card widget (M2b)"
```

---

### Task 4: SwipeDeck 滑卡手势与飞出动画

**Files:**
- Create: `app/lib/features/discovery/widgets/swipe_deck.dart`
- Test: `app/test/features/discovery/swipe_deck_test.dart`

**Interfaces:**
- Consumes: Task 1 的 `Candidate`、Task 3 的 `ProfileCard`。
- Produces:
  - `typedef DecideCallback = Future<bool> Function(Candidate candidate, {required bool like});`
  - `class SwipeDeck extends StatefulWidget { const SwipeDeck({super.key, required List<Candidate> candidates, required DecideCallback onDecide}); }`
  - Key:`deck.topCard`(顶层卡的拖拽区)、`discovery.pass`(✕)、`discovery.like`(♥)
- 手势约定:水平拖动超过卡宽 **25%** 松手 → 判定滑出;不到 → 弹回不算。`onDecide` 在飞出动画**结束之后**调用,页面在它里面真正调接口;onDecide 的 future 完成后复位。

- [x] **Step 1: 写失败的手势测试**

创建 `app/test/features/discovery/swipe_deck_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/discovery/models.dart';
import 'package:chatapp_app/features/discovery/widgets/swipe_deck.dart';

import '../../support/sample_data.dart';

List<Candidate> _candidates() => [
      Candidate.fromJson(candidateJson(userId: 9, nickname: '小红')),
      Candidate.fromJson(candidateJson(userId: 10, nickname: '小刚')),
      Candidate.fromJson(candidateJson(userId: 11, nickname: '小美')),
    ];

/// 最小宿主:收到滑卡结果就从卡组去掉一张(模仿页面的行为)。
class _Host extends StatefulWidget {
  const _Host({required this.decisions, this.matched = false});

  final List<String> decisions;
  final bool matched;

  @override
  State<_Host> createState() => _HostState();
}

class _HostState extends State<_Host> {
  final List<Candidate> _left = _candidates();

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      home: Scaffold(
        body: SwipeDeck(
          candidates: _left,
          onDecide: (candidate, {required like}) async {
            widget.decisions.add('${candidate.userId}:${like ? 'like' : 'pass'}');
            setState(() => _left.removeAt(0));
            return widget.matched;
          },
        ),
      ),
    );
  }
}

void main() {
  testWidgets('右滑超过阈值 → 判定 like,下一张升为顶层', (tester) async {
    final decisions = <String>[];
    await tester.pumpWidget(_Host(decisions: decisions));
    await tester.pump();

    await tester.drag(find.byKey(const Key('deck.topCard')), const Offset(400, 0));
    await tester.pumpAndSettle();

    expect(decisions, ['9:like']);
    expect(find.text('小红,25'), findsNothing);
    expect(find.text('小刚,25'), findsOneWidget);
  });

  testWidgets('左滑 → 判定 pass', (tester) async {
    final decisions = <String>[];
    await tester.pumpWidget(_Host(decisions: decisions));
    await tester.pump();

    await tester.drag(find.byKey(const Key('deck.topCard')), const Offset(-400, 0));
    await tester.pumpAndSettle();

    expect(decisions, ['9:pass']);
  });

  testWidgets('拖动不到阈值 → 弹回,不算一次滑卡', (tester) async {
    final decisions = <String>[];
    await tester.pumpWidget(_Host(decisions: decisions));
    await tester.pump();

    await tester.drag(find.byKey(const Key('deck.topCard')), const Offset(60, 0));
    await tester.pumpAndSettle();

    expect(decisions, isEmpty);
    expect(find.text('小红,25'), findsOneWidget);
  });

  testWidgets('♥/✕ 按钮等价于滑卡', (tester) async {
    final decisions = <String>[];
    await tester.pumpWidget(_Host(decisions: decisions));
    await tester.pump();

    await tester.tap(find.byKey(const Key('discovery.like')));
    await tester.pumpAndSettle();
    expect(decisions, ['9:like']);

    await tester.tap(find.byKey(const Key('discovery.pass')));
    await tester.pumpAndSettle();
    expect(decisions, ['9:like', '10:pass']);
  });
}
```

- [x] **Step 2: 跑测试确认失败**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/discovery/swipe_deck_test.dart`
Expected: 编译失败,`swipe_deck.dart` 不存在。

- [x] **Step 3: 实现卡组**

创建 `app/lib/features/discovery/widgets/swipe_deck.dart`:

```dart
import 'package:flutter/material.dart';

import '../models.dart';
import 'profile_card.dart';

/// 一次滑卡的处理函数;返回是否配对成功。
typedef DecideCallback = Future<bool> Function(Candidate candidate, {required bool like});

/// 卡组:顶层卡可拖拽,松手超出阈值 → 飞出并回调 [onDecide];没超出 → 弹回。
class SwipeDeck extends StatefulWidget {
  const SwipeDeck({super.key, required this.candidates, required this.onDecide});

  final List<Candidate> candidates;
  final DecideCallback onDecide;

  @override
  State<SwipeDeck> createState() => _SwipeDeckState();
}

class _SwipeDeckState extends State<SwipeDeck> with SingleTickerProviderStateMixin {
  /// 拖过卡宽的多少比例算「滑出去」。
  static const _thresholdFraction = 0.25;

  late final AnimationController _controller =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 250));
  Animation<Offset>? _animation;
  Offset _offset = Offset.zero;
  bool _flying = false;
  int? _flightId;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  void didUpdateWidget(covariant SwipeDeck oldWidget) {
    super.didUpdateWidget(oldWidget);
    // 飞出去的那张已经不在顶层了(列表换人,或父级原地删了它)→ 复位,新卡从居中开始。
    // 只读新列表:老 widget 的列表可能是被父级原地改过的同一个对象,读不得。
    if (_flying && _topId(widget.candidates) != _flightId) {
      _offset = Offset.zero;
      _flying = false;
    }
  }

  static int? _topId(List<Candidate> candidates) =>
      candidates.isEmpty ? null : candidates.first.userId;

  double get _width => MediaQuery.sizeOf(context).width;

  Future<void> _animateTo(Offset target) async {
    _controller.reset();
    final animation = Tween<Offset>(begin: _offset, end: target)
        .animate(CurvedAnimation(parent: _controller, curve: Curves.easeOut));
    _animation = animation;
    animation.addListener(_onTick);
    await _controller.forward();
    animation.removeListener(_onTick);
  }

  void _onTick() => setState(() => _offset = _animation!.value);

  void _onPanUpdate(DragUpdateDetails details) =>
      setState(() => _offset += Offset(details.delta.dx, 0));

  void _onPanEnd(DragEndDetails details) {
    if (_offset.dx.abs() > _width * _thresholdFraction) {
      _flyOut(like: _offset.dx > 0);
    } else {
      _snapBack();
    }
  }

  /// 弹回原位;不算一次滑卡。
  Future<void> _snapBack() async {
    if (_flying) return;
    await _animateTo(Offset.zero);
  }

  /// 飞出屏幕;动画结束后回调 [onDecide](等它返回,失败时卡会被放回来)。
  Future<void> _flyOut({required bool like}) async {
    if (_flying || widget.candidates.isEmpty) return;
    final candidate = widget.candidates.first;
    _flying = true;
    _flightId = candidate.userId;
    await _animateTo(Offset(like ? _width * 1.5 : -_width * 1.5, _offset.dy + 32));
    if (!mounted) return;
    try {
      await widget.onDecide(candidate, like: like);
    } finally {
      // 顶层还是这张(比如滑卡失败被放回)→ 摆回居中;
      // 已经换下一张的话,didUpdateWidget 早就复位过了,这里别碰新卡的状态
      if (mounted && _topId(widget.candidates) == candidate.userId) {
        setState(() {
          _offset = Offset.zero;
          _flying = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final candidates = widget.candidates;
    if (candidates.isEmpty) return const SizedBox.shrink();
    final top = candidates.first;
    final second = candidates.length > 1 ? candidates[1] : null;
    return Column(
      children: [
        Expanded(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
            child: Stack(
              fit: StackFit.expand,
              children: [
                if (second != null)
                  Transform.scale(scale: 0.95, child: ProfileCard(candidate: second)),
                GestureDetector(
                  key: const Key('deck.topCard'),
                  // 必须 opaque:默认 deferToChild 时,照片区没有命中目标,按在照片上拖不动
                  behavior: HitTestBehavior.opaque,
                  onPanUpdate: _flying ? null : _onPanUpdate,
                  onPanEnd: _flying ? null : _onPanEnd,
                  child: Transform.translate(
                    offset: _offset,
                    child: Transform.rotate(
                      angle: _offset.dx / _width * 0.3,
                      child: ProfileCard(candidate: top),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.only(top: 8, bottom: 24),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              IconButton.filledTonal(
                key: const Key('discovery.pass'),
                iconSize: 30,
                onPressed: _flying ? null : () => _flyOut(like: false),
                icon: const Icon(Icons.close),
              ),
              const SizedBox(width: 48),
              IconButton.filled(
                key: const Key('discovery.like'),
                iconSize: 30,
                onPressed: _flying ? null : () => _flyOut(like: true),
                icon: const Icon(Icons.favorite),
              ),
            ],
          ),
        ),
      ],
    );
  }
}
```

- [x] **Step 4: 跑测试确认通过**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/discovery/swipe_deck_test.dart`
Expected: `All tests passed!`(4 个)。
若「弹回」用例偶发不过,检查阈值计算用的 `MediaQuery.sizeOf(context).width`(测试窗口宽 800 → 阈值 200,拖 60 应弹回)与 `pumpAndSettle` 是否等动画放完。

- [x] **Step 5: 提交**

```bash
git add app/lib/features/discovery/widgets/swipe_deck.dart app/test/features/discovery/swipe_deck_test.dart
git commit -m "feat: swipeable card deck with fly-out animation (M2b)"
```

---

### Task 5: MatchOverlay 配对成功动效

**Files:**
- Create: `app/lib/features/discovery/widgets/match_overlay.dart`
- Test: `app/test/features/discovery/match_overlay_test.dart`

**Interfaces:**
- Consumes: Task 1 的 `Candidate`。
- Produces:
  - `class MatchOverlay extends StatelessWidget { const MatchOverlay({super.key, required Candidate candidate, String? myAvatarUrl, required VoidCallback onClose}); }`
  - `Future<void> showMatchOverlay(BuildContext context, {required Candidate candidate, String? myAvatarUrl})` —— 用 `showGeneralDialog` 弹全屏遮罩;等它关闭后 future 才完成(页面 await 它,这样配对动效期间不会继续滑卡)。
  - Key:`match.continue`(继续滑卡按钮)

> 动效 = 整体淡入 + 弹性放大(easeOutBack)。后续 M2c 加了聊天入口后,可在这里补「去聊天」按钮。

- [x] **Step 1: 写失败的组件测试**

创建 `app/test/features/discovery/match_overlay_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/discovery/models.dart';
import 'package:chatapp_app/features/discovery/widgets/match_overlay.dart';

import '../../support/sample_data.dart';

void main() {
  testWidgets('展示文案与头像位;点继续滑卡触发关闭', (tester) async {
    final candidate = Candidate.fromJson(candidateJson(nickname: '小红'));
    var closed = false;

    await tester.pumpWidget(MaterialApp(
      home: MatchOverlay(
        candidate: candidate,
        myAvatarUrl: null,
        onClose: () => closed = true,
      ),
    ));

    expect(find.text('你们已互相喜欢'), findsOneWidget);
    expect(find.text('和 小红 打个招呼吧'), findsOneWidget);
    expect(find.byIcon(Icons.person), findsOneWidget); // 我没头像时的占位
    expect(find.byKey(const Key('match.continue')), findsOneWidget);

    await tester.tap(find.byKey(const Key('match.continue')));
    expect(closed, isTrue);
  });
}
```

- [x] **Step 2: 跑测试确认失败**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/discovery/match_overlay_test.dart`
Expected: 编译失败,`match_overlay.dart` 不存在。

- [x] **Step 3: 实现配对动效**

创建 `app/lib/features/discovery/widgets/match_overlay.dart`:

```dart
import 'package:flutter/material.dart';

import '../models.dart';

/// 配对成功动效:双方头像 + 爱心 + 文案,点「继续滑卡」关闭。
class MatchOverlay extends StatelessWidget {
  const MatchOverlay({
    super.key,
    required this.candidate,
    this.myAvatarUrl,
    required this.onClose,
  });

  final Candidate candidate;
  final String? myAvatarUrl;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    final theirAvatarUrl = candidate.photos.isEmpty ? null : candidate.photos.first.url;
    return Scaffold(
      backgroundColor: Colors.transparent,
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                _Avatar(url: myAvatarUrl, radius: 44),
                Transform.translate(
                  offset: const Offset(-14, 0),
                  child: _Avatar(url: theirAvatarUrl, radius: 44),
                ),
              ],
            ),
            const SizedBox(height: 20),
            const Icon(Icons.favorite, color: Colors.pinkAccent, size: 40),
            const SizedBox(height: 16),
            const Text(
              '你们已互相喜欢',
              style: TextStyle(color: Colors.white, fontSize: 24, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 8),
            Text('和 ${candidate.nickname} 打个招呼吧',
                style: const TextStyle(color: Colors.white70, fontSize: 15)),
            const SizedBox(height: 32),
            FilledButton(
              key: const Key('match.continue'),
              onPressed: onClose,
              child: const Text('继续滑卡'),
            ),
          ],
        ),
      ),
    );
  }
}

class _Avatar extends StatelessWidget {
  const _Avatar({required this.url, required this.radius});

  final String? url;
  final double radius;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        border: Border.all(color: Colors.white, width: 3),
      ),
      child: CircleAvatar(
        radius: radius,
        backgroundColor: Colors.white24,
        backgroundImage: url == null ? null : NetworkImage(url!),
        onBackgroundImageError: url == null ? null : (error, stack) {},
        child: url == null ? const Icon(Icons.person, color: Colors.white, size: 40) : null,
      ),
    );
  }
}

/// 弹配对动效;等它关闭后 future 才完成。
Future<void> showMatchOverlay(
  BuildContext context, {
  required Candidate candidate,
  String? myAvatarUrl,
}) =>
    showGeneralDialog<void>(
      context: context,
      barrierDismissible: false,
      barrierLabel: '配对成功',
      barrierColor: Colors.black.withValues(alpha: 0.85),
      transitionDuration: const Duration(milliseconds: 350),
      pageBuilder: (dialogContext, animation, secondary) => MatchOverlay(
        candidate: candidate,
        myAvatarUrl: myAvatarUrl,
        onClose: () => Navigator.of(dialogContext).pop(),
      ),
      transitionBuilder: (context, animation, secondary, child) => FadeTransition(
        opacity: animation,
        child: ScaleTransition(
          scale: Tween<double>(begin: 0.85, end: 1)
              .animate(CurvedAnimation(parent: animation, curve: Curves.easeOutBack)),
          child: child,
        ),
      ),
    );
```

- [x] **Step 4: 跑测试确认通过**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/discovery/match_overlay_test.dart`
Expected: `All tests passed!`(1 个)

- [x] **Step 5: 提交**

```bash
git add app/lib/features/discovery/widgets/match_overlay.dart app/test/features/discovery/match_overlay_test.dart
git commit -m "feat: match success overlay (M2b)"
```

---

### Task 6: 重写 DiscoveryPage,接入卡组

**Files:**
- Modify(重写): `app/lib/features/discovery/discovery_page.dart`
- Modify: `app/lib/features/settings/settings_page.dart`(退出登录顺带 `ref.invalidate(discoveryProvider)`)
- Test: `app/test/features/discovery/discovery_page_test.dart`

**Interfaces:**
- Consumes: Task 1~5 的全部产出;`profileProvider`(判断资料是否完善、拿自己的头像)。
- Produces: 发现页最终形态。Key:`discovery.goOnboarding`(资料不全的引导,沿用)、`discovery.refresh`(空态刷新)、`discovery.like` / `discovery.pass`(来自 SwipeDeck)、`match.continue`(来自 MatchOverlay)。

- [x] **Step 1: 写失败的页面测试**

创建 `app/test/features/discovery/discovery_page_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

void main() {
  testWidgets('资料完善 → 显示第一张卡;点喜欢发 like 请求并换下一张', (tester) async {
    var calls = 0;
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /discovery/candidates': (options) {
        calls += 1;
        return calls == 1
            ? ok([candidateJson(userId: 9, nickname: '小红'),
                  candidateJson(userId: 10, nickname: '小刚')])
            : ok([]);
      },
      'POST /discovery/swipe': (options) => ok({'matched': false}),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    expect(find.text('小红,25'), findsOneWidget);

    await tester.tap(find.byKey(const Key('discovery.like')));
    await tester.pumpAndSettle();

    final request = adapter.log.lastWhere((item) => item.method == 'POST');
    expect(request.data, {'target_user_id': 9, 'action': 'like'});
    expect(find.text('小红,25'), findsNothing);
    expect(find.text('小刚,25'), findsOneWidget);
  });

  testWidgets('互相喜欢 → 弹配对动效;点继续滑卡回到卡组', (tester) async {
    var calls = 0;
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /discovery/candidates': (options) {
        calls += 1;
        return calls == 1
            ? ok([candidateJson(userId: 9, nickname: '小红'),
                  candidateJson(userId: 10, nickname: '小刚')])
            : ok([]);
      },
      'POST /discovery/swipe': (options) => ok({'matched': true}),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('discovery.like')));
    await tester.pumpAndSettle();

    expect(find.text('你们已互相喜欢'), findsOneWidget);
    expect(find.text('和 小红 打个招呼吧'), findsOneWidget);

    await tester.tap(find.byKey(const Key('match.continue')));
    await tester.pumpAndSettle();

    expect(find.text('你们已互相喜欢'), findsNothing);
    expect(find.text('小刚,25'), findsOneWidget);
  });

  testWidgets('没有候选 → 空态;点刷新重新拉', (tester) async {
    var calls = 0;
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /discovery/candidates': (options) {
        calls += 1;
        return calls == 1 ? ok([]) : ok([candidateJson(userId: 9, nickname: '小红')]);
      },
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    expect(find.text('附近暂时没有新的人了'), findsOneWidget);

    await tester.tap(find.byKey(const Key('discovery.refresh')));
    await tester.pumpAndSettle();

    expect(find.text('小红,25'), findsOneWidget);
  });

  testWidgets('拉候选失败 → 显示错误并能重试', (tester) async {
    var calls = 0;
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /discovery/candidates': (options) {
        calls += 1;
        return calls == 1
            ? jsonError(500, '服务器开小差了')
            : ok([candidateJson(userId: 9, nickname: '小红')]);
      },
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    expect(find.textContaining('服务器开小差了'), findsOneWidget);

    await tester.tap(find.text('重试'));
    await tester.pumpAndSettle();

    expect(find.text('小红,25'), findsOneWidget);
  });

  testWidgets('滑卡失败 → 提示错误且卡片回到队首', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /discovery/candidates': (options) => ok([candidateJson(userId: 9, nickname: '小红')]),
      'POST /discovery/swipe': (options) => jsonError(429, '操作太快了,休息一下吧'),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('discovery.like')));
    await tester.pumpAndSettle();

    expect(find.text('操作太快了,休息一下吧'), findsOneWidget);
    expect(find.text('小红,25'), findsOneWidget);
  });
}
```

- [x] **Step 2: 跑测试确认失败**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/discovery/discovery_page_test.dart`
Expected: 失败——现在发现页还是「卡片流开发中」占位,找不到 `小红,25`。

- [x] **Step 3: 重写发现页**

把 `app/lib/features/discovery/discovery_page.dart` 整体替换为:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../profile/models.dart';
import '../profile/profile_controller.dart';
import 'discovery_controller.dart';
import 'models.dart';
import 'widgets/match_overlay.dart';
import 'widgets/swipe_deck.dart';

class DiscoveryPage extends ConsumerWidget {
  const DiscoveryPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final profile = ref.watch(profileProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('发现')),
      body: profile.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text('$error'),
              FilledButton(
                onPressed: () => ref.read(profileProvider.notifier).reload(),
                child: const Text('重试'),
              ),
            ],
          ),
        ),
        data: (data) => data.isComplete
            ? const _DeckView()
            : _IncompleteView(profile: data),
      ),
    );
  }
}

/// 资料不全时不能滑卡,先把人引去向导。
class _IncompleteView extends StatelessWidget {
  const _IncompleteView({required this.profile});

  final Profile profile;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Card(
        margin: const EdgeInsets.all(24),
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text('完善资料后就能开始滑卡'),
              const SizedBox(height: 8),
              Text('还差:${profile.missingFields.map(missingFieldLabel).join('、')}'),
              const SizedBox(height: 16),
              FilledButton(
                key: const Key('discovery.goOnboarding'),
                onPressed: () => context.go('/onboarding'),
                child: const Text('去完善'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _DeckView extends ConsumerWidget {
  const _DeckView();

  Future<bool> _decide(BuildContext context, WidgetRef ref, Candidate candidate,
      {required bool like}) async {
    try {
      final matched =
          await ref.read(discoveryProvider.notifier).decide(candidate, like: like);
      if (matched && context.mounted) {
        final me = ref.read(profileProvider).value;
        await showMatchOverlay(context,
            candidate: candidate, myAvatarUrl: me?.avatar?.url);
      }
      return matched;
    } on ApiException catch (error) {
      if (context.mounted) {
        ScaffoldMessenger.of(context)
          ..hideCurrentSnackBar()
          ..showSnackBar(SnackBar(content: Text(error.message)));
      }
      return false;
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final deck = ref.watch(discoveryProvider);
    return deck.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (error, _) => Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('$error'),
            FilledButton(
              onPressed: () => ref.read(discoveryProvider.notifier).reload(),
              child: const Text('重试'),
            ),
          ],
        ),
      ),
      data: (candidates) => candidates.isEmpty
          ? _EmptyView(
              onRefresh: () => ref.read(discoveryProvider.notifier).reload())
          : SwipeDeck(
              candidates: candidates,
              onDecide: (candidate, {required like}) =>
                  _decide(context, ref, candidate, like: like),
            ),
    );
  }
}

class _EmptyView extends StatelessWidget {
  const _EmptyView({required this.onRefresh});

  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.people_outline, size: 48),
          const SizedBox(height: 12),
          const Text('附近暂时没有新的人了'),
          const SizedBox(height: 4),
          const Text('过会儿再来看看吧',
              style: TextStyle(color: Colors.black54, fontSize: 13)),
          const SizedBox(height: 16),
          FilledButton(
            key: const Key('discovery.refresh'),
            onPressed: onRefresh,
            child: const Text('刷新'),
          ),
        ],
      ),
    );
  }
}
```

- [x] **Step 4: 退出登录时顺手清空卡组**

修改 `app/lib/features/settings/settings_page.dart`:导入并加一行(和第 24 行的 profile 清理同理):

```dart
import '../auth/session.dart';
import '../discovery/discovery_controller.dart';
import '../profile/profile_controller.dart';
```

```dart
    await ref.read(sessionProvider.notifier).logout();
    ref.invalidate(profileProvider); // 别把上一个账号的资料留给下一个
    ref.invalidate(discoveryProvider); // 也别把上一个账号的卡组留给下一个
```

- [x] **Step 5: 跑新页面测试 + 全量回归**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/discovery`
Expected: 全部通过(仓库 3 + 控制器 5 + 卡片 5 + 卡组 4 + 动效 1 + 页面 5)。

Run: `cd app && ../flutter/bin/flutter.bat test`
Expected: 全绿 —— M2a 的 37 个 + M2b 的 23 个 = **60 个**。
（`home_shell_test` 不用改:它的第一条用例资料是完善的,发现页会去拉候选,假网络没铺这条路由 → 页面进错误态,但用例只断言 Tab 和「我的」页,不受影响。)

Run: `cd app && ../flutter/bin/flutter.bat analyze`
Expected: `No issues found!`

- [x] **Step 6: 提交**

```bash
git add app/lib/features/discovery/discovery_page.dart app/lib/features/settings/settings_page.dart app/test/features/discovery/discovery_page_test.dart
git commit -m "feat: discovery page with card deck and match overlay (M2b)"
```

---

### Task 7: 文档、回归与收尾

**Files:**
- Modify: `CLAUDE.md`(进度、前端踩坑小节)
- Modify: `docs/superpowers/plans/2026-09-10-m2b-discovery-matching.md`(勾 checkbox、补执行偏差)

- [x] **Step 1: 后端回归(接口没动,确认没被误伤)**

Run: `cd chatapp && python manage.py test`
Expected: `Ran 91 tests ... OK`

- [x] **Step 2: 更新 CLAUDE.md**

改动点:
1. 「当前进度」段:`M2b 已完成`(发现卡片流:候选批量拉取/拖拽与按钮滑卡/自动续拉/配对动效;前端 XX 测试全绿 + analyze 零告警,后端 91 回归通过);下一步改 M2c。
2. 文档清单加 M2b 计划文件。
3. 「前端约定与踩坑(M2a 已实测)」小节追加(或新开「M2b 已实测」):
   - 卡组在 `features/discovery/widgets/`(SwipeDeck 自绘手势,没引第三方包);拖过屏宽 25% 判滑出
   - `DiscoveryController` 乐观移卡、失败放回;剩 ≤3 张自动续拉
   - 测试里网络图片必须 `errorBuilder` / `onBackgroundImageError`(假网络对图片一律 400)
   - 断言请求别用 `adapter.log.last`——自动续拉的 GET 可能排在滑卡 POST 后面,用 `lastWhere((r) => r.method == 'POST')`

- [x] **Step 3: 勾计划 checkbox 并记录偏差**

把本文件每个 Task 的 `- [x]` 改成 `- [x]`;若执行中改了计划里的代码,把「实际怎么改的 + 为什么」补在该 Task 末尾。

- [x] **Step 4: 提交**

```bash
git add CLAUDE.md docs/superpowers/plans/2026-09-10-m2b-discovery-matching.md
git commit -m "docs: M2b done — discovery deck + match overlay (M2b)"
```

- [x] **Step 5: 收尾**

用 superpowers:finishing-a-development-branch:全量测试(前端 `flutter test` + 后端 `python manage.py test`)→ 给用户出「合并/PR/保留」选项。

---

## 手测清单(模拟器,核心链路优先)

前置:后端 `python manage.py runserver`;dev 库里要有**两个资料完善且有已过审照片**的账号(A、B)——只有一个号时先注册第二个并走完 3 步引导。

- [x] A 登录 → 发现页出现卡片(照片/昵称,年龄/城市/简介/标签)
- [x] 用手指把卡片往右拖到底 → 卡片飞出;下一张顶上来;按钮区 ♥/✕ 同样有效
- [x] 拖一点点松手 → 卡片弹回原位,不计数
- [x] 退出 A、登录 B → 对 A 点 ♥ → 弹配对动效(双方头像 + 「你们已互相喜欢」)→ 点「继续滑卡」回到卡组
- [x] (可选)把所有候选划完 → 空态「附近暂时没有新的人了」+ 刷新后能重新出现(需要没有互滑过的人)

---

## 卡点速查

| 现象 | 原因/处理 |
|---|---|
| 拖着卡片没反应 / 拖拽用例不触发 | `GestureDetector` 默认 `deferToChild`,照片区没有任何命中目标时收不到手势 → 顶层卡必须 `behavior: HitTestBehavior.opaque` |
| 测试报 `Invalid statusCode: 400` | 假网络里 `Image.network` 没挂 `errorBuilder` / `CircleAvatar` 没挂 `onBackgroundImageError` |
| `adapter.log.last` 断言不稳 | 自动续拉的 GET 排在滑卡 POST 后面 → 用 `lastWhere((r) => r.method == 'POST')` |
| 测试窗口宽度 | widget 测试默认 800×600,拖拽阈值 = 200px;拖 400 算滑出,拖 60 算弹回 |
| 假网络没铺路由 | `ScriptedAdapter` 会对未铺路由返回 404,并把提示写进 message,一眼能看出来 |
| Riverpod 3.4 | 用 `.value`(可空),没有 `valueOrNull` |
| 模拟器看不到候选 | 确认 dev 库还有「资料完善 + 有已过审照片」的他人,并且没被当前账号划过/配过 |
| 命令 | 都在 `app/` 下:`../flutter/bin/flutter.bat test`(不要用系统 flutter) |

---

## 执行记录(2026-09-10,与计划的偏差)

1. **Task 4 的 `didUpdateWidget` 改了判定方式**:原计划比较 `oldWidget.candidates` 与 `widget.candidates` 的顶层 id,但当父级**原地改列表**(测试宿主 `removeAt`,或将来某个页面复用同一个 List 对象)时,旧 widget 引用的是同一个被改过的对象,判定失效 → 飞出后 `_flying` 卡在 true,按钮全禁用。改为 `_flying && _topId(widget.candidates) != _flightId`(只读新列表 + 记住飞出卡 id),两种父级行为都稳。
2. **Task 6 给 `discoveryProvider` 关了 Riverpod 自动重试**:Riverpod 3 默认对 build 失败的 provider 自动重试(200ms 起指数退避,`ProviderContainer.defaultRetry`),测试里 `pumpAndSettle` 会把时间推过重试点,第二次请求成功后错误界面被卡片顶掉 → 「拉候选失败」用例断言不到错误文案。页面本来就有手动「重试」按钮,`retry: (retryCount, error) => null` 关掉,行为可预期。
3. **swipe_deck_test 宿主去掉了没用到的 `matched` 参数**(analyzer `unused_element_parameter` 告警,analyze 要求零告警)。

最终状态:前端 60 测试全绿(`flutter test`)+ analyze 零告警;后端 91 测试回归 OK;CLAUDE.md 已更新。

---

## 留给 M2c 的接口约定

| 事项 | 约定 |
|---|---|
| IM 登录时机 | 登录成功与启动鉴权成功后,用 `POST /im/user_sig` 拿 userSig 登录 IM(`u{userId}`) |
| 会话缓存 | `GET /matches` 预热 `userId → 昵称/头像`;配对成功时可再刷一次 |
| 灰条消息 | `TIMCustomElem`,`Data = {"type":"match_notice"}`;聊天页拦成居中灰条 |
| 配对动效入口 | 本计划的 `showMatchOverlay` 在 M2c 可加「去聊天」按钮(跳到聊天页) |
| 退出登录 | 现在只清 JWT + profile/卡组;M2c 必须补 IM 登出(防串号) |
| 会话过期踢回登录 | `TokenStore.clear()` → `SessionController` 这一条通道;M2c 的 IM 状态清理也挂在这条生命周期上 |
