import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'theme_mode_store.dart';

/// 本地读写外观模式。
final themeModeStoreProvider = Provider<ThemeModeStore>((ref) => const ThemeModeStore());

/// 启动时读到的模式。
///
/// 由 `main.dart` 在 `runApp` 之前 await 读出来注入(测试里由 harness 注入),
/// 这样 [ChatApp] 第一帧就是正确主题,不会先按 system 画一帧再跳到 dark(闪白)。
final initialThemeModeProvider = Provider<ThemeMode>((ref) => ThemeMode.system);

/// 外观模式的状态(跟随系统 / 浅色 / 深色)。
///
/// 切换是「先改内存状态、再异步落盘」:UI 立即生效,写盘失败只影响下次启动的记忆。
class ThemeModeController extends Notifier<ThemeMode> {
  @override
  ThemeMode build() => ref.watch(initialThemeModeProvider);

  /// 切换并持久化。
  Future<void> setMode(ThemeMode mode) async {
    if (state == mode) return;
    state = mode;
    await ref.read(themeModeStoreProvider).write(mode);
  }
}

/// 当前外观模式(跟随系统 / 浅色 / 深色)。
final themeModeProvider = NotifierProvider<ThemeModeController, ThemeMode>(
  ThemeModeController.new,
);
