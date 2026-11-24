import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/app_config.dart';
import '../../core/app_info.dart';
import '../../core/providers.dart';
import '../../core/theme/app_typography.dart';
import '../../core/theme/ember_theme_context.dart';
import '../../core/theme/tokens.g.dart' as tokens;
import '../../core/ui/ember_ui.dart';
import '../legal/agreement_dialog.dart';
import '../legal/legal_gate.dart';
import 'ember_brand_mark.dart';
import 'session.dart';

/// 启动页(附录 E):静态品牌区 + 状态文案(E-5.6a 迁移到 Ember)。
///
/// **去掉原 CircularProgressIndicator** —— 常驻无限动画会让 pumpAndSettle 用例不收敛。
///
/// 本单只换皮:启动流程(`appConfigCheckEnabled` 强更检查 → 协议闸门 → bootstrap)
/// 与三个分支(强更 / 拒绝协议 / 启动失败)的业务判断一行未动。
class SplashPage extends ConsumerStatefulWidget {
  /// 构造启动页。
  const SplashPage({super.key});

  @override
  ConsumerState<SplashPage> createState() => _SplashPageState();
}

/// 强制更新分支:品牌 + 标题 + 版本说明 + 「复制下载地址」主按钮。
class _ForceUpdateView extends StatelessWidget {
  const _ForceUpdateView({required this.config});

  final AppConfig config;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return Column(
      key: const Key('splash.forceUpdate'),
      mainAxisSize: MainAxisSize.min,
      children: [
        const EmberBrandMark(key: Key('splash.brand')),
        SizedBox(height: tokens.space20),
        Text(
          '需要更新后才能继续使用',
          textAlign: TextAlign.center,
          style: AppText.title.copyWith(color: colors.textPrimary),
        ),
        SizedBox(height: tokens.space8),
        Text(
          '当前版本 $appVersion,最低要求 ${config.minAppVersion}',
          textAlign: TextAlign.center,
          style: AppText.caption.copyWith(color: colors.textSecondary),
        ),
        if (config.downloadUrl.isNotEmpty) ...[
          SizedBox(height: tokens.space32),
          EmberButton(
            key: const Key('splash.download'),
            label: '复制下载地址',
            onPressed: () =>
                Clipboard.setData(ClipboardData(text: config.downloadUrl)),
          ),
        ],
      ],
    );
  }
}

class _SplashPageState extends ConsumerState<SplashPage> {
  bool _agreementDeclined = false;
  AppConfig? _forceUpdate;

  @override
  void initState() {
    super.initState();
    // 第一步就是 await,状态变更发生在异步之后,initState 里触发是安全的
    _start();
  }

  Future<void> _start() async {
    if (_agreementDeclined) setState(() => _agreementDeclined = false);
    if (ref.read(appConfigCheckEnabledProvider)) {
      final config = await fetchAppConfig(ref.read(apiClientProvider));
      if (!mounted) return;
      if (config != null && isOutdated(current: appVersion, min: config.minAppVersion)) {
        setState(() => _forceUpdate = config);
        return;
      }
    }
    if (!await hasAgreedToLegal()) {
      if (!mounted) return;
      final accepted = await showAgreementDialog(context);
      if (accepted != true) {
        if (!mounted) return;
        setState(() => _agreementDeclined = true);
        if (defaultTargetPlatform == TargetPlatform.android ||
            defaultTargetPlatform == TargetPlatform.iOS) {
          SystemNavigator.pop(); // 移动端直接退出;上面的提示页只是兜底
        }
        return;
      }
      await acceptLegal();
    }
    if (!mounted) return;
    ref.read(sessionProvider.notifier).bootstrap();
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final session = ref.watch(sessionProvider);
    return Scaffold(
      backgroundColor: colors.surfacePage,
      body: Center(
        child: Padding(
          padding: EdgeInsets.all(tokens.space32),
          child: switch (session) {
            _ when _forceUpdate != null => _ForceUpdateView(config: _forceUpdate!),
            SessionBootFailed(:final message) => EmberEmpty(
                // 启动失败没有专门的插画:用品牌 mark 当中性「暖色几何体」
                // (§6 空态纪律:禁止灰色图标占位)。
                illustration: const EmberBrandMark(),
                title: '没能加载出来',
                description: message,
                actionLabel: '重试',
                actionKey: const Key('splash.retry'),
                onAction: () => ref.read(sessionProvider.notifier).bootstrap(),
              ),
            _ when _agreementDeclined => Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const EmberBrandMark(key: Key('splash.brand')),
                  SizedBox(height: tokens.space20),
                  Text(
                    '需要同意《用户协议》与《隐私政策》才能使用本应用',
                    textAlign: TextAlign.center,
                    style: AppText.caption.copyWith(color: colors.textSecondary),
                  ),
                  SizedBox(height: tokens.space32),
                  EmberButton(
                    key: const Key('splash.reread'),
                    label: '重新阅读',
                    onPressed: _start,
                  ),
                ],
              ),
            _ => Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const EmberBrandMark(key: Key('splash.brand')),
                  SizedBox(height: tokens.space20),
                  Text(
                    '交友 Chat',
                    style: AppText.display.copyWith(color: colors.textPrimary),
                  ),
                  SizedBox(height: tokens.space4),
                  Text(
                    '正在启动…',
                    style: AppText.caption.copyWith(color: colors.textSecondary),
                  ),
                ],
              ),
          },
        ),
      ),
    );
  }
}
