import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 外观模式的本地持久化(F-4)。
///
/// 为什么不用后端:外观是纯客户端偏好,与账号无关;登录页(未登录)也要能跟随系统,
/// 放后端反而要等首屏请求才能定主题,会先闪一下白。
///
/// 存的是 [ThemeMode] 的枚举名(`system` / `light` / `dark`),不是 `index` ——
/// 后者会在枚举顺序调整时静默读错。
class ThemeModeStore {
  const ThemeModeStore();

  /// 与 Web 侧 `localStorage` 的 key 同名,两端口径一致便于排查。
  static const key = 'theme_mode';

  /// 读已保存的模式;没存过 / 存了非法值一律回落 [ThemeMode.system]。
  Future<ThemeMode> read() async {
    final prefs = await SharedPreferences.getInstance();
    return decode(prefs.getString(key));
  }

  /// 写模式。写失败只影响「下次启动的记忆」,不抛给调用方。
  Future<void> write(ThemeMode mode) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(key, encode(mode));
  }

  /// 字符串 → 模式(非法值回落 system)。
  static ThemeMode decode(String? raw) {
    for (final mode in ThemeMode.values) {
      if (mode.name == raw) return mode;
    }
    return ThemeMode.system;
  }

  /// 模式 → 字符串。
  static String encode(ThemeMode mode) => mode.name;
}
