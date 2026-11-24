import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/profile/profile_edit_page.dart';
import 'package:chatapp_app/im/voice_recorder.dart';

import '../../support/fake_voice.dart';
import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

/// E-5.6c page spec §6 第 2 条:编辑资料 **2 张 golden**(明 / 暗)。
///
/// 比的是取值:§9.4 顶栏 52(返回 22 + 标题 17/w600 居中)、三张 `EmberCard`
/// 分组卡、`EmberField` 的 52 高 + `radius.md` + `border.divider`、`EmberChip`
/// 标签胶囊、底部主操作「保存」(52 高 + `radius.pill` + `emberGlow`)。
///
/// 照片格在 widget 测试里拿不到真图(所有 HTTP 都返回 400),golden 里是
/// `surface.sunken` + Phosphor `image-broken` 的失败占位 —— 那也是 §8.3 照片格
/// 「失败」这一格;真实照片与长按/删除手感属于**模拟器手测**。
///
/// 重新生成:`cd app && flutter test --update-goldens test/features/profile/profile_edit_golden_test.dart`
/// (只在**确认视觉改动就是想要的**之后跑,并人工看一眼 diff 图。)
const _loggedIn = {
  'auth.access': 'a',
  'auth.refresh': 'r',
  'auth.user_id': 7,
};

void main() {
  for (final brightness in Brightness.values) {
    final mode = brightness == Brightness.light ? 'light' : 'dark';

    testWidgets('编辑资料 golden · $mode', (tester) async {
      // 固定视口 390 宽 + dpr 1,截图不随机器变。
      //
      // 高度取 1180(比 844 的手机屏高):编辑资料是一张长表单,844 只能看到
      // 「基本信息」与半张「关于我」—— 而本单换皮的重头(标签胶囊、照片格、
      // 底部主操作)全在折叠线以下。加高视口让一张 golden 覆盖整页取值。
      tester.view.physicalSize = const Size(390, 1180);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);

      final adapter = ScriptedAdapter({
        'POST /auth/token/refresh': (options) =>
            ok({'access': 'a2', 'refresh': 'r2'}),
        'GET /users/me': (options) => ok(profileJson(
              nickname: '小雨',
              gender: 'female',
              birthday: '1998-03-12',
              city: '杭州',
              bio: '周末爬山,平时看展',
              tags: [tagJson(1, '运动'), tagJson(2, '音乐'), tagJson(3, '旅行')],
              // 两张照片:一张过审、一张待审 —— 顺带把「待审核」角标也钉进 golden。
              photos: [photoJson(1), photoJson(2, approved: false)],
            )),
        'GET /users/tags': (options) => ok([
              tagJson(1, '运动'),
              tagJson(2, '音乐'),
              tagJson(3, '旅行'),
              tagJson(4, '读书'),
            ]),
      });
      await pumpApp(tester, adapter, prefs: {
        ..._loggedIn,
        // 与 main.dart 同一条路径:主题模式从 prefs 读,深色用例不用另造主题
        'theme_mode': brightness == Brightness.dark ? 'dark' : 'light',
      }, overrides: [
        // 1180 高的视口会把语音卡也建出来,而真实录音器要平台通道
        // (`record` 插件在 widget 测试里没有实现)→ 换成假录音器。
        voiceRecorderProvider.overrideWithValue(FakeVoiceRecorder()),
      ]);
      await tester.pumpAndSettle();
      await tester.tap(navTab('我'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('my.card.identity')));
      await tester.pumpAndSettle();

      await expectLater(
        find.byType(ProfileEditPage),
        matchesGoldenFile('goldens/profile_edit_$mode.png'),
      );
    });
  }
}
