/// IM 引导包:服务端决定本次登录走腾讯还是自建。
enum ImBackend { tencent, self }

class ImBootstrap {
  const ImBootstrap({
    required this.backend,
    this.sdkAppId = 0,
    this.token = '',
    this.wsUrl = '',
    this.httpUrl = '',
    required this.imUserId,
  });

  factory ImBootstrap.fromJson(Map<String, dynamic> json) {
    final backend = json['backend'] as String? ?? 'tencent';
    return ImBootstrap(
      backend: backend == 'self' ? ImBackend.self : ImBackend.tencent,
      sdkAppId: int.tryParse('${json['sdkappid'] ?? 0}') ?? 0,
      token: (json['token'] ?? '') as String,
      wsUrl: (json['ws_url'] ?? '') as String,
      httpUrl: (json['http_url'] ?? '') as String,
      imUserId: (json['im_user_id'] ?? '') as String,
    );
  }

  final ImBackend backend;
  final int sdkAppId;
  final String token;
  final String wsUrl;
  final String httpUrl;
  final String imUserId;
}
