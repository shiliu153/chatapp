import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/discovery/icebreaker.dart';

/// 配对那一刻的破冰文案(计划 §2.2):只在配对瞬间展示共同点,聊天页不提示。
void main() {
  test('有共同标签 → 列出最多 2 个标签并邀请开口', () {
    expect(
      matchIcebreaker(sharedTagNames: ['运动', '电影', '音乐'], myCity: '上海', peerCity: '上海'),
      '你们都喜欢 运动、电影,不如从这儿聊起?',
    );
  });

  test('有共同标签时优先说标签,不再提城市', () {
    final text = matchIcebreaker(
        sharedTagNames: ['运动'], myCity: '上海', peerCity: '上海');
    expect(text, '你们都喜欢 运动,不如从这儿聊起?');
    expect(text, isNot(contains('都在')));
  });

  test('无共同标签且同城 → 只提城市', () {
    expect(
      matchIcebreaker(sharedTagNames: const [], myCity: '杭州', peerCity: '杭州'),
      '你们都在 杭州',
    );
  });

  test('无共同标签且城市为空 → 整行不展示', () {
    expect(matchIcebreaker(sharedTagNames: const [], myCity: '', peerCity: ''), isNull);
    expect(matchIcebreaker(sharedTagNames: const [], myCity: '杭州', peerCity: ''), isNull);
  });

  test('无共同标签且不同城 → 不替用户断言', () {
    expect(matchIcebreaker(sharedTagNames: const [], myCity: '杭州', peerCity: '成都'), isNull);
  });

  test('标签名带空白或空串时忽略', () {
    expect(
      matchIcebreaker(sharedTagNames: ['  ', '运动 '], myCity: '', peerCity: ''),
      '你们都喜欢 运动,不如从这儿聊起?',
    );
  });
}
