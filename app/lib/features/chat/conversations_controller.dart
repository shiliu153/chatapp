import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../im/im_client.dart';
import '../../im/im_manager.dart';

/// 会话列表:IM 登录后拉取;有新消息/会话变化就悄悄刷新。
class ConversationsController extends AsyncNotifier<List<ImConversation>> {
  @override
  Future<List<ImConversation>> build() async {
    final status = ref.watch(imStatusProvider);
    if (status is! ImLoggedIn) return const [];
    final sub = ref.read(imClientProvider).events.listen((event) {
      if (event is ImNewMessage || event is ImConversationsChanged) {
        unawaited(reload());
      } else if (event is ImSelfRead) {
        // 我在另一台设备上读完了这个会话(多端在线 K-3):本机未读清零。
        // 只动 unreadCount —— `peerReadSeq` 是「**对方**读我」,与这一帧无关。
        clearUnread(event.peerId);
      } else if (event is ImConversationDeleted) {
        // 我在另一台设备上删了这个会话(K-3):列表里立刻移除,不等下次全量刷新。
        removeConversation(event.peerId);
      }
    });
    ref.onDispose(sub.cancel);
    return ref.read(imClientProvider).fetchConversations();
  }

  /// 把某个会话的未读清零(跨端已读同步用)。
  ///
  /// Args:
  ///   peerId: 会话对端的 IM id。
  void clearUnread(String peerId) {
    final current = state.value;
    if (current == null) return;
    final index = current.indexWhere((item) => item.peerId == peerId && item.unreadCount != 0);
    if (index < 0) return;
    final next = [...current];
    next[index] = next[index].copyWith(unreadCount: 0);
    state = AsyncValue.data(next);
  }

  /// 从列表移除某个会话(跨端删除同步用)。
  ///
  /// Args:
  ///   peerId: 会话对端的 IM id。
  void removeConversation(String peerId) {
    final current = state.value;
    if (current == null) return;
    final next = current.where((item) => item.peerId != peerId).toList();
    if (next.length != current.length) state = AsyncValue.data(next);
  }

  /// 静默刷新:不动 loading,列表和角标不闪。
  Future<void> reload() async {
    if (ref.read(imStatusProvider) is! ImLoggedIn) return;
    state = await AsyncValue.guard(() => ref.read(imClientProvider).fetchConversations());
  }
}

final conversationsProvider =
    AsyncNotifierProvider<ConversationsController, List<ImConversation>>(
  ConversationsController.new,
  retry: (retryCount, error) => null,
);

/// 会话 Tab 未读角标用的总数。
final unreadTotalProvider = Provider<int>((ref) {
  final conversations = ref.watch(conversationsProvider).value ?? const <ImConversation>[];
  return conversations.fold(0, (sum, item) => sum + item.unreadCount);
});
