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
      }
    });
    ref.onDispose(sub.cancel);
    return ref.read(imClientProvider).fetchConversations();
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
