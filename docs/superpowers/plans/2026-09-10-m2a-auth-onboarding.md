# M2a 前端基建 + 登录 + 资料引导实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Flutter 端从 M0 握手页升级为可用的 App 骨架:启动鉴权、手机号验证码登录(自动注册)、多步资料引导(昵称/性别/生日/城市/简介/标签/照片)、主框架三 Tab(发现/会话/我的)、我的资料查看与编辑、偏好设置、退出登录。全部离线可测(假网络),并在 Android 模拟器上连真后端跑通。

**Architecture:** 三层:repository(纯 IO,把 JSON 解析成模型)→ Riverpod controller(会话/资料状态)→ widget(页面)。网络层一个 Dio(JWT 拦截器:401 静默刷新一次后重放,刷新失败清凭证)+ 一个**裸 Dio** 专用于刷新(避免递归)。`TokenStore.clear()` 会发通知,`SessionController` 监听它把状态踢回未登录 —— 这是"会话过期 → 回登录页"的唯一通道,不需 401 层层上报。路由用 go_router,`redirect` 按会话状态决定 splash/登录/主框架。资料引导是 3 步 PageView 向导,每步"下一步"即 PATCH 落库;表单字段部件与"编辑资料"页共用。

**Tech Stack:** Flutter 3.47.2(Dart 3.13)、flutter_riverpod、go_router、dio(已有)、shared_preferences、image_picker、flutter_localizations(中文日期选择器)。后端零改动(M1 接口已就绪)。

**范围边界:**
- 本计划**不做**(留给 M2b):卡片流(发现 Tab 里是占位+引导卡)、配对动效、IM SDK 接入、会话列表、聊天页、未读角标。
- 本计划**不做**:举报/拉黑入口(随 M3)。
- 本计划**不改后端**;若发现接口真的缺字段,先记录再单独处理,不要顺手改 `chatapp/`。
- 会话过期时 IM 登出、切换账号全清(spec §7.5)在 M2c 接入 IM 时落地;本计划只保证 JWT 层面干净。

## Global Constraints

- Windows Git Bash;Flutter 命令 cwd = `D:\pycharmproject\chat_app\app`,一律用 `../flutter/bin/flutter.bat`;`flutter/`(SDK)与 `chatapp/`(后端)本阶段勿动
- 每个 Task 走 TDD:先写失败测试 → 跑红 → 最小实现 → 跑绿 → `git commit`,消息格式 `feat: ... (M2a)` / `chore: ... (M2a)`
- 完成线:`../flutter/bin/flutter.bat analyze` **零告警** + `../flutter/bin/flutter.bat test` **全绿**
- **测试禁止真实网络**:一律用 `ScriptedAdapter`(按 `"METHOD path"` 铺响应并记录请求);测试里不得出现 http 地址的真实请求
- 接口约定沿用 M1:成功 2xx + JSON;失败 `{"code": <状态码>, "message": "<中文>"}`;鉴权 `Authorization: Bearer <access>`
- 后端错误一律转成 `ApiException`(message 可直接展示);`JWT.user_id` 是字符串,前端要在意时先 `int()`
- 界面全中文;主题 Material 3 + 粉色种子色;日期展示/传输一律 `YYYY-MM-DD`
- `--dart-define=API_BASE=...` 指定后端;模拟器用 `http://10.0.2.2:8000/api/v1`,桌面/Web 默认 `http://127.0.0.1:8000/api/v1`
- 用户是 Flutter 新手:每步给命令与预期输出;踩坑记进「卡点速查」
- 建议分支:`m2a-auth-onboarding`(从 master 切出,收尾后 fast-forward 合回)

---

### Task 1: 依赖与 core 基础设施

**Files:**
- Modify: `app/pubspec.yaml`(加依赖)
- Create: `app/lib/core/config.dart`、`app/lib/core/api_exception.dart`、`app/lib/core/token_store.dart`、`app/lib/app.dart`
- Modify: `app/lib/main.dart`(重写为 ProviderScope 入口)
- Delete: `app/test/widget_test.dart`(M0 握手页测试,页面即将不复存在)
- Test: `app/test/core/api_exception_test.dart`、`app/test/core/token_store_test.dart`

**Interfaces:**
- Consumes: 无。
- Produces:
  - `core/config.dart` → `const String apiBase`(读 `--dart-define=API_BASE`)
  - `core/api_exception.dart` → `ApiException(message, {statusCode})` + `ApiException.from(Object error)`
  - `core/token_store.dart` → `TokenStore extends ChangeNotifier`:`save({access, refresh, userId})` / `saveTokens({access, refresh})` / `clear()`(会 `notifyListeners()`) / `accessToken` / `refreshToken` / `userId`
  - `app.dart` → `ChatApp`(先是无路由占位,Task 3 换成 `MaterialApp.router`)

- [ ] **Step 1:加依赖**

```bash
cd "D:/pycharmproject/chat_app/app" && ../flutter/bin/flutter.bat pub add flutter_riverpod go_router shared_preferences image_picker
```

再手动编辑 `app/pubspec.yaml`,在 `dependencies:` 下 `dio` 附近加(中文日期选择器用):

```yaml
  flutter_localizations:
    sdk: flutter
```

```bash
../flutter/bin/flutter.bat pub get
```

预期:两个命令都输出 `Changed ... dependencies!` / `Got dependencies!`。**记下 pub 解析出的 flutter_riverpod 大版本**(`grep -A1 flutter_riverpod pubspec.yaml`)——若解析到 3.x 而某段代码编译不过,以编译器报错为准微调,并在本计划「卡点速查」补记。

- [ ] **Step 2:写失败的测试**

新建 `app/test/core/api_exception_test.dart`:

```dart
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/api_exception.dart';

void main() {
  test('把后端的 {code,message} 取成中文提示', () {
    final error = DioException(
      requestOptions: RequestOptions(path: '/users/me'),
      response: Response(
        requestOptions: RequestOptions(path: '/users/me'),
        statusCode: 403,
        data: {'code': 403, 'message': '账号已被限制,暂时无法滑卡'},
      ),
      type: DioExceptionType.badResponse,
    );
    final apiError = ApiException.from(error);
    expect(apiError.message, '账号已被限制,暂时无法滑卡');
    expect(apiError.statusCode, 403);
  });

  test('网络不通时给统一中文提示', () {
    final error = DioException(
      requestOptions: RequestOptions(path: '/health'),
      type: DioExceptionType.connectionError,
      error: 'offline',
    );
    expect(ApiException.from(error).message, '网络不给力,请检查网络后重试');
  });

  test('已经是 ApiException 就原样返回', () {
    final original = ApiException('原样', statusCode: 400);
    expect(ApiException.from(original), same(original));
  });
}
```

新建 `app/test/core/token_store_test.dart`:

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/token_store.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('存取与清空', () async {
    final store = TokenStore();
    await store.save(access: 'a1', refresh: 'r1', userId: 7);
    expect(await store.accessToken, 'a1');
    expect(await store.refreshToken, 'r1');
    expect(await store.userId, 7);

    await store.saveTokens(access: 'a2', refresh: 'r2');
    expect(await store.accessToken, 'a2');
    expect(await store.refreshToken, 'r2');

    await store.clear();
    expect(await store.accessToken, isNull);
    expect(await store.refreshToken, isNull);
    expect(await store.userId, isNull);
  });

  test('clear 会通知监听者(会话过期的传播通道)', () async {
    final store = TokenStore();
    var notified = 0;
    store.addListener(() => notified++);
    await store.clear();
    expect(notified, 1);
  });
}
```

- [ ] **Step 3:运行确认失败**

```bash
cd "D:/pycharmproject/chat_app/app" && ../flutter/bin/flutter.bat test test/core
```

预期:编译失败 / `Target of URI doesn't exist: 'package:chatapp_app/core/api_exception.dart'`。

- [ ] **Step 4:实现 core**

新建 `app/lib/core/config.dart`:

```dart
/// 后端地址;运行时用 --dart-define=API_BASE=... 覆盖。
/// 模拟器里宿主机回环是 http://10.0.2.2:8000/api/v1。
const String apiBase = String.fromEnvironment('API_BASE',
    defaultValue: 'http://127.0.0.1:8000/api/v1');
```

新建 `app/lib/core/api_exception.dart`:

```dart
import 'package:dio/dio.dart';

/// 统一的接口错误:message 一定是可直接展示给用户的中文。
class ApiException implements Exception {
  ApiException(this.message, {this.statusCode});

  /// 把任意异常翻译成 ApiException;后端错误体固定是 {code, message}。
  factory ApiException.from(Object error) {
    if (error is ApiException) return error;
    if (error is DioException) {
      final response = error.response;
      final data = response?.data;
      if (data is Map && data['message'] is String) {
        return ApiException(data['message'] as String,
            statusCode: response?.statusCode);
      }
      switch (error.type) {
        case DioExceptionType.connectionTimeout:
        case DioExceptionType.sendTimeout:
        case DioExceptionType.receiveTimeout:
        case DioExceptionType.connectionError:
          return ApiException('网络不给力,请检查网络后重试');
        default:
          return ApiException('请求失败,请稍后再试');
      }
    }
    return ApiException('出错了,请稍后再试');
  }

  final String message;
  final int? statusCode;

  @override
  String toString() => 'ApiException($statusCode): $message';
}
```

新建 `app/lib/core/token_store.dart`:

```dart
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 本地凭证存取。凭证被清掉 = 会话结束:
/// clear() 会通知监听者,SessionController 靠这个信号把界面踢回登录页。
class TokenStore extends ChangeNotifier {
  static const _accessKey = 'auth.access';
  static const _refreshKey = 'auth.refresh';
  static const _userIdKey = 'auth.user_id';

  Future<void> save(
      {required String access, required String refresh, required int userId}) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_accessKey, access);
    await prefs.setString(_refreshKey, refresh);
    await prefs.setInt(_userIdKey, userId);
  }

  Future<void> saveTokens({required String access, required String refresh}) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_accessKey, access);
    await prefs.setString(_refreshKey, refresh);
  }

  Future<void> clear() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_accessKey);
    await prefs.remove(_refreshKey);
    await prefs.remove(_userIdKey);
    notifyListeners();
  }

  Future<String?> get accessToken async =>
      (await SharedPreferences.getInstance()).getString(_accessKey);

  Future<String?> get refreshToken async =>
      (await SharedPreferences.getInstance()).getString(_refreshKey);

  Future<int?> get userId async =>
      (await SharedPreferences.getInstance()).getInt(_userIdKey);
}
```

- [ ] **Step 5:换成新入口**

重写 `app/lib/main.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app.dart';

void main() {
  runApp(const ProviderScope(child: ChatApp()));
}
```

新建 `app/lib/app.dart`(Task 3 会把它换成带路由的版本):

```dart
import 'package:flutter/material.dart';

class ChatApp extends StatelessWidget {
  const ChatApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '交友 Chat',
      theme: ThemeData(colorSchemeSeed: Colors.pink, useMaterial3: true),
      home: const Scaffold(body: Center(child: Text('M2a 开发中'))),
    );
  }
}
```

删除 `app/test/widget_test.dart`(它测的 M0 握手页已不存在)。

- [ ] **Step 6:运行测试确认通过**

```bash
../flutter/bin/flutter.bat test test/core && ../flutter/bin/flutter.bat analyze
```

预期:5 个用例 OK;analyze `No issues found!`。

- [ ] **Step 7:提交**

```bash
cd "D:/pycharmproject/chat_app" && git add app && git commit -m "feat: flutter deps + core (config/error/token store) (M2a)"
```

**卡点速查:**
- `pub add` 卡住 → 换 `PUB_HOSTED_URL=https://pub.flutter-io.cn` 临时重试(会把镜像写进 lock,完事记得改回并重新 `pub get`)
- analyzer 抱怨 `flutter_localizations` 与 `intl` 冲突 → 以 `flutter pub get` 的解析结果为准,不要手动钉 intl

---

### Task 2: Dio 鉴权拦截器 + ApiClient

**Files:**
- Create: `app/lib/core/token_refresher.dart`、`app/lib/core/auth_interceptor.dart`、`app/lib/core/providers.dart`、`app/test/support/scripted_adapter.dart`、`app/test/core/auth_interceptor_test.dart`
- Rewrite: `app/lib/core/api_client.dart`
- Delete: `app/test/api_client_test.dart`、`app/test/fake_adapter.dart`(被 ScriptedAdapter 取代)

**Interfaces:**
- Consumes: Task 1 的 `TokenStore`、`ApiException`、`apiBase`。
- Produces:
  - `core/token_refresher.dart` → `TokenRefresher({dio, tokenStore})`;`Future<String?> refresh()`(单飞:并发 401 只打一次刷新;返回新 access 或 null;失败抛 `ApiException`,401 = refresh 已失效)
  - `core/auth_interceptor.dart` → `AuthInterceptor({tokenStore, refresher})` 挂在 Dio 上
  - `core/api_client.dart` → `ApiClient(dio)`;`get(path, {query})` / `post(path, {data})` / `patch(path, {data})` / `delete(path)`,统一抛 `ApiException`
  - `core/providers.dart` → `tokenStoreProvider` / `baseDioProvider` / `refreshDioProvider` / `tokenRefresherProvider` / `apiClientProvider`
  - `test/support/scripted_adapter.dart` → `ScriptedAdapter(routes)`(带 `log`)、`ok(body, {status})`、`fail(status, [message])`、`offline(options)`

**为什么要有"裸 Dio":** 刷新 token 的请求如果也过同一个拦截器,refresh 也 401 时会无限递归。单开一个不带拦截器的 Dio 只干刷新这一件事。

- [ ] **Step 1:写测试基建与失败的测试**

新建 `app/test/support/scripted_adapter.dart`:

```dart
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';

typedef Responder = Future<ResponseBody> Function(RequestOptions options);

/// 测试用假网络:按 `"METHOD path"` 铺响应,并记录所有请求(options.path 是相对路径,
/// 例:'POST /auth/sms/verify')。没铺的路由返回 404,方便一眼看出漏铺。
class ScriptedAdapter implements HttpClientAdapter {
  ScriptedAdapter(this.routes);

  final Map<String, Responder> routes;
  final List<RequestOptions> log = [];

  @override
  Future<ResponseBody> fetch(RequestOptions options, Stream<Uint8List>? requestStream,
      Future<void>? cancelFuture) {
    log.add(options);
    final responder = routes['${options.method} ${options.path}'];
    if (responder == null) {
      return ok({'code': 404, 'message': '测试没铺这条路由: ${options.method} ${options.path}'},
          status: 404);
    }
    return responder(options);
  }

  @override
  void close({bool force = false}) {}
}

const Map<String, List<String>> _jsonHeaders = {
  Headers.contentTypeHeader: [Headers.jsonContentType],
};

Future<ResponseBody> ok(Object body, {int status = 200}) async =>
    ResponseBody.fromString(jsonEncode(body), status, headers: _jsonHeaders);

Future<ResponseBody> fail(int status, [String message = '出错了']) async =>
    ResponseBody.fromString(jsonEncode({'code': status, 'message': message}), status,
        headers: _jsonHeaders);

Future<ResponseBody> offline(RequestOptions options) =>
    throw DioException.connectionError(requestOptions: options, reason: 'offline');
```

新建 `app/test/core/auth_interceptor_test.dart`:

```dart
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/api_client.dart';
import 'package:chatapp_app/core/api_exception.dart';
import 'package:chatapp_app/core/auth_interceptor.dart';
import 'package:chatapp_app/core/token_refresher.dart';
import 'package:chatapp_app/core/token_store.dart';

import '../support/scripted_adapter.dart';

void main() {
  late TokenStore store;
  late ScriptedAdapter adapter;
  late ApiClient client;

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    store = TokenStore();
    await store.save(access: 'old-access', refresh: 'refresh-1', userId: 1);
    adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'new-access', 'refresh': 'refresh-2'}),
    });
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    final refreshDio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    dio.interceptors.add(AuthInterceptor(
      tokenStore: store,
      refresher: TokenRefresher(dio: refreshDio, tokenStore: store),
    ));
    client = ApiClient(dio);
  });

  test('请求自动带上 Authorization', () async {
    adapter.routes['GET /users/me'] = (options) => ok({'nickname': '小明'});
    expect(await client.get('/users/me'), {'nickname': '小明'});
    expect(adapter.log.last.headers['Authorization'], 'Bearer old-access');
  });

  test('401 → 静默刷新 → 用新 token 重放一次', () async {
    var attempts = 0;
    adapter.routes['GET /users/me'] = (options) {
      attempts++;
      if (options.headers['Authorization'] == 'Bearer new-access') {
        return ok({'nickname': '小明'});
      }
      return fail(401, '身份认证信息未提供');
    };
    expect(await client.get('/users/me'), {'nickname': '小明'});
    expect(attempts, 2);
    expect(await store.accessToken, 'new-access');
    expect(await store.refreshToken, 'refresh-2');
  });

  test('刷新也被拒 → 清空凭证并抛原始错误', () async {
    adapter.routes['POST /auth/token/refresh'] = (options) => fail(401, 'Token 无效或已过期');
    adapter.routes['GET /users/me'] = (options) => fail(401, '身份认证信息未提供');
    await expectLater(client.get('/users/me'), throwsA(isA<ApiException>()));
    expect(await store.accessToken, isNull);
    expect(await store.refreshToken, isNull);
  });

  test('非 401 错误原样抛出,不触发刷新', () async {
    adapter.routes['GET /users/me'] = (options) => fail(500, '服务器开小差了');
    await expectLater(
      client.get('/users/me'),
      throwsA(predicate((error) => error is ApiException && error.message == '服务器开小差了')),
    );
    expect(adapter.log.where((r) => r.path == '/auth/token/refresh'), isEmpty);
  });
}
```

- [ ] **Step 2:运行确认失败**

```bash
../flutter/bin/flutter.bat test test/core/auth_interceptor_test.dart
```

预期:编译失败(`auth_interceptor.dart` / `token_refresher.dart` 不存在)。

- [ ] **Step 3:实现**

新建 `app/lib/core/token_refresher.dart`:

```dart
import 'package:dio/dio.dart';

import 'api_exception.dart';
import 'token_store.dart';

/// 用 refresh token 换新 access(服务端同时轮换 refresh)。
/// 单飞:并发的 401 只打一次刷新接口,大家共用同一个 Future。
class TokenRefresher {
  TokenRefresher({required this.dio, required this.tokenStore});

  /// 必须是**不带 AuthInterceptor** 的裸 Dio,否则刷新 401 会递归。
  final Dio dio;
  final TokenStore tokenStore;

  Future<String?>? _inFlight;

  /// 成功 → 新 access;没有 refresh token → null;刷新被拒/网络失败 → 抛 ApiException。
  Future<String?> refresh() => _inFlight ??= _refresh().whenComplete(() => _inFlight = null);

  Future<String?> _refresh() async {
    final refreshToken = await tokenStore.refreshToken;
    if (refreshToken == null) return null;

    final Response<dynamic> response;
    try {
      response = await dio.post<dynamic>('/auth/token/refresh', data: {'refresh': refreshToken});
    } on DioException catch (error) {
      throw ApiException.from(error);
    }

    final data = response.data as Map<String, dynamic>;
    final access = data['access'] as String;
    final rotated = data['refresh'] as String? ?? refreshToken;
    await tokenStore.saveTokens(access: access, refresh: rotated);
    return access;
  }
}
```

新建 `app/lib/core/auth_interceptor.dart`:

```dart
import 'package:dio/dio.dart';

import 'api_exception.dart';
import 'token_refresher.dart';
import 'token_store.dart';

/// 给请求带上 access token;401 时静默刷新一次并重放原请求。
/// 刷新彻底失败就清空凭证 —— TokenStore 的通知会把人踢回登录页。
class AuthInterceptor extends Interceptor {
  AuthInterceptor({required this.tokenStore, required this.refresher});

  static const _retriedFlag = 'auth.retried';

  final TokenStore tokenStore;
  final TokenRefresher refresher;

  @override
  Future<void> onRequest(RequestOptions options, RequestInterceptorHandler handler) async {
    final token = await tokenStore.accessToken;
    if (token != null) {
      options.headers['Authorization'] = 'Bearer $token';
    }
    handler.next(options);
  }

  @override
  Future<void> onError(DioException err, ErrorInterceptorHandler handler) async {
    final options = err.requestOptions;
    final expired = err.response?.statusCode == 401;
    if (!expired || options.extra[_retriedFlag] == true) {
      return handler.next(err);
    }

    final String? newToken;
    try {
      newToken = await refresher.refresh();
    } on ApiException catch (error) {
      if (error.statusCode == 401) {
        await tokenStore.clear(); // refresh 也过期了:真正掉线
      }
      return handler.next(err);
    }
    if (newToken == null) {
      await tokenStore.clear(); // 本地连 refresh token 都没有
      return handler.next(err);
    }

    options.extra[_retriedFlag] = true;
    options.headers['Authorization'] = 'Bearer $newToken';
    try {
      handler.resolve(await refresher.dio.fetch<dynamic>(options));
    } on DioException catch (error) {
      handler.next(error);
    }
  }
}
```

重写 `app/lib/core/api_client.dart`:

```dart
import 'package:dio/dio.dart';

import 'api_exception.dart';

/// 薄封装:统一抛 ApiException,调用方直接拿 response.data。
class ApiClient {
  ApiClient(this._dio);

  final Dio _dio;

  Future<dynamic> get(String path, {Map<String, dynamic>? query}) =>
      _guard(() => _dio.get<dynamic>(path, queryParameters: query));

  Future<dynamic> post(String path, {Object? data}) =>
      _guard(() => _dio.post<dynamic>(path, data: data));

  Future<dynamic> patch(String path, {Object? data}) =>
      _guard(() => _dio.patch<dynamic>(path, data: data));

  Future<dynamic> delete(String path) => _guard(() => _dio.delete<dynamic>(path));

  Future<dynamic> _guard(Future<Response<dynamic>> Function() request) async {
    try {
      final response = await request();
      return response.data;
    } on DioException catch (error) {
      throw ApiException.from(error);
    }
  }
}
```

新建 `app/lib/core/providers.dart`:

```dart
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api_client.dart';
import 'auth_interceptor.dart';
import 'config.dart';
import 'token_refresher.dart';
import 'token_store.dart';

final tokenStoreProvider = Provider<TokenStore>((ref) => TokenStore());

Dio _newDio() => Dio(BaseOptions(
      baseUrl: apiBase,
      connectTimeout: const Duration(seconds: 10),
      receiveTimeout: const Duration(seconds: 10),
    ));

/// 业务请求用的 Dio(带拦截器);测试里 override 成挂了 ScriptedAdapter 的实例。
final baseDioProvider = Provider<Dio>((ref) => _newDio());

/// 裸 Dio,只给 TokenRefresher 用。
final refreshDioProvider = Provider<Dio>((ref) => _newDio());

final tokenRefresherProvider = Provider<TokenRefresher>((ref) => TokenRefresher(
      dio: ref.watch(refreshDioProvider),
      tokenStore: ref.watch(tokenStoreProvider),
    ));

final apiClientProvider = Provider<ApiClient>((ref) {
  final dio = ref.watch(baseDioProvider);
  dio.interceptors.add(AuthInterceptor(
    tokenStore: ref.watch(tokenStoreProvider),
    refresher: ref.watch(tokenRefresherProvider),
  ));
  return ApiClient(dio);
});
```

删除 `app/test/api_client_test.dart` 与 `app/test/fake_adapter.dart`。

- [ ] **Step 4:运行测试确认通过**

```bash
../flutter/bin/flutter.bat test && ../flutter/bin/flutter.bat analyze
```

预期:全部用例 OK(core 5 + 拦截器 4);analyze 无问题。

- [ ] **Step 5:提交**

```bash
cd "D:/pycharmproject/chat_app" && git add app && git commit -m "feat: dio jwt interceptor + api client + scripted test adapter (M2a)"
```

**卡点速查:**
- 重放请求报 `RequestOptions.data` 已被消费/stream 关闭 → 只发生在 multipart 上传上;MVP 可接受(照片上传 401 时用户重试即可),别为此加复杂度
- `DioException.connectionError` 工厂在旧版 dio 不存在 → dio 要求 ^5.0(本仓库已是 5.11),不用管

---

### Task 3: 会话状态 + 启动鉴权 + 路由骨架

**Files:**
- Create: `app/lib/features/auth/auth_repository.dart`、`app/lib/features/auth/session.dart`、`app/lib/features/auth/splash_page.dart`、`app/lib/features/auth/login_page.dart`(本 Task 先占位)、`app/lib/features/common/placeholder_page.dart`、`app/lib/router.dart`、`app/test/support/harness.dart`、`app/test/features/auth/session_test.dart`、`app/test/features/auth/startup_flow_test.dart`
- Rewrite: `app/lib/app.dart`(`MaterialApp.router` + 中文本地化)

**Interfaces:**
- Consumes: Task 2 的 providers、`ApiClient`;Task 1 的 `TokenStore`。
- Produces:
  - `auth_repository.dart` → `AuthRepository`(`sendSms(phone)` / `verifySms(phone, code) → LoginResult`)、`LoginResult{access, refresh, userId, isNewUser}`、`authRepositoryProvider`
  - `session.dart` → `SessionState`(`SessionLoading` / `SessionLoggedOut` / `SessionLoggedIn` / `SessionBootFailed(message)`)、`SessionController`(`bootstrap()` / `login(phone, code) → LoginResult` / `logout()`)、`sessionProvider`
  - `router.dart` → `routerProvider`(路由:`/splash`、`/login`、`/onboarding`*、`/home`*、`/profile/edit`*、`/preference`*、`/settings`*;打星号的先指向占位页,后续 Task 替换)
  - `test/support/harness.dart` → `pumpApp(tester, adapter, {prefs})`

**为什么状态要 sealed:** `switch` 能穷尽四种状态,编译器盯着你写全;`SessionBootFailed` 与 `SessionLoggedOut` 分开,网络抖动能"重试"而不是被清掉凭证重新登录。

- [ ] **Step 1:写失败的测试**

新建 `app/test/features/auth/session_test.dart`:

```dart
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/auth/session.dart';

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

  test('没有 refresh token → 未登录', () async {
    final container = makeContainer();
    addTearDown(container.dispose);
    await container.read(sessionProvider.notifier).bootstrap();
    expect(container.read(sessionProvider), isA<SessionLoggedOut>());
  });

  test('有 refresh token → 静默刷新成功 → 已登录', () async {
    SharedPreferences.setMockInitialValues({'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7});
    adapter.routes['POST /auth/token/refresh'] = (options) => ok({'access': 'a2', 'refresh': 'r2'});
    final container = makeContainer();
    addTearDown(container.dispose);
    await container.read(sessionProvider.notifier).bootstrap();
    expect(container.read(sessionProvider), isA<SessionLoggedIn>());
  });

  test('refresh 被拒(401)→ 清空凭证并回登录页', () async {
    SharedPreferences.setMockInitialValues({'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7});
    adapter.routes['POST /auth/token/refresh'] = (options) => fail(401, 'Token 无效或已过期');
    final container = makeContainer();
    addTearDown(container.dispose);
    await container.read(sessionProvider.notifier).bootstrap();
    expect(container.read(sessionProvider), isA<SessionLoggedOut>());
    expect((await SharedPreferences.getInstance()).getString('auth.refresh'), isNull);
  });

  test('网络失败 → 启动失败,凭证保留可重试', () async {
    SharedPreferences.setMockInitialValues({'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7});
    adapter.routes['POST /auth/token/refresh'] = offline;
    final container = makeContainer();
    addTearDown(container.dispose);
    await container.read(sessionProvider.notifier).bootstrap();
    expect(container.read(sessionProvider), isA<SessionBootFailed>());
    expect((await SharedPreferences.getInstance()).getString('auth.refresh'), 'r');
  });

  test('登录成功 → 凭证落盘 + 已登录', () async {
    adapter.routes['POST /auth/sms/verify'] =
        (options) => ok({'access': 'a3', 'refresh': 'r3', 'is_new_user': true, 'user_id': 9});
    final container = makeContainer();
    addTearDown(container.dispose);
    final result = await container.read(sessionProvider.notifier).login('13800138000', '123456');
    expect(result.isNewUser, isTrue);
    expect(container.read(sessionProvider), isA<SessionLoggedIn>());
    expect(await container.read(tokenStoreProvider).userId, 9);
  });

  test('登出 → 凭证清空 + 未登录', () async {
    adapter.routes['POST /auth/sms/verify'] =
        (options) => ok({'access': 'a3', 'refresh': 'r3', 'is_new_user': false, 'user_id': 9});
    final container = makeContainer();
    addTearDown(container.dispose);
    await container.read(sessionProvider.notifier).login('13800138000', '123456');
    await container.read(sessionProvider.notifier).logout();
    expect(container.read(sessionProvider), isA<SessionLoggedOut>());
    expect(await container.read(tokenStoreProvider).refreshToken, isNull);
  });
}
```

新建 `app/test/support/harness.dart`:

```dart
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/app.dart';
import 'package:chatapp_app/core/providers.dart';

import 'scripted_adapter.dart';

/// 起整个 App(真实 provider + 假网络)。prefs 里塞 {'auth.refresh': 'r', ...} 模拟已登录。
Future<void> pumpApp(WidgetTester tester, ScriptedAdapter adapter,
    {Map<String, Object> prefs = const {}}) async {
  SharedPreferences.setMockInitialValues(prefs);
  final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
  final refreshDio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
  await tester.pumpWidget(ProviderScope(
    overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(refreshDio),
    ],
    child: const ChatApp(),
  ));
}

/// 底部导航栏里的 Tab 标签(避开与各页 AppBar 标题重名)。
Finder navTab(String label) =>
    find.descendant(of: find.byType(NavigationBar), matching: find.text(label));
```

新建 `app/test/features/auth/startup_flow_test.dart`:

```dart
import 'package:flutter_test/flutter_test.dart';

import '../../support/harness.dart';
import '../../support/scripted_adapter.dart';

void main() {
  testWidgets('没有本地凭证启动 → 落在登录页', (tester) async {
    await pumpApp(tester, ScriptedAdapter({}));
    await tester.pumpAndSettle();
    expect(find.text('登录页施工中'), findsOneWidget);
  });
}
```

- [ ] **Step 2:运行确认失败**

```bash
../flutter/bin/flutter.bat test test/features
```

预期:编译失败(`features/auth/session.dart` 等不存在)。

- [ ] **Step 3:实现会话与仓库**

新建 `app/lib/features/auth/auth_repository.dart`:

```dart
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';

class LoginResult {
  const LoginResult({
    required this.access,
    required this.refresh,
    required this.userId,
    required this.isNewUser,
  });

  factory LoginResult.fromJson(Map<String, dynamic> json) => LoginResult(
        access: json['access'] as String,
        refresh: json['refresh'] as String,
        userId: json['user_id'] as int,
        isNewUser: json['is_new_user'] as bool,
      );

  final String access;
  final String refresh;
  final int userId;
  final bool isNewUser;
}

class AuthRepository {
  AuthRepository(this._api);

  final ApiClient _api;

  Future<void> sendSms(String phone) async {
    await _api.post('/auth/sms/send', data: {'phone': phone});
  }

  Future<LoginResult> verifySms(String phone, String code) async {
    final data = await _api.post('/auth/sms/verify', data: {'phone': phone, 'code': code});
    return LoginResult.fromJson(data as Map<String, dynamic>);
  }
}

final authRepositoryProvider =
    Provider<AuthRepository>((ref) => AuthRepository(ref.watch(apiClientProvider)));
```

新建 `app/lib/features/auth/session.dart`:

```dart
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_exception.dart';
import '../../core/providers.dart';
import 'auth_repository.dart';

sealed class SessionState {
  const SessionState();
}

class SessionLoading extends SessionState {
  const SessionLoading();
}

class SessionLoggedOut extends SessionState {
  const SessionLoggedOut();
}

class SessionLoggedIn extends SessionState {
  const SessionLoggedIn();
}

class SessionBootFailed extends SessionState {
  const SessionBootFailed(this.message);
  final String message;
}

class SessionController extends Notifier<SessionState> {
  bool _bootstrapping = false;

  @override
  SessionState build() {
    final store = ref.watch(tokenStoreProvider);
    void onTokensCleared() => _forceLogout();
    store.addListener(onTokensCleared);
    ref.onDispose(() => store.removeListener(onTokensCleared));
    return const SessionLoading();
  }

  /// 启动鉴权:有 refresh token 就静默换新 access;没有就回登录页。
  Future<void> bootstrap() async {
    if (_bootstrapping || state is SessionLoggedIn) return;
    _bootstrapping = true;
    try {
      final store = ref.read(tokenStoreProvider);
      final refreshToken = await store.refreshToken;
      if (refreshToken == null) {
        state = const SessionLoggedOut();
        return;
      }
      await ref.read(tokenRefresherProvider).refresh();
      if (state is! SessionLoggedIn) {
        state = const SessionLoggedIn();
      }
    } on ApiException catch (error) {
      if (error.statusCode == 401) {
        await ref.read(tokenStoreProvider).clear(); // 触发 _forceLogout
        state = const SessionLoggedOut();
      } else {
        state = SessionBootFailed(error.message);
      }
    } finally {
      _bootstrapping = false;
    }
  }

  Future<LoginResult> login(String phone, String code) async {
    final result = await ref.read(authRepositoryProvider).verifySms(phone, code);
    await ref.read(tokenStoreProvider).save(
          access: result.access,
          refresh: result.refresh,
          userId: result.userId,
        );
    state = const SessionLoggedIn();
    return result;
  }

  Future<void> logout() async {
    // 清凭证会通知监听者;M2c 接入 IM 后这里还要 IM 登出 + 清本地缓存(spec §7.5)
    await ref.read(tokenStoreProvider).clear();
    state = const SessionLoggedOut();
  }

  void _forceLogout() {
    if (state is! SessionLoggedOut) {
      state = const SessionLoggedOut();
    }
  }
}

final sessionProvider = NotifierProvider<SessionController, SessionState>(SessionController.new);
```

- [ ] **Step 4:实现路由与页面骨架**

新建 `app/lib/features/common/placeholder_page.dart`:

```dart
import 'package:flutter/material.dart';

/// 还没有实现的页面占位;真页面上线后连同路由一起替换。
class PlaceholderPage extends StatelessWidget {
  const PlaceholderPage({super.key, required this.title});

  final String title;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(title)),
      body: Center(child: Text('$title 施工中')),
    );
  }
}
```

新建 `app/lib/features/auth/splash_page.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'session.dart';

class SplashPage extends ConsumerStatefulWidget {
  const SplashPage({super.key});

  @override
  ConsumerState<SplashPage> createState() => _SplashPageState();
}

class _SplashPageState extends ConsumerState<SplashPage> {
  @override
  void initState() {
    super.initState();
    // bootstrap 的第一步就是 await,状态变更发生在异步之后,initState 里触发是安全的
    ref.read(sessionProvider.notifier).bootstrap();
  }

  @override
  Widget build(BuildContext context) {
    final session = ref.watch(sessionProvider);
    return Scaffold(
      body: Center(
        child: switch (session) {
          SessionBootFailed(:final message) => Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(message),
                const SizedBox(height: 12),
                FilledButton(
                  onPressed: () => ref.read(sessionProvider.notifier).bootstrap(),
                  child: const Text('重试'),
                ),
              ],
            ),
          _ => const Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                CircularProgressIndicator(),
                SizedBox(height: 12),
                Text('正在启动…'),
              ],
            ),
        },
      ),
    );
  }
}
```

新建 `app/lib/features/auth/login_page.dart`(Task 4 换成真页面):

```dart
import 'package:flutter/material.dart';

class LoginPage extends StatelessWidget {
  const LoginPage({super.key});

  @override
  Widget build(BuildContext context) {
    return const Scaffold(body: Center(child: Text('登录页施工中')));
  }
}
```

新建 `app/lib/router.dart`:

```dart
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'features/auth/login_page.dart';
import 'features/auth/session.dart';
import 'features/auth/splash_page.dart';
import 'features/common/placeholder_page.dart';

final routerProvider = Provider<GoRouter>((ref) {
  // 会话状态变化 → 让 GoRouter 重新跑一遍 redirect
  final refreshSignal = ValueNotifier<int>(0);
  ref.listen(sessionProvider, (_, __) => refreshSignal.value++);
  ref.onDispose(refreshSignal.dispose);

  return GoRouter(
    initialLocation: '/splash',
    refreshListenable: refreshSignal,
    routes: [
      GoRoute(path: '/splash', builder: (context, state) => const SplashPage()),
      GoRoute(path: '/login', builder: (context, state) => const LoginPage()),
      GoRoute(
          path: '/onboarding',
          builder: (context, state) => const PlaceholderPage(title: '资料引导')),
      GoRoute(path: '/home', builder: (context, state) => const PlaceholderPage(title: '主框架')),
    ],
    redirect: (context, state) {
      final session = ref.read(sessionProvider);
      final location = state.matchedLocation;
      switch (session) {
        case SessionLoading() || SessionBootFailed():
          return location == '/splash' ? null : '/splash';
        case SessionLoggedOut():
          return location == '/login' ? null : '/login';
        case SessionLoggedIn():
          return (location == '/splash' || location == '/login') ? '/home' : null;
      }
    },
  );
});
```

重写 `app/lib/app.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'router.dart';

class ChatApp extends ConsumerWidget {
  const ChatApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return MaterialApp.router(
      title: '交友 Chat',
      theme: ThemeData(colorSchemeSeed: Colors.pink, useMaterial3: true),
      locale: const Locale('zh', 'CN'),
      supportedLocales: const [Locale('zh', 'CN')],
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      routerConfig: ref.watch(routerProvider),
    );
  }
}
```

- [ ] **Step 5:运行测试确认通过**

```bash
../flutter/bin/flutter.bat test && ../flutter/bin/flutter.bat analyze
```

预期:session 6 个 + 启动流 1 个 + core 5 个 + 拦截器 4 个全绿;analyze 无问题。

- [ ] **Step 6:提交**

```bash
cd "D:/pycharmproject/chat_app" && git add app && git commit -m "feat: session state + startup auth + go_router skeleton (M2a)"
```

**卡点速查:**
- `ref.listen` 在 `Provider` 里报错 → 确认 flutter_riverpod 版本;若 API 不同,改为在 `ChatApp` 里 `ref.listen(sessionProvider, ...)` 触发 `router.refresh()` 也行
- 启动流测试停在"正在启动…" → `bootstrap()` 没被调用或 `pumpAndSettle` 前 provider 还没跑完;先 `await tester.pump()` 再 settle
- Riverpod 3.x 里 `ProviderContainer(overrides: ...)` 构造若被废弃 → 用 `ProviderContainer.test(overrides: ...)`,记得同步更新测试

---

### Task 4: 登录页(手机号 + 验证码)

**Files:**
- Rewrite: `app/lib/features/auth/login_page.dart`
- Modify: `app/test/features/auth/startup_flow_test.dart`(断言从占位文案改成真实页面)
- Test: `app/test/features/auth/login_page_test.dart`

**Interfaces:**
- Consumes: Task 3 的 `sessionProvider.login` / `authRepositoryProvider.sendSms`。
- Produces: 真实登录页(钥匙 `login.phone` / `login.code` / `login.sendCode` / `login.submit`);注册新用户 `is_new_user=true` → `/onboarding`,老用户 → `/home`。

**为什么验证码页能当注册页:** 后端 `sms/verify` 对没注册过的号码自动建号,前端只需根据 `is_new_user` 决定去向导还是主框架。

- [ ] **Step 1:写失败的测试**

新建 `app/test/features/auth/login_page_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

void main() {
  testWidgets('获取验证码 → 按钮进入 60 秒倒计时', (tester) async {
    final adapter = ScriptedAdapter({'POST /auth/sms/send': (options) => ok({'status': 'ok'})});
    await pumpApp(tester, adapter);
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('login.phone')), '13800138000');
    await tester.tap(find.byKey(const Key('login.sendCode')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(adapter.log.where((r) => r.path == '/auth/sms/send'), hasLength(1));
    expect(find.text('60 秒后重发'), findsOneWidget);

    // 卸载页面以取消倒计时 Timer,否则测试结束会报 pending timer
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('手机号格式不对 → 不发请求', (tester) async {
    final adapter = ScriptedAdapter({});
    await pumpApp(tester, adapter);
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('login.phone')), '123');
    await tester.tap(find.byKey(const Key('login.sendCode')));
    await tester.pump();

    expect(find.text('请输入正确的手机号'), findsOneWidget);
    expect(adapter.log, isEmpty);
  });

  testWidgets('老用户登录成功 → 进入主框架', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/sms/verify': (options) =>
          ok({'access': 'a', 'refresh': 'r', 'is_new_user': false, 'user_id': 7}),
      'GET /users/me': (options) => ok(profileJson()),
      'POST /auth/token/refresh': (options) => ok({'access': 'a', 'refresh': 'r'}),
    });
    await pumpApp(tester, adapter);
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('login.phone')), '13800138000');
    await tester.enterText(find.byKey(const Key('login.code')), '123456');
    await tester.tap(find.byKey(const Key('login.submit')));
    await tester.pumpAndSettle();

    expect(adapter.log.where((r) => r.path == '/auth/sms/verify'), hasLength(1));
    expect(find.text('主框架施工中'), findsOneWidget); // Task 5 会替换成主框架壳
  });
}
```

(这里用到 `profileJson()`,在 Task 5 的 `test/support/sample_data.dart` 里定义 —— 本 Task 先建它,内容见 Task 5 Step 1,先只放最简版本即可:`Map<String, dynamic> profileJson({...})` 见下文。)

`app/test/support/sample_data.dart` 本 Task 先建最小版:

```dart
/// 造一份 GET /users/me 的响应;各字段可覆盖。
Map<String, dynamic> profileJson({
  int id = 7,
  String nickname = '小明',
  String? gender = 'male',
  String? birthday = '2000-01-01',
  String city = '上海',
  String bio = '你好',
  List<String> missing = const [],
  List<Map<String, dynamic>> tags = const [],
  List<Map<String, dynamic>> photos = const [],
  Map<String, dynamic>? preference,
}) =>
    {
      'id': id,
      'phone': '13800138000',
      'nickname': nickname,
      'gender': gender,
      'birthday': birthday,
      'age': birthday == null ? null : 26,
      'city': city,
      'bio': bio,
      'status': missing.isEmpty ? 'complete' : 'incomplete',
      'missing_fields': missing,
      'tags': tags,
      'photos': photos,
      'preference': preference ??
          {'target_gender': null, 'age_min': 18, 'age_max': 99, 'city': ''},
    };
```

- [ ] **Step 2:运行确认失败**

```bash
../flutter/bin/flutter.bat test test/features/auth
```

预期:新用例失败(找不到 `login.phone` / 断言 `登录页施工中` 落空)。

- [ ] **Step 3:实现登录页**

整体替换 `app/lib/features/auth/login_page.dart`:

```dart
import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import 'auth_repository.dart';
import 'session.dart';

class LoginPage extends ConsumerStatefulWidget {
  const LoginPage({super.key});

  @override
  ConsumerState<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends ConsumerState<LoginPage> {
  static final _phonePattern = RegExp(r'^1[3-9]\d{9}$');

  final _phoneController = TextEditingController();
  final _codeController = TextEditingController();
  Timer? _timer;
  int _countdown = 0;
  bool _sending = false;
  bool _submitting = false;

  @override
  void dispose() {
    _timer?.cancel();
    _phoneController.dispose();
    _codeController.dispose();
    super.dispose();
  }

  void _show(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _sendCode() async {
    final phone = _phoneController.text.trim();
    if (!_phonePattern.hasMatch(phone)) {
      _show('请输入正确的手机号');
      return;
    }
    setState(() => _sending = true);
    try {
      await ref.read(authRepositoryProvider).sendSms(phone);
      if (!mounted) return;
      _startCountdown();
      _show('验证码已发送,请查看短信');
    } on ApiException catch (error) {
      if (mounted) _show(error.message);
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  void _startCountdown() {
    _timer?.cancel();
    setState(() => _countdown = 60);
    _timer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (!mounted) {
        timer.cancel();
        return;
      }
      if (_countdown <= 1) {
        timer.cancel();
        setState(() => _countdown = 0);
      } else {
        setState(() => _countdown -= 1);
      }
    });
  }

  Future<void> _submit() async {
    final phone = _phoneController.text.trim();
    final code = _codeController.text.trim();
    if (!_phonePattern.hasMatch(phone)) {
      _show('请输入正确的手机号');
      return;
    }
    if (code.length != 6) {
      _show('请输入 6 位验证码');
      return;
    }
    setState(() => _submitting = true);
    try {
      final result = await ref.read(sessionProvider.notifier).login(phone, code);
      if (!mounted) return;
      context.go(result.isNewUser ? '/onboarding' : '/home');
    } on ApiException catch (error) {
      if (mounted) _show(error.message);
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(24),
          children: [
            const SizedBox(height: 60),
            Text('交友 Chat',
                textAlign: TextAlign.center, style: Theme.of(context).textTheme.headlineMedium),
            const SizedBox(height: 8),
            const Text('手机号登录 / 注册', textAlign: TextAlign.center),
            const SizedBox(height: 40),
            TextField(
              key: const Key('login.phone'),
              controller: _phoneController,
              keyboardType: TextInputType.phone,
              maxLength: 11,
              decoration: const InputDecoration(
                labelText: '手机号',
                counterText: '',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    key: const Key('login.code'),
                    controller: _codeController,
                    keyboardType: TextInputType.number,
                    maxLength: 6,
                    decoration: const InputDecoration(
                      labelText: '验证码',
                      counterText: '',
                      border: OutlineInputBorder(),
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                SizedBox(
                  width: 130,
                  height: 56,
                  child: OutlinedButton(
                    key: const Key('login.sendCode'),
                    onPressed: (_sending || _countdown > 0) ? null : _sendCode,
                    child: Text(_countdown > 0 ? '$_countdown 秒后重发' : '获取验证码'),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 24),
            FilledButton(
              key: const Key('login.submit'),
              onPressed: _submitting ? null : _submit,
              child: Text(_submitting ? '登录中…' : '登录 / 注册'),
            ),
            const SizedBox(height: 16),
            if (kDebugMode)
              const Text('开发模式:验证码固定 123456',
                  textAlign: TextAlign.center, style: TextStyle(color: Colors.grey)),
          ],
        ),
      ),
    );
  }
}
```

修改 `app/test/features/auth/startup_flow_test.dart` 的断言:

```dart
    expect(find.text('获取验证码'), findsOneWidget);
```

- [ ] **Step 4:运行测试确认通过**

```bash
../flutter/bin/flutter.bat test && ../flutter/bin/flutter.bat analyze
```

预期:全绿;analyze 无问题。

- [ ] **Step 5:提交**

```bash
cd "D:/pycharmproject/chat_app" && git add app && git commit -m "feat: phone + sms code login page (M2a)"
```

**卡点速查:**
- 测试报 `A Timer is still pending` → 倒计时属于 `Timer.periodic`,别用 `pumpAndSettle` 等它停;测完 `pumpWidget(const SizedBox())` 卸载页面
- 登录成功后偶发先看到主框架再跳向导 → `redirect` 与手动 `context.go` 的先后顺序问题,结果一致,不修
- 429(发太频繁)会走 SnackBar 显示后端中文文案,属预期

---

### Task 5: 资料模型/仓库 + 主框架壳 + 我的资料页

**Files:**
- Create: `app/lib/features/profile/models.dart`、`app/lib/features/profile/profile_repository.dart`、`app/lib/features/profile/profile_controller.dart`、`app/lib/features/profile/my_profile_page.dart`、`app/lib/features/shell/home_shell.dart`、`app/lib/features/discovery/discovery_page.dart`、`app/lib/features/chat/chats_page.dart`、`app/lib/core/format.dart`
- Modify: `app/lib/router.dart`(`/home` → `HomeShell`;注册 `/profile/edit`、`/preference`、`/settings` 占位路由)
- Modify: `app/test/support/sample_data.dart`(补齐 `photoJson` / `tagJson`)
- Modify: `app/test/features/auth/login_page_test.dart`(断言改成主框架 NavigationBar)
- Test: `app/test/features/profile/profile_repository_test.dart`、`app/test/features/shell/home_shell_test.dart`、`app/test/features/profile/models_test.dart`

**Interfaces:**
- Consumes: Task 2 的 providers;Task 3 的 `sessionProvider`。
- Produces:
  - `models.dart` → `Profile{id, nickname, gender, birthday, age, city, bio, status, missingFields, tags, photos, preference}`(`isComplete` / `avatar`)、`Tag{id, name, icon}`、`Photo{id, url, status}`(`isApproved`)、`Preference{targetGender, ageMin, ageMax, city}`;`isAtLeast18(DateTime)`;`missingFieldLabel(String)`
  - `core/format.dart` → `formatDate(DateTime)` / `parseDate(String?)`
  - `profile_repository.dart` → `ProfileRepository`(`fetchMe` / `update(patch)` / `fetchTags` / `uploadPhoto` / `deletePhoto` / `fetchPreference` / `updatePreference`)、`profileRepositoryProvider`
  - `profile_controller.dart` → `profileProvider`(`AsyncNotifierProvider<ProfileController, Profile>`,方法 `reload()` / `save(patch)`)、`tagsProvider`
  - `HomeShell`(三 Tab:`DiscoveryPage` / `ChatsPage` / `MyProfilePage`)

**为什么资料放 Provider 而不是页面里:** 三个 Tab、编辑页、向导都要读同一份资料;`profileProvider` 一处拉取、处处 `watch`,改完 `save()` 直接换 state,全 UI 同步刷新。

- [ ] **Step 1:写失败的测试**

新建 `app/test/features/profile/models_test.dart`:

```dart
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/format.dart';
import 'package:chatapp_app/features/profile/models.dart';

import '../../support/sample_data.dart';

void main() {
  test('Profile.fromJson 解析完整资料', () {
    final profile = Profile.fromJson(profileJson(
      tags: [tagJson(1, '运动')],
      photos: [photoJson(9, approved: true)],
    ));
    expect(profile.nickname, '小明');
    expect(profile.isComplete, isTrue);
    expect(profile.tags.single.name, '运动');
    expect(profile.avatar?.id, 9);
  });

  test('没有过审照片时 avatar 为空', () {
    final profile = Profile.fromJson(profileJson(photos: [photoJson(9, approved: false)]));
    expect(profile.avatar, isNull);
  });

  test('isAtLeast18 计算生日边界', () {
    final today = DateTime(2026, 9, 10);
    expect(isAtLeast18(DateTime(2008, 9, 10), today: today), isTrue);   // 今天刚好 18
    expect(isAtLeast18(DateTime(2008, 9, 11), today: today), isFalse);  // 差一天
  });

  test('日期格式化与解析', () {
    expect(formatDate(DateTime(2000, 1, 5)), '2000-01-05');
    expect(parseDate('2000-01-05'), DateTime(2000, 1, 5));
    expect(parseDate(null), isNull);
  });
}
```

新建 `app/test/features/profile/profile_repository_test.dart`:

```dart
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/api_client.dart';
import 'package:chatapp_app/features/profile/profile_repository.dart';

import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

void main() {
  late ScriptedAdapter adapter;
  late ProfileRepository repository;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    adapter = ScriptedAdapter({});
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    repository = ProfileRepository(ApiClient(dio));
  });

  test('fetchMe 解析资料', () async {
    adapter.routes['GET /users/me'] =
        (options) => ok(profileJson(nickname: '小红', missing: ['photos']));
    final profile = await repository.fetchMe();
    expect(profile.nickname, '小红');
    expect(profile.isComplete, isFalse);
    expect(profile.missingFields, ['photos']);
  });

  test('update 发 PATCH 并回新资料', () async {
    adapter.routes['PATCH /users/me'] = (options) => ok(profileJson(nickname: '新昵称'));
    final profile = await repository.update({'nickname': '新昵称'});
    expect(profile.nickname, '新昵称');
    expect(adapter.log.last.method, 'PATCH');
    expect(adapter.log.last.data, {'nickname': '新昵称'});
  });

  test('fetchTags 解析标签池', () async {
    adapter.routes['GET /users/tags'] = (options) => ok([tagJson(1, '运动'), tagJson(2, '音乐')]);
    final tags = await repository.fetchTags();
    expect(tags.map((tag) => tag.name), ['运动', '音乐']);
  });
}
```

新建 `app/test/features/shell/home_shell_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/harness.dart';
import '../../support/scripted_adapter.dart';
import '../../support/sample_data.dart';

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

ScriptedAdapter _adapter({required Map<String, dynamic> profile}) => ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profile),
    });

void main() {
  testWidgets('三个 Tab 都在;「我的」显示昵称与资料入口', (tester) async {
    final adapter = _adapter(profile: profileJson(nickname: '小明'));
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    expect(find.byType(NavigationBar), findsOneWidget);
    expect(navTab('发现'), findsOneWidget);
    expect(navTab('会话'), findsOneWidget);
    expect(navTab('我的'), findsOneWidget);

    await tester.tap(navTab('我的'));
    await tester.pumpAndSettle();
    expect(find.text('小明'), findsOneWidget);
    expect(find.text('编辑资料'), findsOneWidget);
    expect(find.text('想找的人'), findsOneWidget);
    expect(find.text('设置'), findsOneWidget);
  });

  testWidgets('资料未完善 → 发现页显示引导卡,点按钮去向导', (tester) async {
    final adapter = _adapter(
        profile: profileJson(missing: ['bio', 'photos']));
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    expect(find.text('完善资料后就能开始滑卡'), findsOneWidget);
    await tester.tap(find.byKey(const Key('discovery.goOnboarding')));
    await tester.pumpAndSettle();
    expect(find.text('资料引导施工中'), findsOneWidget);
  });
}
```

- [ ] **Step 2:运行确认失败**

```bash
../flutter/bin/flutter.bat test test/features/profile test/features/shell
```

预期:编译失败(模块不存在)。

- [ ] **Step 3:实现模型与仓库**

新建 `app/lib/core/format.dart`:

```dart
String formatDate(DateTime date) =>
    '${date.year.toString().padLeft(4, '0')}-'
    '${date.month.toString().padLeft(2, '0')}-'
    '${date.day.toString().padLeft(2, '0')}';

DateTime? parseDate(String? text) =>
    (text == null || text.isEmpty) ? null : DateTime.parse(text);
```

新建 `app/lib/features/profile/models.dart`:

```dart
/// 资料相关的数据模型;字段与后端 GET /users/me 的响应一一对应。

class Tag {
  const Tag({required this.id, required this.name, this.icon = ''});

  factory Tag.fromJson(Map<String, dynamic> json) => Tag(
        id: json['id'] as int,
        name: json['name'] as String,
        icon: (json['icon'] ?? '') as String,
      );

  final int id;
  final String name;
  final String icon;
}

class Photo {
  const Photo({required this.id, required this.url, required this.status});

  factory Photo.fromJson(Map<String, dynamic> json) => Photo(
        id: json['id'] as int,
        url: json['url'] as String,
        status: json['status'] as String,
      );

  final int id;
  final String url;
  final String status;

  bool get isApproved => status == 'approved';
}

class Preference {
  const Preference({this.targetGender, this.ageMin = 18, this.ageMax = 99, this.city = ''});

  factory Preference.fromJson(Map<String, dynamic>? json) => json == null
      ? const Preference()
      : Preference(
          targetGender: json['target_gender'] as String?,
          ageMin: json['age_min'] as int,
          ageMax: json['age_max'] as int,
          city: (json['city'] ?? '') as String,
        );

  final String? targetGender;
  final int ageMin;
  final int ageMax;
  final String city;
}

class Profile {
  const Profile({
    required this.id,
    required this.nickname,
    required this.gender,
    required this.birthday,
    required this.age,
    required this.city,
    required this.bio,
    required this.status,
    required this.missingFields,
    required this.tags,
    required this.photos,
    required this.preference,
  });

  factory Profile.fromJson(Map<String, dynamic> json) => Profile(
        id: json['id'] as int,
        nickname: (json['nickname'] ?? '') as String,
        gender: json['gender'] as String?,
        birthday: json['birthday'] as String?,
        age: json['age'] as int?,
        city: (json['city'] ?? '') as String,
        bio: (json['bio'] ?? '') as String,
        status: json['status'] as String,
        missingFields:
            ((json['missing_fields'] ?? const []) as List<dynamic>).cast<String>(),
        tags: ((json['tags'] ?? const []) as List<dynamic>)
            .map((item) => Tag.fromJson(item as Map<String, dynamic>))
            .toList(),
        photos: ((json['photos'] ?? const []) as List<dynamic>)
            .map((item) => Photo.fromJson(item as Map<String, dynamic>))
            .toList(),
        preference: Preference.fromJson(json['preference'] as Map<String, dynamic>?),
      );

  final int id;
  final String nickname;
  final String? gender;
  final String? birthday;
  final int? age;
  final String city;
  final String bio;
  final String status;
  final List<String> missingFields;
  final List<Tag> tags;
  final List<Photo> photos;
  final Preference preference;

  bool get isComplete => missingFields.isEmpty;

  Photo? get avatar {
    for (final photo in photos) {
      if (photo.isApproved) return photo;
    }
    return null;
  }
}

String missingFieldLabel(String field) => const {
      'nickname': '昵称',
      'gender': '性别',
      'birthday': '生日',
      'city': '城市',
      'bio': '简介',
      'photos': '照片',
    }[field] ??
    field;

bool isAtLeast18(DateTime birthday, {DateTime? today}) {
  final now = today ?? DateTime.now();
  var age = now.year - birthday.year;
  if (now.month < birthday.month || (now.month == birthday.month && now.day < birthday.day)) {
    age -= 1;
  }
  return age >= 18;
}
```

新建 `app/lib/features/profile/profile_repository.dart`:

```dart
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import 'models.dart';

class ProfileRepository {
  ProfileRepository(this._api);

  final ApiClient _api;

  Future<Profile> fetchMe() async =>
      Profile.fromJson(await _api.get('/users/me') as Map<String, dynamic>);

  Future<Profile> update(Map<String, dynamic> patch) async =>
      Profile.fromJson(await _api.patch('/users/me', data: patch) as Map<String, dynamic>);

  Future<List<Tag>> fetchTags() async {
    final data = await _api.get('/users/tags') as List<dynamic>;
    return data.map((item) => Tag.fromJson(item as Map<String, dynamic>)).toList();
  }

  Future<Photo> uploadPhoto(Uint8List bytes, String filename) async {
    final data = await _api.post('/users/me/photos',
        data: FormData.fromMap({'file': MultipartFile.fromBytes(bytes, filename: filename)}));
    return Photo.fromJson(data as Map<String, dynamic>);
  }

  Future<void> deletePhoto(int photoId) async {
    await _api.delete('/users/me/photos/$photoId');
  }

  Future<Preference> fetchPreference() async =>
      Preference.fromJson(await _api.get('/users/me/preference') as Map<String, dynamic>);

  Future<Preference> updatePreference(Map<String, dynamic> patch) async => Preference.fromJson(
      await _api.patch('/users/me/preference', data: patch) as Map<String, dynamic>);
}

final profileRepositoryProvider =
    Provider<ProfileRepository>((ref) => ProfileRepository(ref.watch(apiClientProvider)));
```

新建 `app/lib/features/profile/profile_controller.dart`:

```dart
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'models.dart';
import 'profile_repository.dart';

class ProfileController extends AsyncNotifier<Profile> {
  @override
  Future<Profile> build() => ref.watch(profileRepositoryProvider).fetchMe();

  Future<void> reload() async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(() => ref.read(profileRepositoryProvider).fetchMe());
  }

  /// 保存资料;失败原样抛出,由页面弹提示。
  Future<void> save(Map<String, dynamic> patch) async {
    final updated = await ref.read(profileRepositoryProvider).update(patch);
    state = AsyncValue.data(updated);
  }
}

final profileProvider =
    AsyncNotifierProvider<ProfileController, Profile>(ProfileController.new);

final tagsProvider =
    FutureProvider<List<Tag>>((ref) => ref.watch(profileRepositoryProvider).fetchTags());
```

- [ ] **Step 4:实现主框架与我的资料页**

新建 `app/lib/features/chat/chats_page.dart`(M2c 之前的占位):

```dart
import 'package:flutter/material.dart';

class ChatsPage extends StatelessWidget {
  const ChatsPage({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('会话')),
      body: const Center(child: Text('聊天功能开发中,下一步就来')),
    );
  }
}
```

新建 `app/lib/features/discovery/discovery_page.dart`(M2b 之前的占位 + 未完善引导):

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../profile/models.dart';
import '../profile/profile_controller.dart';

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
            ? const Center(child: Text('卡片流开发中,下一步就来'))
            : Center(
                child: Card(
                  margin: const EdgeInsets.all(24),
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Text('完善资料后就能开始滑卡'),
                        const SizedBox(height: 8),
                        Text('还差:${data.missingFields.map(missingFieldLabel).join('、')}'),
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
              ),
      ),
    );
  }
}
```

新建 `app/lib/features/profile/my_profile_page.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'models.dart';
import 'profile_controller.dart';

class MyProfilePage extends ConsumerWidget {
  const MyProfilePage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final profile = ref.watch(profileProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('我的')),
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
        data: (data) => ListView(
          children: [
            const SizedBox(height: 16),
            Center(child: _Avatar(profile: data)),
            const SizedBox(height: 12),
            Center(
              child: Text(data.nickname.isEmpty ? '未填昵称' : data.nickname,
                  style: Theme.of(context).textTheme.titleLarge),
            ),
            Center(
              child: Text([
                if (data.age != null) '${data.age} 岁',
                if (data.city.isNotEmpty) data.city,
              ].join(' · ')),
            ),
            if (data.bio.isNotEmpty) ...[
              const SizedBox(height: 8),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 24),
                child: Text(data.bio, textAlign: TextAlign.center),
              ),
            ],
            if (data.tags.isNotEmpty) ...[
              const SizedBox(height: 12),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 24),
                child: Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  alignment: WrapAlignment.center,
                  children: [for (final tag in data.tags) Chip(label: Text(tag.name))],
                ),
              ),
            ],
            if (!data.isComplete) ...[
              const SizedBox(height: 16),
              Card(
                margin: const EdgeInsets.symmetric(horizontal: 16),
                child: ListTile(
                  leading: const Icon(Icons.error_outline),
                  title: const Text('资料还没完善'),
                  subtitle: Text('还差:${data.missingFields.map(missingFieldLabel).join('、')}'),
                  trailing: FilledButton(
                    key: const Key('my.goOnboarding'),
                    onPressed: () => context.go('/onboarding'),
                    child: const Text('去完善'),
                  ),
                ),
              ),
            ],
            const SizedBox(height: 16),
            const Divider(),
            ListTile(
              leading: const Icon(Icons.edit_outlined),
              title: const Text('编辑资料'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => context.push('/profile/edit'),
            ),
            ListTile(
              leading: const Icon(Icons.favorite_outline),
              title: const Text('想找的人'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => context.push('/preference'),
            ),
            ListTile(
              leading: const Icon(Icons.settings_outlined),
              title: const Text('设置'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => context.push('/settings'),
            ),
          ],
        ),
      ),
    );
  }
}

class _Avatar extends StatelessWidget {
  const _Avatar({required this.profile});

  final Profile profile;

  @override
  Widget build(BuildContext context) {
    final avatar = profile.avatar;
    return CircleAvatar(
      radius: 48,
      backgroundImage: avatar == null ? null : NetworkImage(avatar.url),
      child: avatar == null ? const Icon(Icons.person, size: 48) : null,
    );
  }
}
```

新建 `app/lib/features/shell/home_shell.dart`:

```dart
import 'package:flutter/material.dart';

import '../chat/chats_page.dart';
import '../discovery/discovery_page.dart';
import '../profile/my_profile_page.dart';

class HomeShell extends StatefulWidget {
  const HomeShell({super.key});

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  int _index = 0;

  static const _pages = [DiscoveryPage(), ChatsPage(), MyProfilePage()];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: IndexedStack(index: _index, children: _pages),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (index) => setState(() => _index = index),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.style_outlined), label: '发现'),
          NavigationDestination(icon: Icon(Icons.chat_bubble_outline), label: '会话'),
          NavigationDestination(icon: Icon(Icons.person_outline), label: '我的'),
        ],
      ),
    );
  }
}
```

修改 `app/lib/router.dart`:`/home` 指向 `HomeShell`,并注册三个占位的详情路由:

```dart
import 'features/shell/home_shell.dart';
// ...
      GoRoute(path: '/home', builder: (context, state) => const HomeShell()),
      GoRoute(
          path: '/profile/edit',
          builder: (context, state) => const PlaceholderPage(title: '编辑资料')),
      GoRoute(
          path: '/preference',
          builder: (context, state) => const PlaceholderPage(title: '想找的人')),
      GoRoute(path: '/settings', builder: (context, state) => const PlaceholderPage(title: '设置')),
```

(`/onboarding` 仍是占位;`/profile/edit`、`/preference`、`/settings` 会在 Task 7/9 换成真页面。)

修改 `app/test/support/sample_data.dart`,补上:

```dart
Map<String, dynamic> tagJson(int id, String name, {String icon = ''}) =>
    {'id': id, 'name': name, 'icon': icon};

Map<String, dynamic> photoJson(int id, {bool approved = true, int order = 0}) => {
      'id': id,
      'url': 'http://test/media/photos/$id.png',
      'status': approved ? 'approved' : 'pending',
      'order': order,
    };
```

修改 `app/test/features/auth/login_page_test.dart` 最后一个用例的断言:

```dart
    expect(find.byType(NavigationBar), findsOneWidget); // 进主框架了
```

- [ ] **Step 5:运行测试确认通过**

```bash
../flutter/bin/flutter.bat test && ../flutter/bin/flutter.bat analyze
```

预期:全绿;analyze 无问题。

- [ ] **Step 6:提交**

```bash
cd "D:/pycharmproject/chat_app" && git add app && git commit -m "feat: profile models/repository + home shell + my profile page (M2a)"
```

**卡点速查:**
- `Image.network` 在测试里报 400(假 URL)→ widget 测试里别让头像真正加载;若报错,给 `_Avatar` 用 `foregroundImage` 或测试数据用 `photos: []`(photoJson 的 URL 只在断言头像存在性时才需要)
- 我的资料页显示 `ApiException(...)` → 后端没起或 token 失效;widget 测试里是没铺 `GET /users/me` 路由
- `IndexedStack` 里三个页面都会 build → `GET /users/me` 只发一次(provider 缓存),测试里别断言请求次数少于此

---

### Task 6: 照片管理部件(上传/删除)

**Files:**
- Create: `app/lib/features/profile/widgets/photo_grid.dart`
- Modify: `app/lib/features/profile/profile_repository.dart`(已在 Task 5 写好 `uploadPhoto` / `deletePhoto`,本 Task 确认可用即可)
- Test: `app/test/features/profile/photo_grid_test.dart`

**Interfaces:**
- Consumes: Task 5 的 `profileProvider` / `profileRepositoryProvider`;后端 `POST /users/me/photos`(multipart 字段名 `file`)、`DELETE /users/me/photos/{id}`。
- Produces:
  - `PhotoGrid({pickImage, maxCount})` — `pickImage` 签名 `Future<XFile?> Function()`,默认打开相册,测试可注入;钥匙 `photo.add`;删除前弹确认
  - 上传限制:单张 ≤5MB(客户端先拦),最多 6 张;上传成功后自动刷新资料

**为什么要注入 pickImage:** 相册选择走平台通道,单测里无法真的弹相册;把"选一张图"抽成一个函数参数,测试塞个假的 `XFile` 就能跑通整条上传链路。

- [ ] **Step 1:写失败的测试**

新建 `app/test/features/profile/photo_grid_test.dart`:

```dart
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker/image_picker.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/profile/widgets/photo_grid.dart';

import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

Future<void> pumpGrid(WidgetTester tester, ScriptedAdapter adapter,
    {required Future<XFile?> Function() pickImage}) async {
  SharedPreferences.setMockInitialValues({});
  final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
  final refreshDio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
  await tester.pumpWidget(ProviderScope(
    overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(refreshDio),
    ],
    child: MaterialApp(
      home: Scaffold(body: PhotoGrid(pickImage: pickImage)),
    ),
  ));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('选图 → 上传 → 刷新资料', (tester) async {
    var meCalls = 0;
    final adapter = ScriptedAdapter({
      'GET /users/me': (options) {
        meCalls++;
        return ok(profileJson());
      },
      'POST /users/me/photos': (options) =>
          ok(photoJson(9), status: 201),
    });
    await pumpGrid(tester, adapter,
        pickImage: () async =>
            XFile.fromData(Uint8List.fromList(List.filled(10, 1)), name: 'a.png'));

    await tester.tap(find.byKey(const Key('photo.add')));
    await tester.pumpAndSettle();

    expect(adapter.log.where((r) => r.path == '/users/me/photos'), hasLength(1));
    expect(meCalls, 2); // 初次加载 + 上传后刷新
  });

  testWidgets('超过 5MB → 本地拦截,不发请求', (tester) async {
    final adapter = ScriptedAdapter({'GET /users/me': (options) => ok(profileJson())});
    await pumpGrid(tester, adapter,
        pickImage: () async =>
            XFile.fromData(Uint8List(5 * 1024 * 1024 + 1), name: 'big.png'));

    await tester.tap(find.byKey(const Key('photo.add')));
    await tester.pumpAndSettle();

    expect(find.text('图片不能超过 5MB'), findsOneWidget);
    expect(adapter.log.where((r) => r.path == '/users/me/photos'), isEmpty);
  });
}
```

- [ ] **Step 2:运行确认失败**

```bash
../flutter/bin/flutter.bat test test/features/profile/photo_grid_test.dart
```

预期:编译失败(`photo_grid.dart` 不存在)。

- [ ] **Step 3:实现 PhotoGrid**

新建 `app/lib/features/profile/widgets/photo_grid.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../../../core/api_exception.dart';
import '../models.dart';
import '../profile_controller.dart';
import '../profile_repository.dart';

typedef PickImage = Future<XFile?> Function();

Future<XFile?> pickImageFromGallery() => ImagePicker().pickImage(
      source: ImageSource.gallery,
      maxWidth: 1080,
      imageQuality: 85,
    );

const _maxBytes = 5 * 1024 * 1024;

class PhotoGrid extends ConsumerStatefulWidget {
  const PhotoGrid({super.key, this.pickImage = pickImageFromGallery, this.maxCount = 6});

  /// 测试注入用;默认打开系统相册。
  final PickImage pickImage;
  final int maxCount;

  @override
  ConsumerState<PhotoGrid> createState() => _PhotoGridState();
}

class _PhotoGridState extends ConsumerState<PhotoGrid> {
  bool _busy = false;

  void _show(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _add() async {
    final file = await widget.pickImage();
    if (file == null) return;
    final bytes = await file.readAsBytes();
    if (!mounted) return;
    if (bytes.length > _maxBytes) {
      _show('图片不能超过 5MB');
      return;
    }
    setState(() => _busy = true);
    try {
      await ref.read(profileRepositoryProvider).uploadPhoto(bytes, file.name);
      await ref.read(profileProvider.notifier).reload();
    } on ApiException catch (error) {
      if (mounted) _show(error.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _confirmDelete(Photo photo) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('删除这张照片?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('取消')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('删除')),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    try {
      await ref.read(profileRepositoryProvider).deletePhoto(photo.id);
      await ref.read(profileProvider.notifier).reload();
    } on ApiException catch (error) {
      if (mounted) _show(error.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final photos = ref.watch(profileProvider).valueOrNull?.photos ?? const <Photo>[];
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        for (final photo in photos)
          _PhotoTile(photo: photo, onDelete: () => _confirmDelete(photo)),
        if (photos.length < widget.maxCount)
          _AddTile(busy: _busy, onTap: _busy ? null : _add),
      ],
    );
  }
}

class _PhotoTile extends StatelessWidget {
  const _PhotoTile({required this.photo, required this.onDelete});

  final Photo photo;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 88,
      height: 88,
      child: Stack(
        fit: StackFit.expand,
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(8),
            child: Image.network(photo.url, fit: BoxFit.cover,
                errorBuilder: (context, error, stack) => Container(
                      color: Colors.black12,
                      child: const Icon(Icons.broken_image_outlined),
                    )),
          ),
          if (!photo.isApproved)
            Positioned(
              left: 4,
              bottom: 4,
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(
                    color: Colors.black54, borderRadius: BorderRadius.circular(4)),
                child: Text(photo.status == 'pending' ? '待审核' : '已驳回',
                    style: const TextStyle(color: Colors.white, fontSize: 11)),
              ),
            ),
          Positioned(
            right: 0,
            top: 0,
            child: IconButton(
              key: Key('photo.delete.${photo.id}'),
              iconSize: 18,
              onPressed: onDelete,
              icon: const CircleAvatar(radius: 11, child: Icon(Icons.close, size: 14)),
            ),
          ),
        ],
      ),
    );
  }
}

class _AddTile extends StatelessWidget {
  const _AddTile({required this.busy, required this.onTap});

  final bool busy;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      key: const Key('photo.add'),
      onTap: onTap,
      child: Container(
        width: 88,
        height: 88,
        decoration: BoxDecoration(
          border: Border.all(color: Colors.black26),
          borderRadius: BorderRadius.circular(8),
        ),
        child: busy
            ? const Center(
                child: SizedBox(
                    width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2)))
            : const Icon(Icons.add_a_photo_outlined),
      ),
    );
  }
}
```

- [ ] **Step 4:运行测试确认通过**

```bash
../flutter/bin/flutter.bat test test/features/profile && ../flutter/bin/flutter.bat analyze
```

预期:照片部件 2 个用例 OK;analyze 无问题。

- [ ] **Step 5:提交**

```bash
cd "D:/pycharmproject/chat_app" && git add app && git commit -m "feat: photo grid with upload/delete (M2a)"
```

**卡点速查:**
- 上传返回 400"图片不能超过 5MB" → 客户端压缩参数(`maxWidth: 1080, imageQuality: 85`)应已把手机照片压下去;若原图仍超,提示用户换图
- 上传 401 会走"刷新后重放",multipart 重放失败属已知限制(见 Task 2 卡点),让用户重试一次即可
- Web 上 `XFile.path` 是 blob URL → 所以实现用 `readAsBytes` + `MultipartFile.fromBytes`,不用 `fromFile`

---

### Task 7: 编辑资料页 + 表单字段部件 + 标签选择器

**Files:**
- Create: `app/lib/features/profile/widgets/profile_form_fields.dart`、`app/lib/features/profile/widgets/tag_selector.dart`、`app/lib/features/profile/profile_edit_page.dart`
- Modify: `app/lib/router.dart`(`/profile/edit` 换成真页面)
- Test: `app/test/features/profile/profile_edit_page_test.dart`

**Interfaces:**
- Consumes: Task 5 的 `profileProvider` / `tagsProvider`;Task 6 的 `PhotoGrid`。
- Produces:
  - `NicknameField({controller, errorText})`、`GenderSelector({value, onChanged})`、`BirthdayField({value, onChanged})`、`CityField({controller})`、`BioField({controller})` —— 编辑页与引导向导共用
  - `TagSelector({selectedIds, onChanged})`(`Set<int>` 进出)
  - `ProfileEditPage`:钥匙 `edit.save`;PATCH 只发非 null 字段(后端 DateField/ChoiceField 不接受显式 null);生日 <18 本地拦截

- [ ] **Step 1:写失败的测试**

新建 `app/test/features/profile/profile_edit_page_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

void main() {
  testWidgets('改昵称保存 → PATCH 带上表单内容', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /users/tags': (options) => ok([tagJson(1, '运动')]),
      'PATCH /users/me': (options) => ok(profileJson(nickname: '新昵称')),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await tester.tap(navTab('我的'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('编辑资料'));
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('edit.nickname')), '新昵称');
    await tester.tap(find.byKey(const Key('edit.save')));
    await tester.pumpAndSettle();

    final patch = adapter.log.lastWhere((r) => r.method == 'PATCH').data as Map<String, dynamic>;
    expect(patch['nickname'], '新昵称');
    expect(patch['tag_ids'], isEmpty);
    expect(find.text('已保存'), findsOneWidget);
  });

  testWidgets('后端 400(如违规词)→ SnackBar 显示中文提示', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /users/tags': (options) => ok([]),
      'PATCH /users/me': (options) => fail(400, '昵称包含违规内容,请修改'),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await tester.tap(navTab('我的'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('编辑资料'));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('edit.save')));
    await tester.pumpAndSettle();

    expect(find.text('昵称包含违规内容,请修改'), findsOneWidget);
  });
}
```

- [ ] **Step 2:运行确认失败**

```bash
../flutter/bin/flutter.bat test test/features/profile/profile_edit_page_test.dart
```

预期:编译失败(`profile_edit_page.dart` 不存在)。

- [ ] **Step 3:实现共享字段部件**

新建 `app/lib/features/profile/widgets/profile_form_fields.dart`:

```dart
import 'package:flutter/material.dart';

import '../../../core/format.dart';

class NicknameField extends StatelessWidget {
  const NicknameField({super.key, required this.controller, this.errorText});

  final TextEditingController controller;
  final String? errorText;

  @override
  Widget build(BuildContext context) {
    return TextField(
      key: const Key('edit.nickname'),
      controller: controller,
      maxLength: 20,
      decoration: InputDecoration(
        labelText: '昵称',
        counterText: '',
        border: const OutlineInputBorder(),
        errorText: errorText,
      ),
    );
  }
}

class GenderSelector extends StatelessWidget {
  const GenderSelector({super.key, required this.value, required this.onChanged});

  final String? value;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    return SegmentedButton<String>(
      segments: const [
        ButtonSegment(value: 'male', label: Text('男'), icon: Icon(Icons.male)),
        ButtonSegment(value: 'female', label: Text('女'), icon: Icon(Icons.female)),
      ],
      selected: value == null ? const <String>{} : {value!},
      emptySelectionAllowed: true,
      onSelectionChanged: (selection) {
        if (selection.isNotEmpty) onChanged(selection.first);
      },
    );
  }
}

class BirthdayField extends StatelessWidget {
  const BirthdayField({super.key, required this.value, required this.onChanged});

  final DateTime? value;
  final ValueChanged<DateTime> onChanged;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      key: const Key('edit.birthday'),
      onTap: () async {
        final now = DateTime.now();
        final picked = await showDatePicker(
          context: context,
          initialDate: value ?? DateTime(now.year - 25, now.month, now.day),
          firstDate: DateTime(now.year - 100),
          lastDate: DateTime(now.year - 18, now.month, now.day), // 未满 18 岁选不出来
          helpText: '选择生日',
        );
        if (picked != null) onChanged(picked);
      },
      child: InputDecorator(
        decoration: const InputDecoration(labelText: '生日', border: OutlineInputBorder()),
        child: Text(value == null ? '请选择' : formatDate(value!)),
      ),
    );
  }
}

class CityField extends StatelessWidget {
  const CityField({super.key, required this.controller});

  final TextEditingController controller;

  @override
  Widget build(BuildContext context) {
    return TextField(
      key: const Key('edit.city'),
      controller: controller,
      maxLength: 50,
      decoration: const InputDecoration(
        labelText: '城市',
        counterText: '',
        border: OutlineInputBorder(),
      ),
    );
  }
}

class BioField extends StatelessWidget {
  const BioField({super.key, required this.controller});

  final TextEditingController controller;

  @override
  Widget build(BuildContext context) {
    return TextField(
      key: const Key('edit.bio'),
      controller: controller,
      maxLength: 200,
      maxLines: 3,
      decoration: const InputDecoration(
        labelText: '简介',
        border: OutlineInputBorder(),
        alignLabelWithHint: true,
      ),
    );
  }
}
```

新建 `app/lib/features/profile/widgets/tag_selector.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_exception.dart';
import '../profile_controller.dart';

class TagSelector extends ConsumerWidget {
  const TagSelector({super.key, required this.selectedIds, required this.onChanged});

  final Set<int> selectedIds;
  final ValueChanged<Set<int>> onChanged;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tags = ref.watch(tagsProvider);
    return tags.when(
      loading: () => const Padding(
        padding: EdgeInsets.all(8),
        child: Center(child: CircularProgressIndicator()),
      ),
      error: (error, _) => Text(error is ApiException ? error.message : '标签加载失败'),
      data: (list) => Wrap(
        spacing: 8,
        runSpacing: 8,
        children: [
          for (final tag in list)
            FilterChip(
              label: Text(tag.name),
              selected: selectedIds.contains(tag.id),
              onSelected: (selected) {
                final next = {...selectedIds};
                if (selected) {
                  next.add(tag.id);
                } else {
                  next.remove(tag.id);
                }
                onChanged(next);
              },
            ),
        ],
      ),
    );
  }
}
```

- [ ] **Step 4:实现编辑页**

新建 `app/lib/features/profile/profile_edit_page.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_exception.dart';
import '../../core/format.dart';
import 'models.dart';
import 'profile_controller.dart';
import 'widgets/photo_grid.dart';
import 'widgets/profile_form_fields.dart';
import 'widgets/tag_selector.dart';

class ProfileEditPage extends ConsumerStatefulWidget {
  const ProfileEditPage({super.key});

  @override
  ConsumerState<ProfileEditPage> createState() => _ProfileEditPageState();
}

class _ProfileEditPageState extends ConsumerState<ProfileEditPage> {
  final _nickname = TextEditingController();
  final _city = TextEditingController();
  final _bio = TextEditingController();
  String? _gender;
  DateTime? _birthday;
  Set<int> _tagIds = {};
  bool _prefilled = false;
  bool _saving = false;

  @override
  void dispose() {
    _nickname.dispose();
    _city.dispose();
    _bio.dispose();
    super.dispose();
  }

  void _prefill(Profile profile) {
    if (_prefilled) return;
    _prefilled = true;
    _nickname.text = profile.nickname;
    _city.text = profile.city;
    _bio.text = profile.bio;
    _gender = profile.gender;
    _birthday = parseDate(profile.birthday);
    _tagIds = profile.tags.map((tag) => tag.id).toSet();
  }

  void _show(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _save() async {
    final nickname = _nickname.text.trim();
    if (nickname.isEmpty) {
      _show('请填写昵称');
      return;
    }
    if (_birthday != null && !isAtLeast18(_birthday!)) {
      _show('未满 18 周岁,无法使用本应用');
      return;
    }

    final patch = <String, dynamic>{
      'nickname': nickname,
      'city': _city.text.trim(),
      'bio': _bio.text.trim(),
      'tag_ids': _tagIds.toList(),
    };
    if (_gender != null) patch['gender'] = _gender;
    if (_birthday != null) patch['birthday'] = formatDate(_birthday!);

    setState(() => _saving = true);
    try {
      await ref.read(profileProvider.notifier).save(patch);
      if (!mounted) return;
      _show('已保存');
      Navigator.of(context).pop();
    } on ApiException catch (error) {
      if (mounted) _show(error.message);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final profile = ref.watch(profileProvider);
    return Scaffold(
      appBar: AppBar(
        title: const Text('编辑资料'),
        actions: [
          TextButton(
            key: const Key('edit.save'),
            onPressed: _saving ? null : _save,
            child: Text(_saving ? '保存中…' : '保存'),
          ),
        ],
      ),
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
        data: (data) {
          _prefill(data);
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              NicknameField(controller: _nickname),
              const SizedBox(height: 16),
              GenderSelector(value: _gender, onChanged: (value) => setState(() => _gender = value)),
              const SizedBox(height: 16),
              BirthdayField(
                  value: _birthday, onChanged: (value) => setState(() => _birthday = value)),
              const SizedBox(height: 16),
              CityField(controller: _city),
              const SizedBox(height: 16),
              BioField(controller: _bio),
              const SizedBox(height: 16),
              Text('标签', style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 8),
              TagSelector(
                  selectedIds: _tagIds, onChanged: (ids) => setState(() => _tagIds = ids)),
              const SizedBox(height: 24),
              Text('照片', style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 8),
              const PhotoGrid(),
            ],
          );
        },
      ),
    );
  }
}
```

修改 `app/lib/router.dart`:`/profile/edit` 指向真页面:

```dart
import 'features/profile/profile_edit_page.dart';
// ...
      GoRoute(
          path: '/profile/edit',
          builder: (context, state) => const ProfileEditPage()),
```

- [ ] **Step 5:运行测试确认通过**

```bash
../flutter/bin/flutter.bat test && ../flutter/bin/flutter.bat analyze
```

预期:全绿;analyze 无问题。

- [ ] **Step 6:提交**

```bash
cd "D:/pycharmproject/chat_app" && git add app && git commit -m "feat: profile edit page with shared form widgets (M2a)"
```

**卡点速查:**
- PATCH 报"该字段不能为空"(DateField/ChoiceField 收到 null)→ 检查 patch 构造:gender/birthday 为 null 时**不要放键**
- 编辑页首帧昵称是空的 → `_prefill` 只跑一次,若资料还没加载完就先 build 了,`profile.when(data:)` 里再调一次即可(本实现已如此)

---

### Task 8: 资料引导向导(3 步)

**Files:**
- Create: `app/lib/features/onboarding/onboarding_page.dart`
- Modify: `app/lib/router.dart`(`/onboarding` 换成真页面)
- Test: `app/test/features/onboarding/onboarding_page_test.dart`

**Interfaces:**
- Consumes: Task 7 的字段部件/`TagSelector`/`PhotoGrid`;Task 5 的 `profileProvider`;Task 3 的路由。
- Produces:
  - `OnboardingPage`:3 步 PageView(基本资料 → 城市/简介/标签 → 照片),每步「下一步」先 PATCH 再翻页;第 3 步「完成」要求至少 1 张照片,成功后 `/home`;右上「稍后再说」直接 `/home`
  - `validateBasicStep({nickname, gender, birthday})` / `validateAboutStep({city, bio})` → `String?`(错误文案或 null)

**为什么每步单独 PATCH:** 中途退出/网络抖动不丢已填内容;下次进来由资料接口回填,从第 1 步继续。

- [ ] **Step 1:写失败的测试**

新建 `app/test/features/onboarding/onboarding_page_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/onboarding/onboarding_page.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

void main() {
  test('向导校验函数', () {
    expect(validateBasicStep(nickname: '', gender: 'male', birthday: DateTime(2000)),
        '请填写昵称');
    expect(validateBasicStep(nickname: '小明', gender: null, birthday: DateTime(2000)),
        '请选择性别');
    expect(
        validateBasicStep(nickname: '小明', gender: 'male', birthday: DateTime(2010)), '未满 18 周岁,无法使用本应用');
    expect(validateBasicStep(nickname: '小明', gender: 'male', birthday: DateTime(2000)), isNull);
    expect(validateAboutStep(city: '', bio: '你好'), '请填写城市');
    expect(validateAboutStep(city: '上海', bio: ''), '请填写简介');
    expect(validateAboutStep(city: '上海', bio: '你好'), isNull);
  });

  testWidgets('从发现页引导卡进入向导;第 1 步已有数据 → 下一步 PATCH 基本资料', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson(
            missing: ['city', 'bio', 'photos'],
            city: '',
            bio: '',
          )),
      'GET /users/tags': (options) => ok([tagJson(1, '运动')]),
      'PATCH /users/me': (options) => ok(profileJson(missing: ['photos'])),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('discovery.goOnboarding')));
    await tester.pumpAndSettle();
    expect(find.text('第 1 步 / 共 3 步'), findsOneWidget);

    await tester.tap(find.byKey(const Key('onboarding.next')));
    await tester.pumpAndSettle();

    final patch = adapter.log.lastWhere((r) => r.method == 'PATCH').data as Map<String, dynamic>;
    expect(patch, {'nickname': '小明', 'gender': 'male', 'birthday': '2000-01-01'});
    expect(find.text('第 2 步 / 共 3 步'), findsOneWidget);
  });

  testWidgets('第 2 步校验:缺城市 → 提示且不发请求', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson(
            missing: ['city', 'bio', 'photos'],
            city: '',
            bio: '',
          )),
      'GET /users/tags': (options) => ok([]),
      'PATCH /users/me': (options) => ok(profileJson(missing: ['photos'])),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('discovery.goOnboarding')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('onboarding.next')));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('onboarding.next')));
    await tester.pumpAndSettle();

    expect(find.text('请填写城市'), findsOneWidget);
    expect(adapter.log.where((r) => r.method == 'PATCH'), hasLength(1)); // 只有第 1 步那次
    expect(find.text('第 2 步 / 共 3 步'), findsOneWidget); // 没翻页
  });
}
```

- [ ] **Step 2:运行确认失败**

```bash
../flutter/bin/flutter.bat test test/features/onboarding
```

预期:编译失败(`onboarding_page.dart` 不存在)。

- [ ] **Step 3:实现向导**

新建 `app/lib/features/onboarding/onboarding_page.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/format.dart';
import '../profile/models.dart';
import '../profile/profile_controller.dart';
import '../profile/widgets/photo_grid.dart';
import '../profile/widgets/profile_form_fields.dart';
import '../profile/widgets/tag_selector.dart';

String? validateBasicStep(
    {required String nickname, required String? gender, required DateTime? birthday}) {
  if (nickname.isEmpty) return '请填写昵称';
  if (gender == null) return '请选择性别';
  if (birthday == null) return '请选择生日';
  if (!isAtLeast18(birthday)) return '未满 18 周岁,无法使用本应用';
  return null;
}

String? validateAboutStep({required String city, required String bio}) {
  if (city.isEmpty) return '请填写城市';
  if (bio.isEmpty) return '请填写简介';
  return null;
}

class OnboardingPage extends ConsumerStatefulWidget {
  const OnboardingPage({super.key});

  @override
  ConsumerState<OnboardingPage> createState() => _OnboardingPageState();
}

class _OnboardingPageState extends ConsumerState<OnboardingPage> {
  final _pageController = PageController();
  final _nickname = TextEditingController();
  final _city = TextEditingController();
  final _bio = TextEditingController();
  String? _gender;
  DateTime? _birthday;
  Set<int> _tagIds = {};
  bool _prefilled = false;
  bool _busy = false;
  int _step = 0;

  @override
  void dispose() {
    _pageController.dispose();
    _nickname.dispose();
    _city.dispose();
    _bio.dispose();
    super.dispose();
  }

  void _prefill(Profile profile) {
    if (_prefilled) return;
    _prefilled = true;
    _nickname.text = profile.nickname;
    _city.text = profile.city;
    _bio.text = profile.bio;
    _gender = profile.gender;
    _birthday = parseDate(profile.birthday);
    _tagIds = profile.tags.map((tag) => tag.id).toSet();
  }

  void _show(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  void _goToStep(int step) {
    setState(() => _step = step);
    _pageController.animateToPage(step,
        duration: const Duration(milliseconds: 250), curve: Curves.easeOut);
  }

  Future<void> _next() async {
    Map<String, dynamic>? patch;
    if (_step == 0) {
      final error = validateBasicStep(
          nickname: _nickname.text.trim(), gender: _gender, birthday: _birthday);
      if (error != null) {
        _show(error);
        return;
      }
      patch = {
        'nickname': _nickname.text.trim(),
        'gender': _gender,
        'birthday': formatDate(_birthday!),
      };
    } else if (_step == 1) {
      final error = validateAboutStep(city: _city.text.trim(), bio: _bio.text.trim());
      if (error != null) {
        _show(error);
        return;
      }
      patch = {
        'city': _city.text.trim(),
        'bio': _bio.text.trim(),
        'tag_ids': _tagIds.toList(),
      };
    } else {
      await _finish();
      return;
    }

    setState(() => _busy = true);
    try {
      await ref.read(profileProvider.notifier).save(patch);
      if (!mounted) return;
      _goToStep(_step + 1);
    } on ApiException catch (error) {
      if (mounted) _show(error.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _finish() async {
    setState(() => _busy = true);
    try {
      await ref.read(profileProvider.notifier).reload();
      if (!mounted) return;
      final profile = ref.read(profileProvider).valueOrNull;
      if (profile == null || profile.photos.where((photo) => photo.isApproved).isEmpty) {
        _show('至少上传一张照片');
        return;
      }
      context.go('/home');
    } on ApiException catch (error) {
      if (mounted) _show(error.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final profile = ref.watch(profileProvider);
    return Scaffold(
      appBar: AppBar(
        title: const Text('完善资料'),
        actions: [
          TextButton(
            onPressed: () => context.go('/home'),
            child: const Text('稍后再说'),
          ),
        ],
      ),
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
        data: (data) {
          _prefill(data);
          return Column(
            children: [
              Padding(
                padding: const EdgeInsets.all(16),
                child: LinearProgressIndicator(value: (_step + 1) / 3),
              ),
              Text('第 ${_step + 1} 步 / 共 3 步'),
              Expanded(
                child: PageView(
                  controller: _pageController,
                  physics: const NeverScrollableScrollPhysics(),
                  children: [
                    _StepBasic(
                      nickname: _nickname,
                      gender: _gender,
                      birthday: _birthday,
                      onGenderChanged: (value) => setState(() => _gender = value),
                      onBirthdayChanged: (value) => setState(() => _birthday = value),
                    ),
                    _StepAbout(
                      city: _city,
                      bio: _bio,
                      tagIds: _tagIds,
                      onTagsChanged: (ids) => setState(() => _tagIds = ids),
                    ),
                    const _StepPhotos(),
                  ],
                ),
              ),
              Padding(
                padding: const EdgeInsets.all(16),
                child: Row(
                  children: [
                    if (_step > 0)
                      OutlinedButton(
                        onPressed: _busy ? null : () => _goToStep(_step - 1),
                        child: const Text('上一步'),
                      ),
                    const Spacer(),
                    FilledButton(
                      key: const Key('onboarding.next'),
                      onPressed: _busy ? null : _next,
                      child: Text(_step == 2 ? '完成' : '下一步'),
                    ),
                  ],
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}

class _StepBasic extends StatelessWidget {
  const _StepBasic({
    required this.nickname,
    required this.gender,
    required this.birthday,
    required this.onGenderChanged,
    required this.onBirthdayChanged,
  });

  final TextEditingController nickname;
  final String? gender;
  final DateTime? birthday;
  final ValueChanged<String> onGenderChanged;
  final ValueChanged<DateTime> onBirthdayChanged;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        NicknameField(controller: nickname),
        const SizedBox(height: 16),
        GenderSelector(value: gender, onChanged: onGenderChanged),
        const SizedBox(height: 16),
        BirthdayField(value: birthday, onChanged: onBirthdayChanged),
      ],
    );
  }
}

class _StepAbout extends StatelessWidget {
  const _StepAbout({
    required this.city,
    required this.bio,
    required this.tagIds,
    required this.onTagsChanged,
  });

  final TextEditingController city;
  final TextEditingController bio;
  final Set<int> tagIds;
  final ValueChanged<Set<int>> onTagsChanged;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        CityField(controller: city),
        const SizedBox(height: 16),
        BioField(controller: bio),
        const SizedBox(height: 16),
        Text('标签(可多选)', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        TagSelector(selectedIds: tagIds, onChanged: onTagsChanged),
      ],
    );
  }
}

class _StepPhotos extends StatelessWidget {
  const _StepPhotos();

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: const [
        Text('上传至少 1 张照片(最多 6 张),让别人认识你'),
        SizedBox(height: 16),
        PhotoGrid(),
      ],
    );
  }
}
```

修改 `app/lib/router.dart`:`/onboarding` 指向真页面:

```dart
import 'features/onboarding/onboarding_page.dart';
// ...
      GoRoute(path: '/onboarding', builder: (context, state) => const OnboardingPage()),
```

- [ ] **Step 4:运行测试确认通过**

```bash
../flutter/bin/flutter.bat test && ../flutter/bin/flutter.bat analyze
```

预期:全绿;analyze 无问题。

- [ ] **Step 5:提交**

```bash
cd "D:/pycharmproject/chat_app" && git add app && git commit -m "feat: 3-step onboarding wizard (M2a)"
```

**卡点速查:**
- 第 2 步测试里 PATCH 有两次 → `_next()` 的 `_busy` 没生效(连续点击);按钮已用 `_busy` 禁用,测试里用 `pumpAndSettle` 等完再点
- 向导中途杀掉 App 再进 → 从发现页引导卡重进,内容由 `GET /users/me` 回填,是预期行为

---

### Task 9: 偏好设置页 + 设置/退出登录

**Files:**
- Create: `app/lib/features/profile/preference_page.dart`、`app/lib/features/settings/settings_page.dart`
- Modify: `app/lib/router.dart`(`/preference`、`/settings` 换成真页面)
- Test: `app/test/features/profile/preference_page_test.dart`、`app/test/features/settings/settings_page_test.dart`

**Interfaces:**
- Consumes: Task 5 的 `profileProvider`;Task 3 的 `sessionProvider.logout()`。
- Produces:
  - `PreferencePage`:目标性别(不限/男/女 → `target_gender: null/male/female`)、年龄区间(`RangeSlider` 18–99)、城市(可空);钥匙 `preference.save`
  - `SettingsPage`:退出登录(确认弹窗)→ `sessionProvider.logout()` + `ref.invalidate(profileProvider)` → 自动回登录页

- [ ] **Step 1:写失败的测试**

新建 `app/test/features/settings/settings_page_test.dart`:

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

void main() {
  testWidgets('退出登录 → 清空凭证回到登录页', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await tester.tap(navTab('我的'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('设置'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('退出登录'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('退出'));
    await tester.pumpAndSettle();

    expect(find.text('获取验证码'), findsOneWidget); // 回到登录页
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString('auth.refresh'), isNull);
  });
}
```

新建 `app/test/features/profile/preference_page_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

void main() {
  testWidgets('设置偏好并保存 → PATCH 内容正确', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'PATCH /users/me/preference': (options) =>
          ok({'target_gender': 'female', 'age_min': 20, 'age_max': 30, 'city': ''}),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await tester.tap(navTab('我的'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('想找的人'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('女'));
    await tester.tap(find.byKey(const Key('preference.save')));
    await tester.pumpAndSettle();

    final patch = adapter.log
        .lastWhere((r) => r.method == 'PATCH')
        .data as Map<String, dynamic>;
    expect(patch['target_gender'], 'female');
    expect(patch['age_min'], 18);
    expect(patch['age_max'], 99);
  });
}
```

- [ ] **Step 2:运行确认失败**

```bash
../flutter/bin/flutter.bat test test/features/settings test/features/profile/preference_page_test.dart
```

预期:编译失败 / 断言失败(还是占位页)。

- [ ] **Step 3:实现偏好页**

新建 `app/lib/features/profile/preference_page.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_exception.dart';
import 'models.dart';
import 'profile_controller.dart';
import 'profile_repository.dart';

class PreferencePage extends ConsumerStatefulWidget {
  const PreferencePage({super.key});

  @override
  ConsumerState<PreferencePage> createState() => _PreferencePageState();
}

class _PreferencePageState extends ConsumerState<PreferencePage> {
  final _city = TextEditingController();
  String? _targetGender;
  RangeValues _ageRange = const RangeValues(18, 99);
  bool _prefilled = false;
  bool _saving = false;

  @override
  void dispose() {
    _city.dispose();
    super.dispose();
  }

  void _prefill(Preference preference) {
    if (_prefilled) return;
    _prefilled = true;
    _targetGender = preference.targetGender;
    _ageRange = RangeValues(
      preference.ageMin.toDouble(),
      preference.ageMax.toDouble().clamp(18, 99),
    );
    _city.text = preference.city;
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    try {
      await ref.read(profileRepositoryProvider).updatePreference({
        'target_gender': _targetGender,
        'age_min': _ageRange.start.round(),
        'age_max': _ageRange.end.round(),
        'city': _city.text.trim(),
      });
      if (!mounted) return;
      ScaffoldMessenger.of(context)
        ..hideCurrentSnackBar()
        ..showSnackBar(const SnackBar(content: Text('已保存')));
      Navigator.of(context).pop();
    } on ApiException catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
          ..hideCurrentSnackBar()
          ..showSnackBar(SnackBar(content: Text(error.message)));
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final profile = ref.watch(profileProvider);
    return Scaffold(
      appBar: AppBar(
        title: const Text('想找的人'),
        actions: [
          TextButton(
            key: const Key('preference.save'),
            onPressed: _saving ? null : _save,
            child: Text(_saving ? '保存中…' : '保存'),
          ),
        ],
      ),
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
        data: (data) {
          _prefill(data.preference);
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Text('我想找', style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 8),
              SegmentedButton<String>(
                segments: const [
                  ButtonSegment(value: 'any', label: Text('不限')),
                  ButtonSegment(value: 'male', label: Text('男')),
                  ButtonSegment(value: 'female', label: Text('女')),
                ],
                selected: {_targetGender ?? 'any'},
                onSelectionChanged: (selection) => setState(() {
                  final value = selection.first;
                  _targetGender = value == 'any' ? null : value;
                }),
              ),
              const SizedBox(height: 24),
              Text('年龄 ${_ageRange.start.round()} – ${_ageRange.end.round()} 岁',
                  style: Theme.of(context).textTheme.titleMedium),
              RangeSlider(
                values: _ageRange,
                min: 18,
                max: 99,
                divisions: 81,
                labels: RangeLabels(_ageRange.start.round().toString(),
                    _ageRange.end.round().toString()),
                onChanged: (values) => setState(() => _ageRange = values),
              ),
              const SizedBox(height: 16),
              TextField(
                key: const Key('preference.city'),
                controller: _city,
                maxLength: 50,
                decoration: const InputDecoration(
                  labelText: '城市(留空 = 不限)',
                  counterText: '',
                  border: OutlineInputBorder(),
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}
```

- [ ] **Step 4:实现设置页**

新建 `app/lib/features/settings/settings_page.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../auth/session.dart';
import '../profile/profile_controller.dart';

class SettingsPage extends ConsumerWidget {
  const SettingsPage({super.key});

  Future<void> _logout(BuildContext context, WidgetRef ref) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('退出登录?'),
        content: const Text('退出后需要重新用手机号登录'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('取消')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('退出')),
        ],
      ),
    );
    if (confirmed != true) return;
    await ref.read(sessionProvider.notifier).logout();
    ref.invalidate(profileProvider); // 别把上一个账号的资料留给下一个
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      appBar: AppBar(title: const Text('设置')),
      body: ListView(
        children: [
          ListTile(
            leading: const Icon(Icons.logout, color: Colors.red),
            title: const Text('退出登录', style: TextStyle(color: Colors.red)),
            onTap: () => _logout(context, ref),
          ),
        ],
      ),
    );
  }
}
```

修改 `app/lib/router.dart`:

```dart
import 'features/profile/preference_page.dart';
import 'features/settings/settings_page.dart';
// ...
      GoRoute(path: '/preference', builder: (context, state) => const PreferencePage()),
      GoRoute(path: '/settings', builder: (context, state) => const SettingsPage()),
```

- [ ] **Step 5:运行测试确认通过**

```bash
../flutter/bin/flutter.bat test && ../flutter/bin/flutter.bat analyze
```

预期:全绿;analyze 无问题。

- [ ] **Step 6:提交**

```bash
cd "D:/pycharmproject/chat_app" && git add app && git commit -m "feat: preference page + settings/logout (M2a)"
```

**卡点速查:**
- 保存偏好报"该字段不能为空" → `target_gender: null` 后端允许(可空 ChoiceField);报错则是 age 越界,确认 slider 范围 18–99
- 退出后还能看到上个账号的资料 → `profileProvider` 是 keep-alive,记得 `ref.invalidate`;别改回 autoDispose(编辑页会反复重拉)

---

### Task 10: 全量验证 + 模拟器联调 + 文档收尾

**Files:**
- Modify: `CLAUDE.md`
- 无新代码

**Interfaces:**
- Consumes: 前面全部 Task;后端已跑起来(单进程)。
- Produces: 模拟器上的真机联调记录;CLAUDE.md 更新到 M2a 状态;M2b 交接说明。

- [ ] **Step 1:全量静态检查与测试**

```bash
cd "D:/pycharmproject/chat_app/app" && ../flutter/bin/flutter.bat analyze && ../flutter/bin/flutter.bat test
```

预期:`No issues found!` + 全部用例 OK(约 25+)。

- [ ] **Step 2:确认后端干净启动(单进程!)**

```bash
netstat -ano | grep :8000
```

有残留就按 CLAUDE.md 的办法杀掉旧 PID,然后:

```bash
cd "D:/pycharmproject/chat_app/chatapp" && python manage.py runserver
```

- [ ] **Step 3:模拟器联调**

```bash
cd "D:/pycharmproject/chat_app/app" && ../flutter/bin/flutter.bat run -d emulator-5554 --dart-define=API_BASE=http://10.0.2.2:8000/api/v1
```

手测清单(逐项勾):

- 新手机号注册(验证码 123456)→ 进 3 步向导 → 第 1 步填昵称/性别/生日 → 第 2 步城市/简介/标签 → 第 3 步传 1 张照片 → 完成 → 主框架
- 模拟器相册是空的 → 先推一张图进去:`adb push 本地图片.png /sdcard/Pictures/sample.png`,再 `adb shell am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file:///sdcard/Pictures/sample.png`(不行就重启模拟器);实在不行跳过照片,在电脑端用 `run -d windows` 走一遍文件选择
- 杀 App 重启 → 直接进主框架(静默刷新),不要求重新登录
- 我的 → 编辑资料改昵称 → 保存 → 立刻可见;想找的人 → 设置偏好 → 保存
- 退出登录 → 回登录页;再登录 → 资料还在(后端数据)
- 后端 Ctrl+C 后再操作 → 界面出现中文错误提示而不是崩(网络错误兜底)

- [ ] **Step 4:更新 CLAUDE.md**

- 「当前进度」改成:M2a 完成(前端基建+登录+资料引导+主框架/我的资料/偏好/退出),下一步 M2b(卡片流+配对动效)
- 「目录结构」的 `app/` 行更新:`lib/core`(网络/会话/错误)、`lib/features/*`(auth/onboarding/discovery/chat/profile/settings/shell)、`lib/router.dart`;测试:`test/support/scripted_adapter.dart` 假网络、`test/support/harness.dart` 起整个 App
- 「常用命令」补:`../flutter/bin/flutter.bat test test/core` 等单目录跑法
- 新增「前端约定与踩坑」小节:401 静默刷新机制(TokenStore 通知 → 会话踢回登录)、`--dart-define=API_BASE`、倒计时 Timer 与 `pumpAndSettle` 的坑、ScriptedAdapter 只铺已用路由、照片上传走 bytes、模拟器推图命令

- [ ] **Step 5:勾选本计划 + 验收清单,提交**

```bash
cd "D:/pycharmproject/chat_app" && git add CLAUDE.md docs/superpowers/plans/2026-09-10-m2a-auth-onboarding.md && git commit -m "docs: M2a done — app foundation/auth/onboarding (M2a)"
```

---

## M2a 验收清单(全部通过即进入 M2b 计划)

- [ ] `flutter analyze` 零告警;`flutter test` 全绿(离线,无真实网络)
- [ ] 后端 `python manage.py test` 仍全绿(本计划没动后端,回归确认)
- [ ] 模拟器:新号注册 → 3 步向导(含照片)→ 主框架;杀进程重启保持登录
- [ ] 资料未完善时发现 Tab 显示引导卡;完善后消失
- [ ] 编辑资料 / 照片增删 / 偏好设置 / 退出登录 全部可用,错误有中文提示
- [ ] CLAUDE.md 更新完毕;`git status` 干净

## 留给 M2b / M2c 的接口约定

| 事项 | 约定 |
|---|---|
| 卡片流 | 换掉 `features/discovery/discovery_page.dart` 的占位:数据 `GET /discovery/candidates`(`user_id/nickname/gender/age/city/bio/tags/photos`),滑动 `POST /discovery/swipe {target_user_id, action}` |
| 配对动效 | `POST /discovery/swipe` 返回 `{"matched": true}` 时播;重复滑卡安全(幂等) |
| IM 登录时机 | 登录成功(`sessionProvider` → `SessionLoggedIn`)与启动鉴权成功后调;`userId` 从 `TokenStore.userId` 取,IM ID = `u{userId}`;userSig 走 `POST /im/user_sig` |
| 会话缓存 | `GET /matches` 预热 `userId → 昵称/头像` 本地缓存(启动 + 配对成功时刷新) |
| 灰条消息 | `TIMCustomElem`,`Data = {"type":"match_notice"}`,`Desc = "你们已互相喜欢,开始聊天吧"`;聊天页拦截渲染成居中灰条 |
| 退出登录 | M2c 起必须补 IM 登出 + 清缓存(spec §7.5 切换账号防串号),目前只清 JWT |
| 对方资料卡 | 「点头像看公开资料 + 举报/拉黑入口」依赖 `GET /users/{id}`(后端还没有)与 `Block`/`Report` 接口,随 **M3 合规收尾**一起做 |
| 错误处理 | 403 = 封禁/未完善;429 = 操作太快(前端可静默退避) |
