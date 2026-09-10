import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../im/im_repository.dart';
import '../auth/session.dart';

/// `imUserId(u9) → 昵称/头像` 本地缓存:会话列表和聊天页标题都靠它显示人。
/// watch session:退出/换号时自动重建,别把上一个号的缓存留给下一个。
class MatchCacheController extends AsyncNotifier<Map<String, MatchEntry>> {
  @override
  Future<Map<String, MatchEntry>> build() async {
    final session = ref.watch(sessionProvider);
    if (session is! SessionLoggedIn) return const {};
    return _fetch();
  }

  /// 新配对成功后刷一次(配对动效那边调)。
  Future<void> refresh() async {
    state = await AsyncValue.guard(_fetch);
  }

  Future<Map<String, MatchEntry>> _fetch() async {
    final matches = await ref.read(imRepositoryProvider).fetchMatches();
    return {for (final entry in matches) entry.imUserId: entry};
  }
}

final matchCacheProvider = AsyncNotifierProvider<MatchCacheController, Map<String, MatchEntry>>(
  MatchCacheController.new,
  retry: (retryCount, error) => null,
);

/// 显示名:本地缓存 > IM 会话名 > IM id。
String displayNameFor(Map<String, MatchEntry> cache, String peerId, {String? imName}) {
  final cached = cache[peerId]?.nickname;
  if (cached != null && cached.isNotEmpty) return cached;
  if (imName != null && imName.isNotEmpty) return imName;
  return peerId;
}

/// 头像:本地缓存 > IM 会话头像。
String? avatarUrlFor(Map<String, MatchEntry> cache, String peerId, {String? imFaceUrl}) {
  final cached = cache[peerId]?.avatarUrl;
  if (cached != null && cached.isNotEmpty) return cached;
  if (imFaceUrl != null && imFaceUrl.isNotEmpty) return imFaceUrl;
  return null;
}
