import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'models.dart';
import 'settings_repository.dart';

/// 登录设备列表(一类端一行)。
///
/// 关掉自动重试(与 `blockedUsersProvider` 同口径):页面自带「重试」,
/// 否则错误态会被自动重试闪一下再出现,用户看到的是抖动。
class DevicesController extends AsyncNotifier<List<Device>> {
  @override
  Future<List<Device>> build() =>
      ref.watch(settingsRepositoryProvider).fetchDevices();

  /// 下线成功后就地刷新:本页数据只被这一页使用,不需要让别的 provider 失效。
  Future<void> reload() async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(
        () => ref.read(settingsRepositoryProvider).fetchDevices());
  }
}

final devicesProvider =
    AsyncNotifierProvider<DevicesController, List<Device>>(
  DevicesController.new,
  retry: (retryCount, error) => null,
);
