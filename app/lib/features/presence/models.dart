import '../../core/format.dart';

/// 一个人的在线状态:online = 最近 2 分钟内 App 有活动。
class Presence {
  const Presence({required this.online, this.lastActiveAt});

  factory Presence.fromJson(Map<String, dynamic> json) => Presence(
        online: json['online'] as bool? ?? false,
        lastActiveAt: json['last_active_at'] == null
            ? null
            : DateTime.tryParse(json['last_active_at'] as String),
      );

  final bool online;
  final DateTime? lastActiveAt;
}

/// 展示文案:在线「● 在线」;离线有最后活跃「x 分钟前在线」;未知 → null(不显示)。
String? presenceLabel(Presence? presence, {DateTime? now}) {
  if (presence == null) return null;
  if (presence.online) return '● 在线';
  final at = presence.lastActiveAt;
  if (at == null) return null;
  return '${formatLastActive(at, now: now)}在线';
}
