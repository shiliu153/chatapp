import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api_client.dart';

/// 测试里默认关闭启动版本检查(避免每个用例都多一次 /app/config 请求)。
final appConfigCheckEnabledProvider = Provider<bool>((ref) => true);

/// GET /app/config 的响应。
class AppConfig {
  const AppConfig({
    required this.minAppVersion,
    required this.latestVersion,
    required this.downloadUrl,
  });

  factory AppConfig.fromJson(Map<String, dynamic> json) => AppConfig(
        minAppVersion: (json['min_app_version'] ?? '0.0.0') as String,
        latestVersion: (json['latest_version'] ?? '0.0.0') as String,
        downloadUrl: (json['download_url'] ?? '') as String,
      );

  final String minAppVersion;
  final String latestVersion;
  final String downloadUrl;
}

/// 拉取版本配置;网络失败返回 null(启动不被阻断)。
Future<AppConfig?> fetchAppConfig(ApiClient api) async {
  try {
    final data = await api.get('/app/config') as Map<String, dynamic>;
    return AppConfig.fromJson(data);
  } catch (_) {
    return null;
  }
}

/// 三段数字逐段比较;格式不合法按 0 处理。
bool isOutdated({required String current, required String min}) {
  List<int> parts(String value) =>
      value.split('.').map((item) => int.tryParse(item) ?? 0).toList();
  final a = parts(current);
  final b = parts(min);
  for (var i = 0; i < 3; i++) {
    final x = i < a.length ? a[i] : 0;
    final y = i < b.length ? b[i] : 0;
    if (x != y) return x < y;
  }
  return false;
}
