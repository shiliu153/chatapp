import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import 'models.dart';

/// 个人使用报告:纯只读聚合,只有一条请求,没有写操作。
///
/// 单独成一个仓库而不是塞进 `SettingsRepository`:它不是「设置」,后续若加导出/分享
/// 也只会在这一处长大。
class StatsRepository {
  StatsRepository(this._api);

  final ApiClient _api;

  /// 拉取某个自然周期的七项数字。
  ///
  /// [period] 只会有 `week` / `month` / `year` 三种取值(枚举里就这三个),
  /// 因此客户端不需要处理 `40005`;真收到也只可能是我方参数被改坏。
  Future<StatsReport> fetchReport(StatsPeriod period) async {
    final data = await _api.get('/stats/me', query: {'period': period.query})
        as Map<String, dynamic>;
    return StatsReport.fromJson(data);
  }
}

final statsRepositoryProvider = Provider<StatsRepository>(
    (ref) => StatsRepository(ref.watch(apiClientProvider)));
