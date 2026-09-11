import 'package:shared_preferences/shared_preferences.dart';

import 'legal_texts.dart';

const _agreedVersionKey = 'legal.agreed_version';

/// 是否已同意当前版本的协议(文案 bump 版本后会重新弹一次)。
Future<bool> hasAgreedToLegal() async {
  final prefs = await SharedPreferences.getInstance();
  return (prefs.getInt(_agreedVersionKey) ?? 0) >= legalVersion;
}

Future<void> acceptLegal() async {
  final prefs = await SharedPreferences.getInstance();
  await prefs.setInt(_agreedVersionKey, legalVersion);
}
