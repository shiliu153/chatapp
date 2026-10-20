import 'package:chatapp_app/core/push/push_service.dart';

/// 推送替身:记录调用、可注入 registration_id、可手动触发点击。
class FakePushService implements PushService {
  FakePushService({this.registrationIdValue = 'rid-test', this.notificationEnabled = true});

  final String? registrationIdValue;
  bool notificationEnabled;
  int startCalls = 0;
  int stopCalls = 0;
  int openSettingsCalls = 0;
  void Function(String deeplink)? _onOpen;

  @override
  Future<void> start({required void Function(String deeplink) onOpen}) async {
    startCalls++;
    _onOpen = onOpen;
  }

  /// 模拟用户点击通知。
  void tap(String deeplink) => _onOpen?.call(deeplink);

  @override
  Future<String?> registrationId() async => registrationIdValue;

  @override
  Future<bool> isNotificationEnabled() async => notificationEnabled;

  @override
  Future<void> openNotificationSettings() async {
    openSettingsCalls++;
  }

  @override
  Future<void> stop() async {
    stopCalls++;
  }
}
