import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/im/im_client.dart';

void main() {
  test('userIdFromImId:u{id} 约定解析,非账号 id 返回 null', () {
    expect(userIdFromImId('u7'), 7);
    expect(userIdFromImId('u123'), 123);
    expect(userIdFromImId(systemNoticePeerId), isNull);   // 系统通知不是真人
    expect(userIdFromImId('u'), isNull);
    expect(userIdFromImId('uabc'), isNull);
    expect(userIdFromImId('7'), isNull);
  });
}
