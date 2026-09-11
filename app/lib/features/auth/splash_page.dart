import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../legal/agreement_dialog.dart';
import '../legal/legal_gate.dart';
import 'session.dart';

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
          SystemNavigator.pop();   // 移动端直接退出;上面的提示页只是兜底
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
      body: Center(
        child: switch (session) {
          SessionBootFailed(:final message) => Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(message),
                const SizedBox(height: 12),
                FilledButton(
                  onPressed: () => ref.read(sessionProvider.notifier).bootstrap(),
                  child: const Text('重试'),
                ),
              ],
            ),
          _ when _agreementDeclined => Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Text('需要同意《用户协议》与《隐私政策》才能使用本应用'),
                const SizedBox(height: 12),
                FilledButton(
                  key: const Key('splash.reread'),
                  onPressed: _start,
                  child: const Text('重新阅读'),
                ),
              ],
            ),
          _ => const Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                CircularProgressIndicator(),
                SizedBox(height: 12),
                Text('正在启动…'),
              ],
            ),
        },
      ),
    );
  }
}
