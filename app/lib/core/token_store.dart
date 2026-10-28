import 'package:flutter/foundation.dart';

import 'token_storage.dart';

/// 本地凭证存取。凭证被清掉 = 会话结束:
/// clear() 会通知监听者,SessionController 靠这个信号把界面踢回登录页。
///
/// 设计要点:
/// 1. 默认落在系统安全存储(Android Keystore / iOS Keychain),不再明文写 SharedPreferences;
/// 2. 老用户首次启动时把 SharedPreferences 里的旧令牌**搬过去再删掉**,避免升级即被登出;
/// 3. 安全存储不可用(Keystore 损坏、平台通道缺失)时降级回 SharedPreferences 读写,
///    宁可保留旧行为也不要让用户登不进来。
class TokenStore extends ChangeNotifier {
  TokenStore({TokenStorage? storage, TokenStorage? legacy})
      : _storage = storage ?? SecureTokenStorage(),
        _legacy = legacy ?? SharedPreferencesTokenStorage();

  static const _accessKey = 'auth.access';
  static const _refreshKey = 'auth.refresh';
  static const _userIdKey = 'auth.user_id';

  final TokenStorage _storage;

  /// 迁移来源 / 降级目标。
  final TokenStorage _legacy;

  /// 迁移只跑一次;用 Future 缓存,避免启动时并发读触发多轮迁移。
  Future<void>? _migration;

  String? _forceLogoutReason;

  Future<void> _ensureMigrated() => _migration ??= _migrate();

  /// 把 SharedPreferences 里的旧令牌搬进安全存储,搬一个删一个(幂等)。
  Future<void> _migrate() async {
    for (final key in const [_accessKey, _refreshKey, _userIdKey]) {
      try {
        if (await _storage.read(key) != null) continue;
        final legacyValue = await _legacy.read(key);
        if (legacyValue == null) continue;
        await _storage.write(key, legacyValue);
        await _legacy.delete(key);
      } catch (error) {
        // 安全存储不可用:保留旧值,后面的读写会走降级分支
        debugPrint('令牌迁移失败($key): $error');
        return;
      }
    }
  }

  Future<String?> _read(String key) async {
    await _ensureMigrated();
    try {
      return await _storage.read(key);
    } catch (error) {
      debugPrint('安全存储读取失败($key),降级到 SharedPreferences: $error');
      return _legacy.read(key);
    }
  }

  Future<void> _write(String key, String value) async {
    await _ensureMigrated();
    try {
      await _storage.write(key, value);
    } catch (error) {
      debugPrint('安全存储写入失败($key),降级到 SharedPreferences: $error');
      await _legacy.write(key, value);
    }
  }

  Future<void> _delete(String key) async {
    try {
      await _storage.delete(key);
    } catch (error) {
      debugPrint('安全存储删除失败($key): $error');
    }
    // 旧存储里的同名键也要清掉,否则降级分支会读回已作废的令牌
    await _legacy.delete(key);
  }

  Future<void> save(
      {required String access, required String refresh, required int userId}) async {
    await _write(_accessKey, access);
    await _write(_refreshKey, refresh);
    await _write(_userIdKey, '$userId');
  }

  Future<void> saveTokens({required String access, required String refresh}) async {
    await _write(_accessKey, access);
    await _write(_refreshKey, refresh);
  }

  Future<void> clear() async {
    await _delete(_accessKey);
    await _delete(_refreshKey);
    await _delete(_userIdKey);
    notifyListeners();
  }

  /// 带原因的强制退出(如:账号在另一台设备登录被顶下线)。
  /// 原因是一次性信号:登录页展示后 take 掉。
  Future<void> forceLogout(String reason) async {
    _forceLogoutReason = reason;
    await clear();
  }

  String? takeForceLogoutReason() {
    final reason = _forceLogoutReason;
    _forceLogoutReason = null;
    return reason;
  }

  Future<String?> get accessToken => _read(_accessKey);

  Future<String?> get refreshToken => _read(_refreshKey);

  Future<int?> get userId async {
    final raw = await _read(_userIdKey);
    return raw == null ? null : int.tryParse(raw);
  }
}
