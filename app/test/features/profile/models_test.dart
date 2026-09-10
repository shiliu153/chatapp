import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/format.dart';
import 'package:chatapp_app/features/profile/models.dart';

import '../../support/sample_data.dart';

void main() {
  test('Profile.fromJson 解析完整资料', () {
    final profile = Profile.fromJson(profileJson(
      tags: [tagJson(1, '运动')],
      photos: [photoJson(9, approved: true)],
    ));
    expect(profile.nickname, '小明');
    expect(profile.isComplete, isTrue);
    expect(profile.tags.single.name, '运动');
    expect(profile.avatar?.id, 9);
  });

  test('没有过审照片时 avatar 为空', () {
    final profile = Profile.fromJson(profileJson(photos: [photoJson(9, approved: false)]));
    expect(profile.avatar, isNull);
  });

  test('isAtLeast18 计算生日边界', () {
    final today = DateTime(2026, 9, 10);
    expect(isAtLeast18(DateTime(2008, 9, 10), today: today), isTrue); // 今天刚好 18
    expect(isAtLeast18(DateTime(2008, 9, 11), today: today), isFalse); // 差一天
  });

  test('日期格式化与解析', () {
    expect(formatDate(DateTime(2000, 1, 5)), '2000-01-05');
    expect(parseDate('2000-01-05'), DateTime(2000, 1, 5));
    expect(parseDate(null), isNull);
  });
}
