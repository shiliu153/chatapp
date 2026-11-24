import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import 'package:chatapp_app/core/theme/app_theme.dart';
import 'package:chatapp_app/core/theme/ember_theme_context.dart';
import 'package:chatapp_app/core/theme/tokens.g.dart' as tokens;
import 'package:chatapp_app/core/ui/ember_ui.dart';

/// 二级页组件 golden(E-5.6a,page spec §6 第 2 条 + §7 拍板:本组 **14 张**)。
///
/// | 组件 | 张数 | 覆盖 |
/// |---|---|---|
/// | `EmberPageScaffold`(代表页) | 2 | 明 / 暗:顶栏 + 卡片内容 + 底部主操作区 |
/// | `EmberField` | 6 | 明 / 暗 × default / focus / error |
/// | `EmberSettingsTile` | 2 | 明 / 暗:文字值行 + 开关行 + 分隔线 |
/// | `EmberDialog` | 4 | 明 / 暗 × 常规 / 危险 |
///
/// 为什么是**组件级 golden**(而不是模拟器整页截图):这里比的是取值 —— 顶栏 52 /
/// 标题 17-w600 居中、输入框 `surface.card` + `border.divider` 与 focus 的 2px 外扩、
/// 行高 68–76 与开关的 `brand.default`、Dialog 的图标底与危险描边。设备字体、真实
/// 照片、键盘弹出属于**模拟器手测**(PR 正文「等待模拟器验收」那一段)。
///
/// 重新生成:`cd app && flutter test --update-goldens test/core/ui/secondary_components_golden_test.dart`
/// (只在**确认视觉改动就是想要的**之后跑,并人工看一眼 diff 图。)
void main() {
  /// 固定 390 宽视口 + 关掉动效(骨架 / 开关的 spring 会停在中间帧)。
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
          // 包一层 Scaffold:输入框 / Dialog 都需要 Material 祖先。
          child: Scaffold(body: child),
        ),
      ),
    );
    await tester.pump();
  }

  for (final brightness in Brightness.values) {
    final mode = brightness == Brightness.light ? 'light' : 'dark';

    // --- EmberPageScaffold:代表页(2 张)-------------------------------------
    testWidgets('二级页骨架 golden · $mode', (tester) async {
      await pumpScene(
        tester,
        EmberPageScaffold(
          key: const Key('golden.scaffold'),
          title: '用户协议',
          backKey: const Key('golden.back'),
          trailing: EmberButton(
            label: '稍后再说',
            variant: EmberButtonVariant.text,
            onPressed: () {},
          ),
          body: ListView(
            padding: EdgeInsets.only(top: tokens.space16),
            children: [
              EmberCard(
                child: Builder(
                  builder: (context) => Text(
                    '欢迎使用「交友 Chat」。本页是 §9.4 二级页 shell 的代表形态:'
                    '顶栏 52、标题 17/w600 居中、内容水平内边距 20、底部主操作区。',
                    style: TextStyle(
                      fontSize: tokens.fontSizeBody,
                      height: tokens.fontLineHeightBody,
                      color: context.ember.textPrimary,
                    ),
                  ),
                ),
              ),
            ],
          ),
          bottomBar: EmberButton(label: '同意并继续', expand: true, onPressed: () {}),
        ),
        brightness: brightness,
      );
      await expectLater(
        find.byKey(const Key('golden.scaffold')),
        matchesGoldenFile('goldens/ember_page_scaffold_$mode.png'),
      );
    });

    // --- EmberField:default / focus / error(6 张)---------------------------
    testWidgets('输入框 golden · $mode · default', (tester) async {
      await pumpScene(
        tester,
        Padding(
          padding: EdgeInsets.all(tokens.space20),
          child: EmberField(key: const Key('golden.field'), placeholder: '手机号'),
        ),
        brightness: brightness,
        // 视口收到内容大小(与 E-5.3 chat_golden 同口径):golden 只该含这个组件。
        size: const Size(390, 120),
      );
      await expectLater(
        find.byKey(const Key('golden.field')),
        matchesGoldenFile('goldens/ember_field_${mode}_default.png'),
      );
    });

    testWidgets('输入框 golden · $mode · focus(2px brand + 外扩)', (tester) async {
      await pumpScene(
        tester,
        Padding(
          padding: EdgeInsets.all(tokens.space20),
          child: EmberField(
            key: const Key('golden.field'),
            placeholder: '手机号',
            autofocus: true,
          ),
        ),
        brightness: brightness,
        size: const Size(390, 120),
      );
      await tester.pump();
      await expectLater(
        find.byKey(const Key('golden.field')),
        matchesGoldenFile('goldens/ember_field_${mode}_focus.png'),
      );
    });

    testWidgets('输入框 golden · $mode · error(2px danger + 说明文字)', (tester) async {
      await pumpScene(
        tester,
        Padding(
          padding: EdgeInsets.all(tokens.space20),
          child: EmberField(
            key: const Key('golden.field'),
            placeholder: '手机号',
            errorText: '请输入正确的手机号',
          ),
        ),
        brightness: brightness,
        size: const Size(390, 140),
      );
      await expectLater(
        find.byKey(const Key('golden.field')),
        matchesGoldenFile('goldens/ember_field_${mode}_error.png'),
      );
    });

    // --- EmberSettingsTile(2 张)-------------------------------------------
    testWidgets('设置行 golden · $mode', (tester) async {
      await pumpScene(
        tester,
        Align(
          alignment: Alignment.topLeft,
          child: SizedBox(
            width: 390,
            child: EmberCard(
              key: const Key('golden.tiles'),
              padding: EdgeInsets.symmetric(horizontal: tokens.space20),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  EmberSettingsTile(
                    title: '外观',
                    subtitle: '跟随系统或手动选择深浅色',
                    value: '深色',
                    showChevron: true,
                    onTap: () {},
                    showDivider: true,
                  ),
                  EmberSettingsTile(
                    title: '新消息通知',
                    subtitle: '关闭后不再收到推送',
                    switchValue: true,
                    onChanged: (_) {},
                    showDivider: true,
                  ),
                  EmberSettingsTile(
                    title: '隐身浏览',
                    icon: PhosphorIconsRegular.eyeSlash,
                    switchValue: false,
                    onChanged: (_) {},
                    showDivider: true,
                  ),
                  const EmberSettingsTile(title: '版本', value: '1.0.13'),
                ],
              ),
            ),
          ),
        ),
        brightness: brightness,
        size: const Size(390, 320),
      );
      await expectLater(
        find.byKey(const Key('golden.tiles')),
        matchesGoldenFile('goldens/ember_settings_tile_$mode.png'),
      );
    });

    // --- EmberDialog:常规 / 危险(4 张)-------------------------------------
    testWidgets('Dialog golden · $mode · 常规', (tester) async {
      await pumpScene(
        tester,
        Center(
          child: EmberDialog(
            key: const Key('golden.dialog'),
            icon: PhosphorIconsRegular.bell,
            title: '开启通知?',
            message: '开启后会收到新消息提醒,可随时在设置里关闭。',
            confirmLabel: '去开启',
            cancelLabel: '暂不开启',
          ),
        ),
        brightness: brightness,
        size: const Size(390, 360),
      );
      await expectLater(
        find.byKey(const Key('golden.dialog')),
        matchesGoldenFile('goldens/ember_dialog_${mode}_normal.png'),
      );
    });

    testWidgets('Dialog golden · $mode · 危险', (tester) async {
      await pumpScene(
        tester,
        Center(
          child: EmberDialog(
            key: const Key('golden.dialog'),
            icon: PhosphorIconsRegular.trash,
            title: '注销账号?',
            message: '注销后资料与对话都会删除,且不可恢复。',
            confirmLabel: '注销账号',
            cancelLabel: '再想想',
            danger: true,
          ),
        ),
        brightness: brightness,
        size: const Size(390, 360),
      );
      await expectLater(
        find.byKey(const Key('golden.dialog')),
        matchesGoldenFile('goldens/ember_dialog_${mode}_danger.png'),
      );
    });
  }
}
