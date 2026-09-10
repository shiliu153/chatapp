import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/format.dart';

void main() {
  test('formatMessageTime:今天只给时分,更早给月日', () {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day, 9, 5);
    expect(formatMessageTime(today), '09:05');

    final old = DateTime(now.year, now.month, now.day).subtract(const Duration(days: 3));
    final expected =
        '${old.month.toString().padLeft(2, '0')}-${old.day.toString().padLeft(2, '0')}';
    expect(formatMessageTime(old), expected);
  });
}
