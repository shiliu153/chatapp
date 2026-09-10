import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api_exception.dart';
import 'im_client.dart';
import 'im_repository.dart';
import 'tencent_im_client.dart';

/// 真实 IM 客户端(全局单例语义);测试里 override 成 FakeImClient。
final imClientProvider = Provider<ImClient>((ref) => TencentImClient());

sealed class ImStatus {
  const ImStatus();
}

class ImLoggedOut extends ImStatus {
  const ImLoggedOut();
}

class ImConnecting extends ImStatus {
  const ImConnecting();
}

class ImLoggedIn extends ImStatus {
  const ImLoggedIn(this.imUserId);
  final String imUserId;
}

class ImFailed extends ImStatus {
  const ImFailed(this.message);
  final String message;
}

/// IM 登录生命周期:谁触发、什么时候重登、失败怎么降级,全收在这。
class ImManager extends Notifier<ImStatus> {
  Future<void> _queue = Future.value();

  @override
  ImStatus build() {
    final client = ref.watch(imClientProvider);
    final sub = client.events.listen(_onEvent);
    ref.onDispose(sub.cancel);
    return const ImLoggedOut();
  }

  void _onEvent(ImEvent event) {
    switch (event) {
      case ImSigExpired():
        unawaited(_run(_doLogin)); // 在线期间签名过期:重新拉一张再登
      case ImKickedOffline():
        state = const ImFailed('账号已在其他设备登录');
      case ImNewMessage() || ImConversationsChanged():
        break; // 会话/聊天控制器各自消费
    }
  }

  /// 登录成功 / 启动鉴权成功后由 SessionController 调;不阻塞进主界面。
  Future<void> login() => _run(_doLogin);

  Future<void> retry() => login();

  Future<void> logout() => _run(() async {
        try {
          await ref.read(imClientProvider).logout();
        } catch (_) {
          // 登出失败也要把本地状态清掉:JWT 都没了,不能停在上一个号的登录态
        }
        state = const ImLoggedOut();
      });

  Future<void> _doLogin() async {
    state = const ImConnecting();
    try {
      final sig = await ref.read(imRepositoryProvider).fetchUserSig();
      final client = ref.read(imClientProvider);
      await client.init(sdkAppId: sig.sdkAppId);
      await client.login(userId: sig.imUserId, userSig: sig.userSig);
      state = ImLoggedIn(sig.imUserId);
    } on ApiException catch (error) {
      state = ImFailed(error.message);
    } on ImException catch (error) {
      state = ImFailed('IM 登录失败(${error.code})');
    } catch (_) {
      state = ImFailed('IM 登录失败,请重试');
    }
  }

  /// 登录/登出排队执行:SDK 要求「登出没结束不能再次登录」,排队最省心。
  Future<void> _run(Future<void> Function() action) {
    final next = _queue.then((_) => action());
    _queue = next.then((_) {}, onError: (_, _) {});
    return next;
  }
}

final imStatusProvider = NotifierProvider<ImManager, ImStatus>(ImManager.new);
