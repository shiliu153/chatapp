import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

/// 首启协议弹窗:不可点外部关闭;同意返回 true,不同意返回 false。
Future<bool?> showAgreementDialog(BuildContext context) => showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        title: const Text('用户协议与隐私政策'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('欢迎使用「交友 Chat」。请阅读并同意以下文件后再开始使用:'),
            TextButton(
              onPressed: () => context.push('/legal/agreement'),
              child: const Text('《用户协议》'),
            ),
            TextButton(
              onPressed: () => context.push('/legal/privacy'),
              child: const Text('《隐私政策》'),
            ),
          ],
        ),
        actions: [
          TextButton(
            key: const Key('agreement.decline'),
            onPressed: () => Navigator.pop(context, false),
            child: const Text('不同意'),
          ),
          FilledButton(
            key: const Key('agreement.accept'),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('同意并继续'),
          ),
        ],
      ),
    );
