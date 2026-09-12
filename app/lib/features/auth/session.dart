import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_exception.dart';
import '../../core/providers.dart';
import '../../im/im_manager.dart';
import '../discovery/discovery_controller.dart';
import '../moderation/moderation_controller.dart';
import '../profile/profile_controller.dart';
import '../profile/profile_repository.dart';
import 'auth_repository.dart';

/// 登录态心跳间隔;override 成 null 可关闭(测试用)。
final heartbeatIntervalProvider =
    Provider<Duration?>((ref) => const Duration(seconds: 45));

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
  Timer? _heartbeat;

  @override
  SessionState build() {
    final store = ref.watch(tokenStoreProvider);
    void onTokensCleared() => _forceLogout();
    store.addListener(onTokensCleared);
    ref.onDispose(() => store.removeListener(onTokensCleared));
    ref.onDispose(() => _heartbeat?.cancel());
    return const SessionLoading();
  }

  /// 登录态心跳:定期轻量请求一次,被顶号/封禁后不用等用户操作页面,
  /// 最多一个周期内就会被 40101 顶回登录页(测试里把间隔 override 成 null 关掉)。
  void _startHeartbeat() {
    _heartbeat?.cancel();
    _heartbeat = null;
    final interval = ref.read(heartbeatIntervalProvider);
    if (interval == null || interval <= Duration.zero) return;
    _heartbeat = Timer.periodic(interval, (_) async {
      try {
        await ref.read(profileRepositoryProvider).fetchMe();
      } catch (_) {
        // 鉴权类失败由 AuthInterceptor 统一处理;网络抖动忽略,下个周期再试
      }
    });
  }

  /// 网络级失败的重试参数:启动时偶发抖动别直接弹错误页(401 不重试)。
  /// 非 const:测试里把间隔调成 0,避免白等。
  static int bootRetries = 2;
  static Duration bootRetryDelay = Duration(seconds: 1);

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
      await _refreshWithRetry();
      if (state is! SessionLoggedIn) {
        state = const SessionLoggedIn();
      }
      _startHeartbeat();
      unawaited(ref.read(imStatusProvider.notifier).login());
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

  /// 换新 access;网络级失败(超时/连不上)短暂等待后重试,业务错误(401 等)直接抛。
  Future<void> _refreshWithRetry() async {
    for (var attempt = 0; ; attempt++) {
      try {
        await ref.read(tokenRefresherProvider).refresh();
        return;
      } on ApiException catch (error) {
        if (error.statusCode != null || attempt >= bootRetries) rethrow;
        await Future.delayed(bootRetryDelay);
      }
    }
  }

  /// 登录成功 = 换了(或重登)账号:先作废上一个账号留下的业务缓存。
  /// 这些 provider 不随会话状态自动重建,不清的话新账号会读到旧数据
  /// (2026-09-12 手测:被顶号后换号登录,我的页仍显示上一个账号)。
  /// 新增按用户隔离的缓存 provider 要加进清单;随 IM 登录态重建的
  /// (会话列表、matchCache)不用管。
  void _resetUserScopedCaches() {
    ref.invalidate(profileProvider);
    ref.invalidate(discoveryProvider);
    ref.invalidate(blockedUsersProvider);
    // 整族失效:资料卡是公开数据,但「能不能看到」随号主而变(拉黑/重封禁),
    // 留着上一个号看过的卡会让新号绕过可见性判断
    ref.invalidate(userProfileProvider);
  }

  Future<LoginResult> login(String phone, String code) async {
    final result = await ref.read(authRepositoryProvider).verifySms(phone, code);
    await ref.read(tokenStoreProvider).save(
          access: result.access,
          refresh: result.refresh,
          userId: result.userId,
        );
    _resetUserScopedCaches();
    state = const SessionLoggedIn();
    _startHeartbeat();
    // IM 登录不阻塞进主界面;失败时聊天页有「重试」
    unawaited(ref.read(imStatusProvider.notifier).login());
    return result;
  }

  Future<void> logout() async {
    // 清凭证会通知监听者;M2c 接入 IM 后这里还要 IM 登出 + 清本地缓存(spec §7.5)
    _heartbeat?.cancel();
    _heartbeat = null;
    await ref.read(tokenStoreProvider).clear();
    state = const SessionLoggedOut();
  }

  void _forceLogout() {
    _heartbeat?.cancel();
    _heartbeat = null;
    if (state is! SessionLoggedOut) {
      state = const SessionLoggedOut();
    }
    // JWT 一清就 IM 登出(防串号);IM 清理统一挂在这条唯一通道上
    unawaited(ref.read(imStatusProvider.notifier).logout());
  }
}

final sessionProvider =
    NotifierProvider<SessionController, SessionState>(SessionController.new);
