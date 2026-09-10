import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 本地凭证存取。凭证被清掉 = 会话结束:
/// clear() 会通知监听者,SessionController 靠这个信号把界面踢回登录页。
class TokenStore extends ChangeNotifier {
  static const _accessKey = 'auth.access';
  static const _refreshKey = 'auth.refresh';
  static const _userIdKey = 'auth.user_id';

  Future<void> save(
      {required String access, required String refresh, required int userId}) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_accessKey, access);
    await prefs.setString(_refreshKey, refresh);
    await prefs.setInt(_userIdKey, userId);
  }

  Future<void> saveTokens({required String access, required String refresh}) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_accessKey, access);
    await prefs.setString(_refreshKey, refresh);
  }

  Future<void> clear() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_accessKey);
    await prefs.remove(_refreshKey);
    await prefs.remove(_userIdKey);
    notifyListeners();
  }

  Future<String?> get accessToken async =>
      (await SharedPreferences.getInstance()).getString(_accessKey);

  Future<String?> get refreshToken async =>
      (await SharedPreferences.getInstance()).getString(_refreshKey);

  Future<int?> get userId async =>
      (await SharedPreferences.getInstance()).getInt(_userIdKey);
}
