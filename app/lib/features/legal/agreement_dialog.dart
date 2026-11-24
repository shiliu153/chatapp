import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../core/theme/tokens.g.dart' as tokens;
import '../../core/ui/ember_ui.dart';

/// 首次启动的协议弹窗(E-5.6a 迁移到 Ember):**不可点外部关闭**;同意返回 `true`,
/// 不同意返回 `false`。
///
/// 外壳换成 [`showEmberDialog`](`core/ui/ember_dialog.dart`,§9.3「图标 + 明确动词」),
/// 业务判断(同意才 `acceptLegal`)留在启动页,本文件只负责弹层本身。
///
/// 两个协议入口是**文字按钮**(§8.2:15/w600 `brand.default` 无底、最小触控 48),
/// 左对齐排在说明下面。
Future<bool?> showAgreementDialog(BuildContext context) => showEmberDialog(
      context,
      icon: PhosphorIconsRegular.scroll,
      title: '用户协议与隐私政策',
      message: '欢迎使用「交友 Chat」。请阅读并同意以下文件后再开始使用:',
      // 不同意 / 同意都必须是明确动词(§9.3);「不同意」本身是信息量充足的表达。
      cancelLabel: '不同意',
      confirmLabel: '同意并继续',
      cancelKey: const Key('agreement.decline'),
      confirmKey: const Key('agreement.accept'),
      barrierDismissible: false,
      content: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Align(
            alignment: Alignment.centerLeft,
            child: EmberButton(
              label: '《用户协议》',
              variant: EmberButtonVariant.text,
              onPressed: () => context.push('/legal/agreement'),
            ),
          ),
          SizedBox(height: tokens.space4),
          Align(
            alignment: Alignment.centerLeft,
            child: EmberButton(
              label: '《隐私政策》',
              variant: EmberButtonVariant.text,
              onPressed: () => context.push('/legal/privacy'),
            ),
          ),
        ],
      ),
    );
