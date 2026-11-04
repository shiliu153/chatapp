/// IM 引导包:登录时服务端下发的自建 IM 连接参数。
///
/// 腾讯云 IM 分支已于 2026-11-08 删除(backlog D-4),所以这里只剩自建一套。
class ImBootstrap {
  const ImBootstrap({
    required this.token,
    required this.wsUrl,
    required this.httpUrl,
    required this.imUserId,
  });

  factory ImBootstrap.fromJson(Map<String, dynamic> json) => ImBootstrap(
        token: (json['token'] ?? '') as String,
        wsUrl: (json['ws_url'] ?? '') as String,
        httpUrl: (json['http_url'] ?? '') as String,
        imUserId: (json['im_user_id'] ?? '') as String,
      );

  /// 自建 IM 的登录令牌(带会话版本 `sv`,imserver 握手时校验)。
  final String token;
  final String wsUrl;
  final String httpUrl;
  final String imUserId;
}
