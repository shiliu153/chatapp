import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import 'models.dart';

/// 站内通知的数据访问:列表(游标分页)、未读数、标记已读。
class NotificationsRepository {
  NotificationsRepository(this._api);

  final ApiClient _api;

  /// 拉一页通知;返回本页条目、后端总数与下一页游标。
  Future<({List<AppNotification> items, int count, String? nextCursor})> fetch(
      {int limit = 20, String? cursor}) async {
    final data = await _api.get('/notifications', query: {
      'limit': limit,
      'before': ?cursor,
    }) as Map<String, dynamic>;
    final items = (data['results'] as List<dynamic>)
        .map((item) => AppNotification.fromJson(item as Map<String, dynamic>))
        .toList();
    return (
      items: items,
      count: data['count'] as int,
      nextCursor: data['next_cursor'] as String?,
    );
  }

  /// 未读数(入口角标);与列表同口径(自己的、90 天内)。
  Future<int> fetchUnreadCount() async {
    final data = await _api.get('/notifications/unread_count') as Map<String, dynamic>;
    return data['unread'] as int;
  }

  /// 标记已读:给 `ids` 只标这几条,`all: true` 标全部未读。
  Future<void> markRead({List<int>? ids, bool all = false}) async {
    await _api.post('/notifications/read', data: {
      'ids': ?ids,
      if (all) 'all': true,
    });
  }
}

final notificationsRepositoryProvider = Provider<NotificationsRepository>(
    (ref) => NotificationsRepository(ref.watch(apiClientProvider)));
