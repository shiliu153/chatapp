import 'package:flutter/foundation.dart';
import 'package:jpush_flutter/jpush_flutter.dart';
import 'package:jpush_flutter/jpush_interface.dart';

import '../config.dart';
import 'push_service.dart';

/// 极光实现:全项目唯一 import `jpush_flutter` 的文件。
class JPushPushService implements PushService {
  JPushPushService({String? appKey}) : _appKey = appKey ?? jpushAppKey;

  final String _appKey;
  final JPushFlutterInterface _jpush = JPush.newJPush();
  bool _started = false;

  @override
  Future<void> start({required void Function(String deeplink) onOpen}) async {
    if (_started) return;
    _started = true;
    try {
      _jpush.setup(
        appKey: _appKey,
        channel: 'developer-default',
        production: !kDebugMode,
        debug: kDebugMode,
      );
      // 前台不弹通知栏:正在用 App 时,页面自身的刷新比系统通知更合适
      _jpush.setUnShowAtTheForeground(unShow: true);
      _jpush.addEventHandler(onOpenNotification: (Map<String, dynamic> message) async {
        final extras = message['extras'];
        final path = extras is Map ? extras['deeplink'] : null;
        if (path is String && path.isNotEmpty) onOpen(path);
      });
      _jpush.requestRequiredPermission();
      // 冷启动兜底:iOS 会把「点通知启动 App」的那条缓存起来(Android 一般由
      // onOpenNotification 直接回调),取到就按 deeplink 打开。
      final launch = await _jpush.getLaunchAppNotification();
      final launchExtras = launch['extras'];
      final launchPath = launchExtras is Map ? launchExtras['deeplink'] : null;
      if (launchPath is String && launchPath.isNotEmpty) onOpen(launchPath);
    } catch (error) {
      debugPrint('推送初始化失败: $error');
    }
  }

  @override
  Future<String?> registrationId() async {
    try {
      final id = await _jpush.getRegistrationID();
      return id.isEmpty ? null : id;
    } catch (error) {
      debugPrint('取 registration_id 失败: $error');
      return null;
    }
  }

  @override
  Future<bool> isNotificationEnabled() async {
    try {
      return await _jpush.isNotificationEnabled();
    } catch (error) {
      debugPrint('查询通知权限失败: $error');
      return false;
    }
  }

  @override
  Future<void> openNotificationSettings() async {
    try {
      _jpush.openSettingsForNotification();
    } catch (error) {
      debugPrint('打开系统通知设置失败: $error');
    }
  }

  @override
  Future<void> stop() async {
    try {
      await _jpush.stopPush();
    } catch (error) {
      debugPrint('停止推送失败: $error');
    }
  }
}
