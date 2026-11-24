import 'dart:ui' show Tristate;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import 'package:chatapp_app/core/theme/ember_colors.dart';
import 'package:chatapp_app/core/theme/tokens.g.dart' as tokens;
import 'package:chatapp_app/core/ui/ember_settings_tile.dart';

import 'ember_test_kit.dart';

/// 在固定 390 宽的舞台里渲染一行(页面逻辑宽度,与 golden 一致)。
Future<void> _pumpTile(WidgetTester tester, Widget tile, {Brightness brightness = Brightness.light}) async {
  await pumpEmber(
    tester,
    SizedBox(width: 390, child: tile),
    brightness: brightness,
  );
}

void main() {
  group('EmberSettingsTile · §5.2 行高与字阶', () {
    testWidgets('单行行高 68;标题 17/w600、副标题 13 text.secondary', (tester) async {
      await _pumpTile(
        tester,
        const EmberSettingsTile(title: '通知设置', subtitle: '新消息提醒方式'),
      );

      // 带副标题时落到 68–76 的 76 一侧(§5.2 区间)。
      final height = tester.getSize(find.byType(EmberSettingsTile)).height;
      expect(height, greaterThanOrEqualTo(68));
      expect(height, lessThanOrEqualTo(76));

      final title = tester.widget<Text>(find.text('通知设置'));
      expect(title.style!.fontSize, tokens.fontSizeSubtitle);
      expect(title.style!.fontWeight, FontWeight.w600);
      expect(title.style!.color, EmberColors.light.textPrimary);

      final subtitle = tester.widget<Text>(find.text('新消息提醒方式'));
      expect(subtitle.style!.fontSize, tokens.fontSizeCaption);
      expect(subtitle.style!.color, EmberColors.light.textSecondary);
    });

    testWidgets('无副标题时行高也是 68(下沿)', (tester) async {
      await _pumpTile(tester, const EmberSettingsTile(title: '深色模式', value: '跟随系统'));
      expect(tester.getSize(find.byType(EmberSettingsTile)).height, 68);
    });
  });

  group('EmberSettingsTile · 右侧 slot', () {
    testWidgets('文字值走 text.secondary;箭头走 caretRight 20', (tester) async {
      await _pumpTile(tester, const EmberSettingsTile(title: '外观', value: '深色'));
      expect(
        tester.widget<Text>(find.text('深色')).style!.color,
        EmberColors.light.textSecondary,
      );

      await _pumpTile(tester, const EmberSettingsTile(title: '关于', showChevron: true));
      final chevron = tester.widget<Icon>(find.byIcon(PhosphorIconsRegular.caretRight));
      expect(chevron.size, tokens.sizeIcon20);
      expect(chevron.color, EmberColors.light.textTertiary);
    });

    testWidgets('开关行:选中 brand.default 轨道,关闭 surface.sunken', (tester) async {
      await _pumpTile(
        tester,
        EmberSettingsTile(title: '通知', switchValue: true, onChanged: (_) {}),
      );
      var toggle = tester.widget<Switch>(find.byType(Switch));
      expect(toggle.value, isTrue);
      expect(toggle.activeTrackColor, EmberColors.light.brandDefault);
      expect(toggle.activeThumbColor, EmberColors.light.brandOn);

      await _pumpTile(
        tester,
        EmberSettingsTile(title: '通知', switchValue: false, onChanged: (_) {}),
      );
      toggle = tester.widget<Switch>(find.byType(Switch));
      expect(toggle.value, isFalse);
      expect(toggle.inactiveTrackColor, EmberColors.light.surfaceSunken);
    });

    testWidgets('开关行点击整行 → 切换一次(与心跳期 VisitsHiddenRow 同口径)', (tester) async {
      bool? next;
      await _pumpTile(
        tester,
        EmberSettingsTile(
          title: '通知',
          switchValue: true,
          onChanged: (value) => next = value,
        ),
      );
      await tester.tap(find.text('通知'));
      await tester.pump();
      expect(next, isFalse);
    });

    testWidgets('开关 + 自定义 trailing 同时给 → 构造断言失败', (tester) async {
      expect(
        () => EmberSettingsTile(
          title: 'x',
          switchValue: true,
          trailing: const SizedBox.shrink(),
        ),
        throwsAssertionError,
      );
    });
  });

  group('EmberSettingsTile · 状态矩阵(page spec §4)', () {
    testWidgets('pressed → 底 surface.sunken', (tester) async {
      await _pumpTile(tester, EmberSettingsTile(title: '黑名单', showChevron: true, onTap: () {}));
      final gesture = await tester.startGesture(tester.getCenter(find.text('黑名单')));
      await tester.pump();
      expect(
        tester
            .widgetList<ColoredBox>(find.byType(ColoredBox))
            .map((box) => box.color)
            .where((color) => color == EmberColors.light.surfaceSunken),
        isNotEmpty,
        reason: '按下时整行底色应转 surface.sunken(§8.3 pressed)',
      );
      await gesture.up();
      await tester.pump();
    });

    testWidgets('disabled → 标题 / 副标题 text.tertiary,读屏 enabled=false 且不可点', (tester) async {
      var taps = 0;
      final handle = tester.ensureSemantics();
      await _pumpTile(
        tester,
        EmberSettingsTile(
          title: '黑名单',
          subtitle: '暂时不可用',
          enabled: false,
          onTap: () => taps++,
        ),
      );

      expect(tester.widget<Text>(find.text('黑名单')).style!.color, EmberColors.light.textTertiary);
      expect(tester.widget<Text>(find.text('暂时不可用')).style!.color, EmberColors.light.textTertiary);
      expectSemanticallyEnabled(tester, find.byType(EmberSettingsTile), enabled: false);

      await tester.tap(find.text('黑名单'));
      await tester.pump();
      expect(taps, 0);
      handle.dispose();
    });

    testWidgets('showDivider → 底部 1px border.divider', (tester) async {
      await _pumpTile(
        tester,
        const EmberSettingsTile(title: '第一行', showDivider: true),
      );
      final decoration = tester
          .widget<DecoratedBox>(
            find.ancestor(of: find.text('第一行'), matching: find.byType(DecoratedBox)).first,
          )
          .decoration as BoxDecoration;
      expect(decoration.border!.bottom.color, EmberColors.light.borderDivider);
      expect(decoration.border!.bottom.width, 1);
    });

    testWidgets('深色:文字取深色档', (tester) async {
      await _pumpTile(
        tester,
        const EmberSettingsTile(title: '通知设置', subtitle: '新消息提醒方式'),
        brightness: Brightness.dark,
      );
      expect(tester.widget<Text>(find.text('通知设置')).style!.color, EmberColors.dark.textPrimary);
      expect(
        tester.widget<Text>(find.text('新消息提醒方式')).style!.color,
        EmberColors.dark.textSecondary,
      );
    });
  });

  group('EmberSettingsTile · 读屏(page spec §6 第 3 条)', () {
    testWidgets('开关行读「标题,已开启 / 已关闭」并带 toggled 标志', (tester) async {
      final handle = tester.ensureSemantics();
      await _pumpTile(
        tester,
        EmberSettingsTile(title: '新消息通知', switchValue: true, onChanged: (_) {}),
      );
      expect(semanticsOf(tester, find.byType(EmberSettingsTile)).label, '新消息通知,已开启');
      expect(
        tester
            .getSemantics(find.byType(EmberSettingsTile))
            .getSemanticsData()
            .flagsCollection
            .isToggled,
        Tristate.isTrue,
      );

      await _pumpTile(
        tester,
        EmberSettingsTile(title: '新消息通知', switchValue: false, onChanged: (_) {}),
      );
      expect(semanticsOf(tester, find.byType(EmberSettingsTile)).label, '新消息通知,已关闭');
      handle.dispose();
    });

    testWidgets('可点行进读屏的按钮集合,标签是标题', (tester) async {
      final handle = tester.ensureSemantics();
      await _pumpTile(
        tester,
        EmberSettingsTile(title: '设备管理', showChevron: true, onTap: () {}),
      );
      expect(semanticsOf(tester, find.byType(EmberSettingsTile)).label, '设备管理');
      expectSemanticallyButton(tester, find.byType(EmberSettingsTile), isButton: true);
      handle.dispose();
    });
  });
}
