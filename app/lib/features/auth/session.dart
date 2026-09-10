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

final sessionProvider =
    NotifierProvider<SessionController, SessionState>(SessionController.new);
