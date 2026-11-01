import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/legal/legal_texts.dart';

void main() {
  test('隐私政策包含访问记录条款', () {
    expect(privacyPolicyText, contains('访问记录'));
    expect(privacyPolicyText, contains('隐身浏览'));
  });

  test('协议版本已升到 3', () {
    expect(legalVersion, 3);
  });
}
