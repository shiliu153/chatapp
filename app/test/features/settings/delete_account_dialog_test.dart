import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/ui/ember_ui.dart';
import 'package:chatapp_app/features/settings/widgets/delete_account_dialog.dart';
import '../../support/heart_theme.dart';

/// 注销账号的第二步确认(E-5.6b 迁移到 `EmberDialog` + `EmberField`)。
///
/// 与迁移前的差别只有**校验时机**:`EmberDialog` 没有「禁用确认键」的能力,所以
/// 确认键始终可点,点下去才校验 —— 不合法时在字段下方给 `status.danger` 说明
/// (page spec §5「表单校验失败:字段下方 danger 文字,不弹全局 Toast」)。
/// 安全口径不变:不输入完整 11 位手机号,请求发不出去、弹窗不关。
void main() {
  /// 照 app_dialog_test.dart 的写法:用按钮打开弹窗,把返回值存进闭包变量。
  Future<void> openDialog(WidgetTester tester, void Function(String?) onResult) async {
    await tester.pumpWidget(MaterialApp(theme: heartTheme,
      home: Scaffold(
        body: Builder(
          builder: (context) => TextButton(
            onPressed: () async => onResult(await showDeleteAccountDialog(context)),
            child: const Text('开'),
          ),
        ),
      ),
    ));
    await tester.tap(find.text('开'));
    await tester.pumpAndSettle();
  }

  testWidgets('手机号不合法时给字段级说明、弹窗不关;填对了才返回', (tester) async {
    String? result;
    await openDialog(tester, (value) => result = value);

    expect(find.text('注销账号'), findsOneWidget);
    expect(find.byKey(const Key('deleteAccount.phone')), findsOneWidget);

    // 未输入 → 点确认:说明出现、弹窗还在、没有返回值
    await tester.tap(find.byKey(const Key('deleteAccount.confirm')));
    await tester.pumpAndSettle();
    expect(find.text('请输入当前账号的 11 位手机号'), findsOneWidget);
    expect(find.text('注销账号'), findsOneWidget);
    expect(result, isNull);

    // 位数不够 → 仍然拦下
    await tester.enterText(find.byKey(const Key('deleteAccount.phone')), '138');
    await tester.pumpAndSettle();
    expect(find.text('请输入当前账号的 11 位手机号'), findsNothing); // 一改动就撤掉旧说明
    await tester.tap(find.byKey(const Key('deleteAccount.confirm')));
    await tester.pumpAndSettle();
    expect(find.text('请输入当前账号的 11 位手机号'), findsOneWidget);
    expect(result, isNull);

    // 11 位 → 关闭并回传手机号
    await tester.enterText(find.byKey(const Key('deleteAccount.phone')), '13800138000');
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('deleteAccount.confirm')));
    await tester.pumpAndSettle();
    expect(result, '13800138000');
    expect(find.text('注销账号'), findsNothing);
  });

  testWidgets('取消返回 null', (tester) async {
    String? result;
    await openDialog(tester, (value) => result = value);

    await tester.enterText(find.byKey(const Key('deleteAccount.phone')), '13800138000');
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('deleteAccount.cancel')));
    await tester.pumpAndSettle();
    expect(result, isNull);
  });

  testWidgets('确认键是危险变体(§8.3「实底只在二次确认后」)', (tester) async {
    await openDialog(tester, (_) {});
    expect(
      tester.widget<EmberButton>(find.byKey(const Key('deleteAccount.confirm'))).variant,
      EmberButtonVariant.danger,
    );
  });
}
