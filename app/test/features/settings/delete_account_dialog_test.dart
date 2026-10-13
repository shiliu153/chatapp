import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/app_button.dart';
import 'package:chatapp_app/features/settings/widgets/delete_account_dialog.dart';

void main() {
  /// 照 app_dialog_test.dart 的写法:用按钮打开弹窗,把返回值存进闭包变量。
  Future<void> openDialog(WidgetTester tester, void Function(String?) onResult) async {
    await tester.pumpWidget(MaterialApp(
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

  testWidgets('手机号不合法时确认按钮禁用,填对了才可点', (tester) async {
    await openDialog(tester, (_) {});

    expect(find.text('注销账号'), findsOneWidget);
    expect(find.byKey(const Key('deleteAccount.phone')), findsOneWidget);
    expect(
      tester.widget<AppButton>(find.byKey(const Key('deleteAccount.confirm'))).onPressed,
      isNull, // 未输入 → 禁用
    );

    await tester.enterText(find.byKey(const Key('deleteAccount.phone')), '138');
    await tester.pumpAndSettle();
    expect(
      tester.widget<AppButton>(find.byKey(const Key('deleteAccount.confirm'))).onPressed,
      isNull, // 位数不够 → 仍禁用
    );

    await tester.enterText(find.byKey(const Key('deleteAccount.phone')), '13800138000');
    await tester.pumpAndSettle();
    expect(
      tester.widget<AppButton>(find.byKey(const Key('deleteAccount.confirm'))).onPressed,
      isNotNull,
    );
  });

  testWidgets('确认返回输入的手机号;取消返回 null', (tester) async {
    String? result;
    await openDialog(tester, (value) => result = value);

    await tester.enterText(find.byKey(const Key('deleteAccount.phone')), '13800138000');
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('deleteAccount.confirm')));
    await tester.pumpAndSettle();
    expect(result, '13800138000');

    await tester.tap(find.text('开'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('deleteAccount.cancel')));
    await tester.pumpAndSettle();
    expect(result, isNull);
  });

  testWidgets('确认按钮是危险实底(§7「实底(二次确认后)」)', (tester) async {
    await openDialog(tester, (_) {});
    expect(
      tester.widget<AppButton>(find.byKey(const Key('deleteAccount.confirm'))).variant,
      AppButtonVariant.dangerFilled,
    );
  });
}
