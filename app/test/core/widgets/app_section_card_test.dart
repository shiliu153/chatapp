import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_colors.dart';
import 'package:chatapp_app/core/theme/app_radius.dart';
import 'package:chatapp_app/core/widgets/app_section_card.dart';

void main() {
  testWidgets('白卡 R20 + 分组标题在最上;子项按 gap 竖排', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(
        body: AppSectionCard(
          key: Key('card'),
          title: '基本信息',
          children: [Text('甲'), Text('乙')],
        ),
      ),
    ));

    expect(find.text('基本信息'), findsOneWidget);
    expect(find.text('甲'), findsOneWidget);
    expect(find.text('乙'), findsOneWidget);

    final container = tester.widget<Container>(find.descendant(
      of: find.byKey(const Key('card')),
      matching: find.byType(Container),
    ));
    final decoration = container.decoration! as BoxDecoration;
    expect(decoration.color, AppColors.bgCard);
    expect((decoration.borderRadius! as BorderRadius).topLeft.x, AppRadius.card);

    final titleY = tester.getCenter(find.text('基本信息')).dy;
    final firstY = tester.getCenter(find.text('甲')).dy;
    final secondY = tester.getCenter(find.text('乙')).dy;
    expect(titleY, lessThan(firstY));
    expect(firstY, lessThan(secondY));
  });
}
