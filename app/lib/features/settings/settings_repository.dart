import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import 'models.dart';

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

  /// 登录设备列表:一类端一行,最多两行(`app` + `web`),不分页。
  ///
  /// `current` 由后端按请求头 `X-Client` 判定 —— 头由全局
  /// `ClientHeaderInterceptor` 统一补,页面里不手写。
  Future<List<Device>> fetchDevices() async {
    final data = await _api.get('/devices') as Map<String, dynamic>;
    return ((data['results'] ?? const []) as List<dynamic>)
        .map((item) => Device.fromJson(item as Map<String, dynamic>))
        .toList();
  }

  /// 下线指定的端(`app` / `web`):该端会话版本 +1,令牌立即失效。
  ///
  /// 服务端幂等(重复调用也是 204);允许下线当前端,语义等同注销本端,
  /// 调用方拿到成功响应后要自己清凭证回登录页。
  Future<void> logoutDevice(String clientType) async {
    await _api.delete('/devices/$clientType');
  }
}

final settingsRepositoryProvider = Provider<SettingsRepository>(
    (ref) => SettingsRepository(ref.watch(apiClientProvider)));
