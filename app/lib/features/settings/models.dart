// 设置页用到的数据模型;字段与后端 `GET /api/v1/devices` 的 `results[]` 一一对应。
import '../../core/format.dart';

/// 一台「登录过的设备」= 一类端(`app` / `web`)的会话行。
///
/// 后端没有任何「在线」字段:在线是账号级 presence,按端拆要不划算地改心跳链路,
/// 所以这里只有 [lastActiveAt](登录或刷新令牌时更新),让用户自己判断哪台还在用。
class Device {
  const Device({
    required this.clientType,
    required this.clientLabel,
    required this.current,
    required this.createdAt,
    required this.lastActiveAt,
  });

  factory Device.fromJson(Map<String, dynamic> json) => Device(
        clientType: json['client_type'] as String,
        clientLabel: (json['client_label'] ?? '') as String,
        current: (json['current'] ?? false) as bool,
        createdAt: parseDate(json['created_at'] as String?),
        lastActiveAt: parseDate(json['last_active_at'] as String?),
      );

  /// 端类型:`app` 或 `web`(下线接口的路径参数)。
  final String clientType;

  /// 端类型的展示名,由后端给(`App` / `网页端`),App 不自造映射。
  final String clientLabel;

  /// 本次请求所在的端;由后端按请求头 `X-Client` 判定,只有一行是 `true`。
  final bool current;

  /// 该端**首次**登录时间;契约必填,解析失败时按空处理,不影响其余字段展示。
  final DateTime? createdAt;

  /// 该端最近一次登录或刷新令牌的时间;批次 M 之前的会话行是 `null`。
  final DateTime? lastActiveAt;
}
