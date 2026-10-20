import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../features/auth/session.dart';
import '../../router.dart';
import 'jpush_push_service.dart';
import 'push_repository.dart';
import 'push_service.dart';

/// 推送生命周期:登录上报、登出解绑、点击通知路由。
enum PushStatus { idle, registering, ready, failed }

/// 真实推送服务(全局单例语义);测试里 override 成 FakePushService。
final pushServiceProvider = Provider<PushService>((ref) => JPushPushService());

class PushController extends Notifier<PushStatus> {
  String? _registrationId;
  String? _pendingPath;
  bool _started = false;

  @override
  PushStatus build() {
    ref.listen(sessionProvider, (_, next) {
      switch (next) {
        case SessionLoggedIn():
          unawaited(_register().then((_) => _flushPending()));
        case SessionLoggedOut():
          unawaited(_unregister());
        default:
          break;
      }
    });
    if (ref.read(sessionProvider) is SessionLoggedIn) {
      unawaited(_register().then((_) => _flushPending()));
    }
    return PushStatus.idle;
  }

  Future<void> _register() async {
    if (_started) return;
    _started = true;
    state = PushStatus.registering;
    try {
      final service = ref.read(pushServiceProvider);
      await service.start(onOpen: _openDeeplink);
      final id = await service.registrationId();
      if (id == null || id.isEmpty) {
        state = PushStatus.failed;
        return;
      }
      _registrationId = id;
      await ref.read(pushRepositoryProvider).registerDevice(id);
      state = PushStatus.ready;
    } catch (error) {
      debugPrint('推送注册失败: $error');
      state = PushStatus.failed;
    }
  }

  Future<void> _unregister() async {
    final id = _registrationId;
    _registrationId = null;
    _pendingPath = null;   // 换号后不能沿用上一个账号的待跳转路径
    _started = false;
    try {
      if (id != null) await ref.read(pushRepositoryProvider).unregisterDevice(id);
    } catch (error) {
      debugPrint('推送解绑失败: $error');
    }
    try {
      await ref.read(pushServiceProvider).stop();
    } catch (error) {
      debugPrint('停止推送失败: $error');
    }
    state = PushStatus.idle;
  }

  void _openDeeplink(String path) {
    if (!path.startsWith('/')) return;
    if (ref.read(sessionProvider) is! SessionLoggedIn) {
      // 冷启动时登录态还在恢复:先记下,登录成功后补跳
      _pendingPath = path;
      return;
    }
    ref.read(pushDeeplinkHandlerProvider)(path);
  }

  void _flushPending() {
    final path = _pendingPath;
    if (path == null) return;
    _pendingPath = null;
    if (ref.read(sessionProvider) is! SessionLoggedIn) {
      _pendingPath = path;
      return;
    }
    ref.read(pushDeeplinkHandlerProvider)(path);
  }
}

/// 点击通知后的跳转动作;测试里 override 成记录器,避免真的驱动 GoRouter。
final pushDeeplinkHandlerProvider = Provider<void Function(String)>((ref) => (path) {
      ref.read(routerProvider).go(path);
    });

final pushControllerProvider =
    NotifierProvider<PushController, PushStatus>(PushController.new);
