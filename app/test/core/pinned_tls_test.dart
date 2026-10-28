import 'package:dio/io.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/pinned_tls.dart';
import 'package:chatapp_app/core/pinned_tls_core.dart';

void main() {
  test('内置两张根证书能构造只信它们的上下文', () async {
    final context = await PinnedTls.buildContext();
    expect(context, isNotNull);
  });

  test('没有根证书时直接报错(否则等于不校验)', () {
    expect(() => buildPinnedContext(const []), throwsStateError);
  });

  test('测试环境(未启用绑定)走系统默认适配器', () {
    expect(PinnedTls.enforced, isFalse);
    expect(PinnedTls.adapter(), isA<IOHttpClientAdapter>());
    expect(PinnedTls.wsClient(), isNull);
  });
}
