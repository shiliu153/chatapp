import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'session.dart';

class SplashPage extends ConsumerStatefulWidget {
  const SplashPage({super.key});

  @override
  ConsumerState<SplashPage> createState() => _SplashPageState();
}

class _SplashPageState extends ConsumerState<SplashPage> {
  @override
  void initState() {
    super.initState();
    // bootstrap 的第一步就是 await,状态变更发生在异步之后,initState 里触发是安全的
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
