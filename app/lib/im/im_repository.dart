import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api_client.dart';
import '../core/providers.dart';
import 'im_bootstrap.dart';

/// POST /im/user_sig 的响应:登录 IM 需要的一组信息。
class UserSig {
  const UserSig({
    required this.backend,
    required this.userSig,
    required this.sdkAppId,
    required this.token,
    required this.wsUrl,
    required this.httpUrl,
    required this.imUserId,
  });

  factory UserSig.fromJson(Map<String, dynamic> json) => UserSig(
        backend: (json['backend'] ?? 'tencent') as String,
        userSig: (json['user_sig'] ?? '') as String,
        // 后端配置里 sdkappid 是字符串,统一转成 int 给 SDK 用
        sdkAppId: int.tryParse('${json['sdkappid'] ?? 0}') ?? 0,
        token: (json['token'] ?? '') as String,
        wsUrl: (json['ws_url'] ?? '') as String,
        httpUrl: (json['http_url'] ?? '') as String,
        imUserId: json['im_user_id'] as String,
      );

  final String backend;
  final String userSig;
  final int sdkAppId;
  final String token;
  final String wsUrl;
  final String httpUrl;
  final String imUserId;

  ImBootstrap get bootstrap => ImBootstrap(
        backend: backend == 'self' ? ImBackend.self : ImBackend.tencent,
        sdkAppId: sdkAppId,
        token: token,
        wsUrl: wsUrl,
        httpUrl: httpUrl,
        imUserId: imUserId,
      );
}

/// GET /matches 的一条:用来把 IM 的 userId 翻译成昵称/头像。
class MatchEntry {
  const MatchEntry({
    required this.userId,
    required this.imUserId,
    required this.nickname,
    this.avatarUrl,
    this.matchedAt,
  });

  factory MatchEntry.fromJson(Map<String, dynamic> json) => MatchEntry(
        userId: json['user_id'] as int,
        imUserId: json['im_user_id'] as String,
        nickname: (json['nickname'] ?? '') as String,
        avatarUrl: json['avatar_url'] as String?,
        matchedAt:
            json['matched_at'] == null ? null : DateTime.tryParse(json['matched_at'] as String),
      );

  final int userId;
  final String imUserId;
  final String nickname;
  final String? avatarUrl;
  final DateTime? matchedAt;
}

class ImRepository {
  ImRepository(this._api);

  final ApiClient _api;

  Future<UserSig> fetchUserSig() async {
    final data = await _api.post('/im/user_sig') as Map<String, dynamic>;
    return UserSig.fromJson(data);
  }

  Future<List<MatchEntry>> fetchMatches() async {
    final data = await _api.getAllPages('/matches');
    return data.map((item) => MatchEntry.fromJson(item as Map<String, dynamic>)).toList();
  }

  /// 解除配对:后端软删除 + 双向拉黑 IM;幂等(没配对也 204)。
  Future<void> unmatch(int userId) async {
    await _api.delete('/matches/$userId');
  }
}

final imRepositoryProvider =
    Provider<ImRepository>((ref) => ImRepository(ref.watch(apiClientProvider)));
