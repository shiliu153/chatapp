import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_brand_mark.dart';
import '../../core/widgets/app_button.dart';
import '../../core/widgets/app_error_view.dart';
import '../legal/agreement_dialog.dart';
import '../legal/legal_gate.dart';
import 'session.dart';

/// 启动页(附录 E):静态品牌区 + 状态文案。
/// **去掉原 CircularProgressIndicator** —— 常驻无限动画会让 pumpAndSettle 用例不收敛。
class SplashPage extends ConsumerStatefulWidget {
  const SplashPage({super.key});

  @override
  ConsumerState<SplashPage> createState() => _SplashPageState();
}

class _SplashPageState extends ConsumerState<SplashPage> {
  bool _agreementDeclined = false;

  @override
  void initState() {
    super.initState();
    // 第一步就是 await,状态变更发生在异步之后,initState 里触发是安全的
    _start();
  }

  Future<void> _start() async {
    if (_agreementDeclined) setState(() => _agreementDeclined = false);
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
    final session = ref.watch(sessionProvider);
    return Scaffold(
      backgroundColor: AppColors.bgPage,
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.xxl),
          child: switch (session) {
            SessionBootFailed(:final message) => AppErrorView(
                message: message,
                retryKey: const Key('splash.retry'),
                onRetry: () => ref.read(sessionProvider.notifier).bootstrap(),
              ),
            _ when _agreementDeclined => Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const AppBrandMark(key: Key('splash.brand')),
                  const SizedBox(height: AppSpacing.lg),
                  Text(
                    '需要同意《用户协议》与《隐私政策》才能使用本应用',
                    textAlign: TextAlign.center,
                    style: AppText.caption.copyWith(color: AppColors.text2),
                  ),
                  const SizedBox(height: AppSpacing.xxl),
                  AppButton(
                    key: const Key('splash.reread'),
                    label: '重新阅读',
                    onPressed: _start,
                  ),
                ],
              ),
            _ => Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const AppBrandMark(key: Key('splash.brand')),
                  const SizedBox(height: AppSpacing.lg),
                  Text('交友 Chat',
                      style: AppText.title.copyWith(color: AppColors.text1)),
                  const SizedBox(height: AppSpacing.xs),
                  Text('正在启动…',
                      style: AppText.caption.copyWith(color: AppColors.text2)),
                ],
              ),
          },
        ),
      ),
    );
  }
}
