import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/app_config.dart';

void main() {
  test('版本比较按三段数字', () {
    expect(isOutdated(current: '1.0.0', min: '1.1.0'), isTrue);
    expect(isOutdated(current: '1.1.0', min: '1.1.0'), isFalse);
    expect(isOutdated(current: '1.10.0', min: '1.2.0'), isFalse);
    expect(isOutdated(current: '2.0', min: '1.9.9'), isFalse);
  });
}
