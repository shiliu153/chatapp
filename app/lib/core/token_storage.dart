import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 令牌落盘抽象。
///
/// 生产走系统安全存储(Android Keystore / iOS Keychain),测试注入内存实现,
/// 这样单元测试不需要平台通道,也不会把真实凭证写进测试机。
abstract class TokenStorage {
  /// 读取一个键;不存在返回 `null`。
  Future<String?> read(String key);

  /// 写入一个键。
  Future<void> write(String key, String value);

  /// 删除一个键(不存在时忽略)。
  Future<void> delete(String key);
}

/// 生产实现:Android 用 EncryptedSharedPreferences(Keystore 托管密钥),
/// iOS 用 Keychain(首次解锁后可读,支持后台任务)。
class SecureTokenStorage implements TokenStorage {
  SecureTokenStorage([FlutterSecureStorage? storage])
      : _storage = storage ??
            const FlutterSecureStorage(
              aOptions: AndroidOptions(encryptedSharedPreferences: true),
              iOptions: IOSOptions(accessibility: KeychainAccessibility.first_unlock),
            );

  final FlutterSecureStorage _storage;

  @override
  Future<String?> read(String key) => _storage.read(key: key);

  @override
  Future<void> write(String key, String value) => _storage.write(key: key, value: value);

  @override
  Future<void> delete(String key) => _storage.delete(key: key);
}

/// 旧版本用过的 SharedPreferences 实现。
///
/// 现在只承担两个角色:老用户一次性迁移的来源,以及安全存储不可用时的降级落盘。
class SharedPreferencesTokenStorage implements TokenStorage {
  @override
  Future<String?> read(String key) async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.get(key)?.toString();
  }

  @override
  Future<void> write(String key, String value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(key, value);
  }

  @override
  Future<void> delete(String key) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(key);
  }
}

/// 内存实现:单元测试用,进程结束即丢。
class InMemoryTokenStorage implements TokenStorage {
  InMemoryTokenStorage([Map<String, String>? initial])
      : _values = {...?initial};

  final Map<String, String> _values;

  /// 当前全部键值(测试断言用)。
  @visibleForTesting
  Map<String, String> get values => Map.unmodifiable(_values);

  @override
  Future<String?> read(String key) async => _values[key];

  @override
  Future<void> write(String key, String value) async => _values[key] = value;

  @override
  Future<void> delete(String key) async => _values.remove(key);
}
