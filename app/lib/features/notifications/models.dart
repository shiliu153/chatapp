// 站内通知数据;字段与后端 GET /notifications 的单项一一对应(只取 UI 用得到的)。

/// 通知里的触发者摘要。`id` 是**账号 id**(即 IM 的 `u{id}`),可直接拼成 `/chat/u{id}`。
class NotificationActor {
  const NotificationActor({
    required this.id,
    required this.nickname,
    this.avatarUrl,
  });

  factory NotificationActor.fromJson(Map<String, dynamic> json) => NotificationActor(
        id: json['id'] as int,
        nickname: (json['nickname'] ?? '') as String,
        avatarUrl: json['avatar'] as String?,
      );

  final int id;
  final String nickname;
  final String? avatarUrl;
}

/// 通知点击后要跳向的目标。`kind=none` 时 `id` 为 `null`(只标已读,不跳转)。
class NotificationTarget {
  const NotificationTarget({required this.kind, this.id});

  factory NotificationTarget.fromJson(Map<String, dynamic> json) => NotificationTarget(
        kind: (json['kind'] ?? 'none') as String,
        id: json['id'] as int?,
      );

  static const none = NotificationTarget(kind: 'none');

  final String kind;
  final int? id;

  bool get isPost => kind == 'post' && id != null;

  bool get isUser => kind == 'user' && id != null;
}

/// 一条站内通知。
class AppNotification {
  const AppNotification({
    required this.id,
    required this.kind,
    required this.text,
    required this.isRead,
    required this.createdAt,
    this.actor,
    this.target = NotificationTarget.none,
  });

  factory AppNotification.fromJson(Map<String, dynamic> json) {
    final actor = json['actor'];
    return AppNotification(
      id: json['id'] as int,
      kind: (json['kind'] ?? '') as String,
      text: (json['text'] ?? '') as String,
      isRead: json['is_read'] == true,
      createdAt: DateTime.parse(json['created_at'] as String),
      actor: actor is Map<String, dynamic> ? NotificationActor.fromJson(actor) : null,
      target: json['target'] is Map<String, dynamic>
          ? NotificationTarget.fromJson(json['target'] as Map<String, dynamic>)
          : NotificationTarget.none,
    );
  }

  final int id;
  final String kind;

  /// 服务端生成的正文,直接展示(不要自己拼文案)。
  final String text;
  final bool isRead;
  final DateTime createdAt;
  final NotificationActor? actor;
  final NotificationTarget target;

  AppNotification copyWith({bool? isRead}) => AppNotification(
        id: id,
        kind: kind,
        text: text,
        isRead: isRead ?? this.isRead,
        createdAt: createdAt,
        actor: actor,
        target: target,
      );
}
