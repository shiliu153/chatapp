import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../profile/models.dart';
import 'models.dart';

class DiscoveryRepository {
  DiscoveryRepository(this._api);

  final ApiClient _api;

  /// 候选卡(discovery.md §3.1);响应是**裸数组**。
  ///
  /// [filter] 里只出现用户改过的字段,没改的一个参数都不发 —— 后端对缺省字段沿用
  /// 「想找的人」偏好,所以「只筛城市」不会顺带把年龄区间钉死成面板里的默认值。
  Future<List<Candidate>> fetchCandidates(
      {int limit = 10, DiscoveryFilter filter = DiscoveryFilter.none}) async {
    final data = await _api.get('/discovery/candidates',
        query: {'limit': limit, ...filter.toQuery()}) as List<dynamic>;
    return data.map((item) => Candidate.fromJson(item as Map<String, dynamic>)).toList();
  }

  /// 今日精选(discovery.md §3.11);响应是**包装对象** `{date, candidates}`。
  Future<DailyCandidates> fetchDaily({int limit = 6}) async {
    final data =
        await _api.get('/discovery/daily', query: {'limit': limit}) as Map<String, dynamic>;
    return DailyCandidates.fromJson(data);
  }

  /// 滑一张卡;返回是否配对成功,以及配对成功时后端直接给出的共同标签。
  ///
  /// 共同标签只用来渲染「配对那一刻」的破冰文案,不要为了它再拉一次对方资料 ——
  /// 那会被记成一次访客访问(discovery.md §3.2)。
  Future<({bool matched, List<Tag> sharedTags})> swipe({
    required int targetUserId,
    required bool like,
  }) async {
    final data = await _api.post('/discovery/swipe',
            data: {'target_user_id': targetUserId, 'action': like ? 'like' : 'pass'})
        as Map<String, dynamic>;
    return (
      matched: data['matched'] == true,
      sharedTags: ((data['shared_tags'] ?? const []) as List<dynamic>)
          .map((item) => Tag.fromJson(item as Map<String, dynamic>))
          .toList(),
    );
  }

  /// 撤销最近一次滑卡(discovery.md §3.9);返回被撤销的目标账号 ID。
  ///
  /// 没有可撤销的滑卡时后端回 `400` + `40003`(无记录 / 超 30 秒 / 已配对),
  /// 由调用方按业务码处理,这里只管转发、不改写错误。
  Future<int> undoSwipe() async {
    final data = await _api.post('/discovery/swipe/undo') as Map<String, dynamic>;
    return data['target_user_id'] as int;
  }

  /// 每日喜欢额度快照(discovery.md §3.10)。
  Future<LikeQuota> fetchQuota() async {
    final data = await _api.get('/discovery/quota') as Map<String, dynamic>;
    return LikeQuota.fromJson(data);
  }

  /// 喜欢我的人(游标分页);返回本页条目、后端总数与下一页游标。
  Future<({List<LikeReceived> items, int count, String? nextCursor})> fetchLikesReceived(
      {int limit = 20, String? cursor}) async {
    final data = await _api.get('/discovery/likes', query: {
      'limit': limit,
      'before': ?cursor,
    }) as Map<String, dynamic>;
    final items = (data['results'] as List<dynamic>)
        .map((item) => LikeReceived.fromJson(item as Map<String, dynamic>))
        .toList();
    return (items: items, count: data['count'] as int,
        nextCursor: data['next_cursor'] as String?);
  }

  /// 入口角标:只查数量。
  Future<int> fetchLikesReceivedCount() async {
    final data = await _api.get('/discovery/likes/count') as Map<String, dynamic>;
    return data['count'] as int;
  }

  /// 谁看过我(游标分页);返回本页条目、后端总数与下一页游标。
  Future<({List<Visit> items, int count, String? nextCursor})> fetchVisits(
      {int limit = 20, String? cursor}) async {
    final data = await _api.get('/discovery/visits', query: {
      'limit': limit,
      'before': ?cursor,
    }) as Map<String, dynamic>;
    final items = (data['results'] as List<dynamic>)
        .map((item) => Visit.fromJson(item as Map<String, dynamic>))
        .toList();
    return (items: items, count: data['count'] as int,
        nextCursor: data['next_cursor'] as String?);
  }

  /// 访客入口角标:只查数量。
  Future<int> fetchVisitsCount() async {
    final data = await _api.get('/discovery/visits/count') as Map<String, dynamic>;
    return data['count'] as int;
  }
}

final discoveryRepositoryProvider = Provider<DiscoveryRepository>(
    (ref) => DiscoveryRepository(ref.watch(apiClientProvider)));
