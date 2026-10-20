import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';

/// 设置页里的账号级操作。注销是**不可恢复**操作,故单独成一个仓库,
/// 不塞进 ProfileRepository(它只管资料读写)。
class SettingsRepository {
  SettingsRepository(this._api);

  final ApiClient _api;

  /// 注销账号:后端要求带上完整手机号做二次确认,不匹配返回 400。
  Future<void> deleteAccount(String phone) async {
    await _api.delete('/users/me', data: {'phone': phone});
  }

  /// 提交意见反馈;``type`` 取 feature / bug / account / other。
  Future<void> submitFeedback({
    required String type,
    required String content,
    String contact = '',
  }) async {
    await _api.post('/feedback', data: {
      'type': type,
      'content': content,
      if (contact.isNotEmpty) 'contact': contact,
    });
  }
}

final settingsRepositoryProvider = Provider<SettingsRepository>(
    (ref) => SettingsRepository(ref.watch(apiClientProvider)));
