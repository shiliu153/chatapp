import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_colors.dart';
import 'package:chatapp_app/core/widgets/app_chip_group.dart';
import 'package:chatapp_app/core/widgets/app_option_group.dart';

void main() {
  testWidgets('多选切换:点未选加入,点已选移除', (tester) async {
    Set<int> selected = {1};
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: StatefulBuilder(
          builder: (context, setState) => AppChipGroup<int>(
            items: const [
              AppOption(value: 1, label: '运动'),
              AppOption(value: 2, label: '音乐'),
            ],
            selected: selected,
            onChanged: (next) => setState(() => selected = next),
          ),
        ),
      ),
    ));

    BoxDecoration decorationOf(String label) => tester
        .widget<AnimatedContainer>(find.ancestor(
          of: find.text(label),
          matching: find.byType(AnimatedContainer),
        ))
        .decoration! as BoxDecoration;

    expect(decorationOf('运动').color, AppColors.brand.withValues(alpha: .12));
    expect(tester.widget<Text>(find.text('运动')).style!.color, AppColors.brand);

    await tester.tap(find.text('音乐'));
    await tester.pump();
    expect(selected, {1, 2});
    expect(decorationOf('音乐').color, AppColors.brand.withValues(alpha: .12));

    await tester.tap(find.text('运动'));
    await tester.pump();
    expect(selected, {2});
  });
}
