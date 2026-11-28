import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../core/app_info.dart';
import '../../core/theme/app_typography.dart';
import '../../core/theme/ember_theme_context.dart';
import '../../core/theme/tokens.g.dart' as tokens;
import '../../core/ui/ember_ui.dart';
import '../auth/ember_brand_mark.dart';
import 'widgets/settings_rows.dart';

/// 关于页(E-5.6b 迁移到 Ember):应用名、版本、协议入口与版权。
///
/// 只换皮:展示内容一字不动(`appDisplayName` / `appVersion` / `appIcpNumber` 仍以
/// `core/app_info.dart` 为唯一事实来源)。品牌 mark 换成准入线用的
/// [`EmberBrandMark`](朱砂圆角方 + 心形,没有渐变 —— 心跳期的渐变 mark 已退役);
/// 协议入口走 [`EmberSettingsTile`],版权两行走 `micro` + `text.tertiary`。
class AboutPage extends StatelessWidget {
  /// 构造关于页。
  const AboutPage({super.key});

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return EmberPageScaffold(
      title: '关于',
      backKey: const Key('about.back'),
      body: ListView(
        padding: EdgeInsets.only(
          top: tokens.space32,
          bottom: tokens.space40 + MediaQuery.viewPaddingOf(context).bottom,
        ),
        children: [
          const Center(child: EmberBrandMark(size: 72)),
          SizedBox(height: tokens.space16),
          Center(
            child: Text(
              appDisplayName,
              style: AppText.title.copyWith(color: colors.textPrimary),
            ),
          ),
          SizedBox(height: tokens.space4),
          Center(
            child: Text(
              '版本 $appVersion',
              key: const Key('about.version'),
              style: AppText.caption.copyWith(color: colors.textTertiary),
            ),
          ),
          SizedBox(height: tokens.space32),
          SettingsGroup(
            children: [
              EmberSettingsTile(
                key: const Key('about.agreement'),
                icon: PhosphorIconsRegular.fileText,
                title: '用户协议',
                showChevron: true,
                showDivider: true,
                padding: settingsRowPadding,
                onTap: () => context.push('/legal/agreement'),
              ),
              EmberSettingsTile(
                key: const Key('about.privacy'),
                icon: PhosphorIconsRegular.shieldCheck,
                title: '隐私政策',
                showChevron: true,
                padding: settingsRowPadding,
                onTap: () => context.push('/legal/privacy'),
              ),
            ],
          ),
          SizedBox(height: tokens.space32),
          if (appIcpNumber.isNotEmpty)
            Center(
              child: Text(
                appIcpNumber,
                style: AppText.micro.copyWith(color: colors.textTertiary),
              ),
            ),
          Center(
            child: Text(
              '© 2026 $appDisplayName',
              style: AppText.micro.copyWith(color: colors.textTertiary),
            ),
          ),
        ],
      ),
    );
  }
}
