import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import 'package:chatapp_app/core/theme/app_theme.dart';
import 'package:chatapp_app/core/ui/ember_ui.dart';
import 'package:chatapp_app/features/discovery/models.dart';
import 'package:chatapp_app/features/discovery/widgets/discovery_illustration.dart';
import 'package:chatapp_app/features/discovery/widgets/profile_card.dart';
import 'package:chatapp_app/features/presence/models.dart';

import '../../support/sample_data.dart';

/// 发现页 golden(E-5.2 page spec §6 第 2 条):**12 张**
///
/// | 组 | 张数 | 覆盖 |
/// |---|---|---|
/// | 卡面 `ProfileCard` | 4 | 明 / 暗 × 有在线 / 无在线 |
/// | 操作钮 `EmberActionButton` | 4 | 明 / 暗 × default / 额度用完(disabled) |
/// | 空态 `EmberEmpty` + unDraw 插画 | 2 | 明 / 暗 |
/// | 筛选 `EmberChip` | 2 | default / selected |
///
/// 为什么是**组件级 golden**(而不是模拟器截图):这里比的是取值 —— `overlay.scrim`
/// 叠字、`title` 24 Fraunces、标签白 22%、在线点 `status.success`、操作钮的
/// `brand.default` + `emberGlow` 与置灰三件套。设备字体、真实照片、手势轨迹属于
/// **模拟器手测**的范围(PR 正文「等待模拟器验收」那一段)。
///
/// 照片层在 widget 测试里拿不到真图(所有 HTTP 都返回 400),所以卡面走的是
/// 「无照片 / 图挂了」的内容占位(`surface.sunken` + Phosphor `user`),这本身也是
/// §4 卡面表里的一格;照片全出血与指示点由手测覆盖。
///
/// 重新生成:`cd app && flutter test --update-goldens test/features/discovery/discovery_golden_test.dart`
/// (只在**确认视觉改动就是想要的**之后跑,并人工看一眼 diff 图。)
void main() {
  /// 固定视口(390 宽 = 常见手机逻辑宽度)+ 关掉动效,截图不会撞上弹簧中间帧。
  Future<void> pumpScene(
    WidgetTester tester,
    Widget child, {
    required Brightness brightness,
    Size size = const Size(390, 844),
  }) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(brightness: brightness),
        themeAnimationDuration: Duration.zero,
        home: MediaQuery(
          data: MediaQueryData(size: size, disableAnimations: true),
          child: Scaffold(
            body: Center(
              child: Padding(padding: const EdgeInsets.all(20), child: child),
            ),
          ),
        ),
      ),
    );
    await tester.pump();
    await _precacheAssets(tester);
    await tester.pump();
  }

  Candidate candidate({int? age, String city = '上海', String bio = '喜欢爬山和看展'}) =>
      Candidate.fromJson(candidateJson(
        userId: 9,
        nickname: '小红',
        age: age ?? 25,
        city: city,
        bio: bio,
        tags: [tagJson(1, '运动'), tagJson(2, '音乐')],
      ));

  Widget card({required Presence? presence}) => SizedBox(
        width: 350,
        height: 560,
        child: ProfileCard(candidate: candidate(), presence: presence),
      );

  /// 操作钮场景:跳过(56)+ 喜欢(64)并排,`disabledLike` 时喜欢钮取额度用完形态。
  Widget actionButtons({required bool disabledLike}) => SizedBox(
        key: const Key('golden.actionButtons'),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            EmberActionButton(
              icon: PhosphorIconsRegular.x,
              semanticLabel: '跳过',
              onPressed: () {},
            ),
            const SizedBox(width: 24),
            EmberActionButton(
              icon: PhosphorIconsFill.heart,
              semanticLabel: '喜欢',
              variant: EmberActionButtonVariant.primary,
              size: EmberActionButtonSize.large,
              onPressed: disabledLike ? null : () {},
            ),
          ],
        ),
      );

  for (final brightness in Brightness.values) {
    final mode = brightness == Brightness.light ? 'light' : 'dark';

    testWidgets('卡面 golden · $mode · 在线', (tester) async {
      await pumpScene(
        tester,
        card(presence: const Presence(online: true)),
        brightness: brightness,
      );
      await expectLater(
        find.byType(ProfileCard),
        matchesGoldenFile('goldens/profile_card_${mode}_online.png'),
      );
    });

    testWidgets('卡面 golden · $mode · 不在线', (tester) async {
      await pumpScene(tester, card(presence: null), brightness: brightness);
      await expectLater(
        find.byType(ProfileCard),
        matchesGoldenFile('goldens/profile_card_${mode}_offline.png'),
      );
    });

    testWidgets('操作钮 golden · $mode · default', (tester) async {
      await pumpScene(
        tester,
        actionButtons(disabledLike: false),
        brightness: brightness,
        size: const Size(260, 160),
      );
      await expectLater(
        find.byKey(const Key('golden.actionButtons')),
        matchesGoldenFile('goldens/action_buttons_${mode}_default.png'),
      );
    });

    testWidgets('操作钮 golden · $mode · 额度用完(disabled)', (tester) async {
      await pumpScene(
        tester,
        actionButtons(disabledLike: true),
        brightness: brightness,
        size: const Size(260, 160),
      );
      await expectLater(
        find.byKey(const Key('golden.actionButtons')),
        matchesGoldenFile('goldens/action_buttons_${mode}_disabled.png'),
      );
    });

    testWidgets('空态 golden · $mode', (tester) async {
      await pumpScene(
        tester,
        EmberEmpty(
          illustration: const DiscoveryIllustration(
            DiscoveryIllustrationKind.emptyNearby,
          ),
          title: '附近暂时没有新的人了',
          description: '过会儿再来看看吧',
          actionLabel: '刷新',
          onAction: () {},
        ),
        brightness: brightness,
        size: const Size(390, 480),
      );
      await expectLater(
        find.byType(EmberEmpty),
        matchesGoldenFile('goldens/empty_state_$mode.png'),
      );
    });
  }

  testWidgets('筛选 chip golden · default', (tester) async {
    await pumpScene(
      tester,
      EmberChip(
        label: '筛选',
        icon: PhosphorIconsRegular.slidersHorizontal,
        onTap: () {},
      ),
      brightness: Brightness.light,
      size: const Size(160, 120),
    );
    await expectLater(
      find.byType(EmberChip),
      matchesGoldenFile('goldens/filter_chip_default.png'),
    );
  });

  testWidgets('筛选 chip golden · selected', (tester) async {
    await pumpScene(
      tester,
      EmberChip(
        label: '筛选',
        icon: PhosphorIconsRegular.slidersHorizontal,
        selected: true,
        onTap: () {},
      ),
      brightness: Brightness.light,
      size: const Size(160, 120),
    );
    await expectLater(
      find.byType(EmberChip),
      matchesGoldenFile('goldens/filter_chip_selected.png'),
    );
  });
}

/// 把树里的**资源图**先解码好再截图(`Image.asset` 的解码是异步的,直接截会截到空).
///
/// 只处理 `AssetImage`:照片层是网络图,在 widget 测试里一律 400(而且会抛到
/// `precacheImage` 上),所以跳过 —— 卡面 golden 用内容占位,见文件头说明。
Future<void> _precacheAssets(WidgetTester tester) async {
  final elements = find.byType(Image).evaluate().toList();
  await tester.runAsync(() async {
    for (final element in elements) {
      final provider = (element.widget as Image).image;
      if (provider is! AssetImage) continue;
      await precacheImage(provider, element);
    }
  });
}
