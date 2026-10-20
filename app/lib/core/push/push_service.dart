/// 推送服务抽象:真实实现包极光 SDK,测试用 FakePushService。
///
/// 原生插件在 `flutter test` 里跑不起来,所以所有测试都走替身;
/// 实现必须吞掉异常 —— 推送是增强能力,不能影响 App 启动。
abstract class PushService {
  /// 初始化并开始接收推送。
  ///
  /// [onOpen] 在用户点击通知时回调,参数是通知携带的 deeplink 路径。
  Future<void> start({required void Function(String deeplink) onOpen});

  /// 当前设备的极光 registration_id;初始化失败返回 null。
  Future<String?> registrationId();

  /// 系统通知权限是否已开启。
  Future<bool> isNotificationEnabled();

  /// 跳转系统通知设置页。
  Future<void> openNotificationSettings();

  /// 停止接收推送(登出时调用)。
  Future<void> stop();
}
