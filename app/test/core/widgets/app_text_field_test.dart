import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_colors.dart';
import 'package:chatapp_app/core/widgets/app_text_field.dart';

Widget _wrap(Widget child) => MaterialApp(
      home: Scaffold(body: Padding(padding: const EdgeInsets.all(16), child: child)),
    );

void main() {
  testWidgets('单行盒高 52;label 在上方;能输入', (tester) async {
    final controller = TextEditingController();
    addTearDown(controller.dispose);
    await tester.pumpWidget(_wrap(AppTextField(
      key: const Key('f'),
      controller: controller,
      label: '昵称',
    )));

    expect(find.text('昵称'), findsOneWidget);
    // 内盒高恒为 52(§7);label 在盒上方,所以整体比 52 高
    expect(
      tester.getSize(find.descendant(
        of: find.byKey(const Key('f')),
        matching: find.byType(AnimatedContainer),
      )).height,
      52,
    );

    await tester.enterText(find.byKey(const Key('f')), '小明');
    expect(controller.text, '小明');
  });

  testWidgets('聚焦时描边 1.5 brand', (tester) async {
    final node = FocusNode();
    addTearDown(node.dispose);
    await tester.pumpWidget(_wrap(AppTextField(
      key: const Key('f'),
      label: '昵称',
      focusNode: node,
    )));

    BoxDecoration decorationOf() {
      final container = tester.widget<AnimatedContainer>(find.descendant(
        of: find.byKey(const Key('f')),
        matching: find.byType(AnimatedContainer),
      ));
      return container.decoration! as BoxDecoration;
    }

    expect((decorationOf().border! as Border).top.color, AppColors.divider);
    expect((decorationOf().border! as Border).top.width, 1);

    node.requestFocus();
    await tester.pumpAndSettle();
    expect((decorationOf().border! as Border).top.color, AppColors.brand);
    expect((decorationOf().border! as Border).top.width, 1.5);
  });

  testWidgets('maxLength 渲染 x/y 计数并随输入更新', (tester) async {
    final controller = TextEditingController();
    addTearDown(controller.dispose);
    await tester.pumpWidget(_wrap(AppTextField(
      key: const Key('f'),
      controller: controller,
      label: '简介',
      maxLines: 3,
      maxLength: 200,
      counterKey: const Key('f.counter'),
    )));

    expect(find.byKey(const Key('f.counter')), findsOneWidget);
    expect(find.text('0/200'), findsOneWidget);

    await tester.enterText(find.byKey(const Key('f')), '你好');
    await tester.pump();
    expect(find.text('2/200'), findsOneWidget);
  });

  testWidgets('suffix 渲染在输入区右侧', (tester) async {
    await tester.pumpWidget(_wrap(AppTextField(
      key: const Key('f'),
      label: '验证码',
      suffix: const Text('获取验证码', key: Key('f.suffix')),
    )));

    expect(find.byKey(const Key('f.suffix')), findsOneWidget);
    final fieldX = tester.getCenter(find.byType(EditableText)).dx;
    final suffixX = tester.getCenter(find.byKey(const Key('f.suffix'))).dx;
    expect(suffixX, greaterThan(fieldX));
  });

  testWidgets('borderless:无描边无底色', (tester) async {
    await tester.pumpWidget(_wrap(const AppTextField(
      key: Key('f'),
      hint: '分享新鲜事…',
      borderless: true,
      maxLines: 6,
      minLines: 6,
    )));

    expect(find.text('分享新鲜事…'), findsOneWidget);
    expect(
      find.descendant(
          of: find.byKey(const Key('f')), matching: find.byType(AnimatedContainer)),
      findsNothing,
    );
  });
}
