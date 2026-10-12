import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_colors.dart';
import 'package:chatapp_app/core/widgets/app_list_row.dart';

void main() {
  testWidgets('图标 + 标题 + 副标题 + 默认 chevron;高 64;点击回调', (tester) async {
    var taps = 0;
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: AppListRow(
          key: const Key('row'),
          icon: Icons.block_rounded,
          title: '黑名单',
          subtitle: '3 人',
          onTap: () => taps++,
        ),
      ),
    ));

    expect(tester.getSize(find.byKey(const Key('row'))).height, 64);
    expect(find.byIcon(Icons.block_rounded), findsOneWidget);
    expect(find.byIcon(Icons.chevron_right_rounded), findsOneWidget);
    expect(find.text('3 人'), findsOneWidget);

    await tester.tap(find.byKey(const Key('row')));
    expect(taps, 1);
  });

  testWidgets('trailing 覆盖 chevron', (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: AppListRow(
          title: '小红',
          trailing: const Text('解除', key: Key('row.trailing')),
        ),
      ),
    ));
    expect(find.byKey(const Key('row.trailing')), findsOneWidget);
    expect(find.byIcon(Icons.chevron_right_rounded), findsNothing);
  });

  testWidgets('danger + centerTitle:居中 danger 字,无图标无 chevron', (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: AppListRow(
          key: const Key('row'),
          title: '退出登录',
          centerTitle: true,
          danger: true,
          onTap: () {},
        ),
      ),
    ));

    final text = tester.widget<Text>(find.text('退出登录'));
    expect(text.style!.color, AppColors.danger);
    expect(text.style!.fontWeight, FontWeight.w600);
    expect(find.byIcon(Icons.chevron_right_rounded), findsNothing);

    final rowCenter = tester.getCenter(find.byKey(const Key('row'))).dx;
    final textCenter = tester.getCenter(find.text('退出登录')).dx;
    expect(textCenter, closeTo(rowCenter, 0.5));
  });
}
