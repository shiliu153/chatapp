import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/image_pick.dart';

void main() {
  test('聊天选图使用 1920 长边与 80 质量的压缩参数', () {
    // 参数集中放在 image_pick.dart;这里防止后续被误改成资料照的 1080/85
    expect(chatImageMaxSide, 1920);
    expect(chatImageQuality, 80);
    expect(pickChatImageFromGallery, isNotNull);
  });
}
