import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

/// E-5.6c page spec §6 第 3 条:**Semantics 断言**。
///
/// | 元素 | 读什么 |
/// |---|---|
/// | 字段 | 「标签,值」 |
/// | 字段(错误态) | 「标签,错误说明」 |
/// | 照片格 | 「第 N 张照片」(未过审再补状态) |
/// | 照片删除钮 | 「删除第 N 张照片」 |
///
/// 为什么必须钉这几条:§8.4「颜色不是唯一线索」—— 输入框的红色描边、照片的
/// 「待审核」角标对读屏用户等于不存在,只有语义标签能把它们说出来;而「一句话
/// 念完标签 + 值」决定了表单能不能被听明白(念成「昵称」「小雨」两条也算及格,
/// 但错误态必须是「标签 + 说明」连读,否则用户不知道哪个字段错了)。
const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

/// 进「我的 → 编辑资料」。
Future<void> openEditPage(WidgetTester tester, ScriptedAdapter adapter) async {
  await pumpApp(tester, adapter, prefs: _loggedIn);
  await tester.pumpAndSettle();
  await tester.tap(navTab('我'));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const Key('my.card.identity')));
  await tester.pumpAndSettle();
}

/// 把编辑页的列表滚到 [target] 可见。
///
/// 800×600 的测试视口放不下三张分组卡:「关于我」(标签)与「照片」在折叠线以下,
/// `ListView` 不会构建它们,语义树里也就没有对应节点 —— 断言前必须先滚进去。
Future<void> scrollEditTo(WidgetTester tester, Finder target) async {
  await tester.scrollUntilVisible(
    target,
    200,
    scrollable:
        find.descendant(of: find.byType(ListView), matching: find.byType(Scrollable)).first,
  );
  await tester.pumpAndSettle();
}

ScriptedAdapter adapterWith({List<Map<String, dynamic>> photos = const []}) =>
    ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson(
            nickname: '小雨',
            city: '杭州',
            bio: '周末爬山',
            photos: photos,
          )),
      'GET /users/tags': (options) => ok([tagJson(1, '运动')]),
      'PATCH /users/me': (options) => ok(profileJson(nickname: '新昵称')),
    });

void main() {
  testWidgets('字段读「标签,值」', (tester) async {
    final semantics = tester.ensureSemantics();
    await openEditPage(tester, adapterWith());

    // 昵称框:标签「昵称」+ 值「小雨」(EmberField 的 label / value 两个槽位)。
    final nickname = tester
        .getSemantics(find.byKey(const Key('edit.nickname')))
        .getSemanticsData();
    expect(nickname.label, '昵称');
    expect(nickname.value, '小雨');

    // 城市框同理(第二个字段不会串到第一个的语义上)。
    final city =
        tester.getSemantics(find.byKey(const Key('edit.city'))).getSemanticsData();
    expect(city.label, '城市');
    expect(city.value, '杭州');
    semantics.dispose();
  });

  testWidgets('错误态读「标签,错误说明」', (tester) async {
    final semantics = tester.ensureSemantics();
    await openEditPage(tester, adapterWith());

    await tester.enterText(find.byKey(const Key('edit.nickname')), '');
    await tester.tap(find.byKey(const Key('edit.save')));
    await tester.pumpAndSettle();

    // 一条播报同时给出「哪个字段」和「错在哪」。
    expect(find.bySemanticsLabel('昵称，请填写昵称'), findsOneWidget);
    semantics.dispose();
  });

  testWidgets('照片格读「第 N 张照片」,删除钮读「删除第 N 张照片」', (tester) async {
    final semantics = tester.ensureSemantics();
    await openEditPage(
      tester,
      adapterWith(photos: [photoJson(1), photoJson(2, approved: false)]),
    );

    await scrollEditTo(tester, find.byKey(const Key('photo.add')));

    // 照片格:第 N 张;未过审的那张把状态也念出来(颜色不是唯一线索)。
    expect(find.bySemanticsLabel('第 1 张照片'), findsOneWidget);
    expect(find.bySemanticsLabel('第 2 张照片，待审核'), findsOneWidget);
    // 删除钮按序号播报,而不是「一个没有名字的按钮」。
    expect(find.bySemanticsLabel('删除第 1 张照片'), findsOneWidget);
    expect(find.bySemanticsLabel('删除第 2 张照片'), findsOneWidget);
    semantics.dispose();
  });

  testWidgets('标签 chip 读「名称,已选中」(选中态不只靠颜色)', (tester) async {
    final semantics = tester.ensureSemantics();
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson(tags: [tagJson(1, '运动')])),
      'GET /users/tags': (options) => ok([tagJson(1, '运动'), tagJson(2, '音乐')]),
    });
    await openEditPage(tester, adapter);
    await scrollEditTo(tester, find.text('运动'));

    // `EmberChip` 的可点变体把胶囊里的文字也并进同一个语义节点,所以标签形如
    // 「运动，已选中\n运动」—— 用正则匹配前缀(E-5.2 的组件口径,本单不改)。
    expect(find.bySemanticsLabel(RegExp('运动，已选中')), findsOneWidget);
    expect(find.bySemanticsLabel(RegExp('音乐，已选中')), findsNothing);

    // 点一下「音乐」→ 播报翻成已选中(回调把整份新集合交回页面)。
    await tester.tap(find.text('音乐'));
    await tester.pumpAndSettle();
    expect(find.bySemanticsLabel(RegExp('音乐，已选中')), findsOneWidget);
    semantics.dispose();
  });
}
