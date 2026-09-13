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

  test('formatPostTime 按间隔返回相对时间', () {
    final now = DateTime(2026, 9, 12, 20, 0);
    expect(formatPostTime(now.subtract(const Duration(seconds: 30)), now: now), '刚刚');
    expect(formatPostTime(now.subtract(const Duration(minutes: 5)), now: now), '5 分钟前');
    expect(formatPostTime(now.subtract(const Duration(hours: 3)), now: now), '3 小时前');
    expect(formatPostTime(now.subtract(const Duration(days: 2)), now: now), '2 天前');
    expect(formatPostTime(DateTime(2026, 8, 1), now: now), '8 月 1 日');
    expect(formatPostTime(DateTime(2025, 12, 1), now: now), '2025 年 12 月 1 日');
  });

  test('formatLastActive 按间隔返回相对时间', () {
    final now = DateTime(2026, 9, 13, 14, 0);
    expect(formatLastActive(now.subtract(const Duration(seconds: 30)), now: now), '刚刚');
    expect(formatLastActive(now.subtract(const Duration(minutes: 5)), now: now), '5 分钟前');
    expect(formatLastActive(now.subtract(const Duration(hours: 3)), now: now), '3 小时前');
    expect(formatLastActive(now.subtract(const Duration(days: 2)), now: now), '2 天前');
  });
}
