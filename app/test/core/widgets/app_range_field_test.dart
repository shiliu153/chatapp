import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/app_range_field.dart';

void main() {
  testWidgets('标题 + 双滑块;拖动起点滑块后回调新值', (tester) async {
    RangeValues values = const RangeValues(18, 99);
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: StatefulBuilder(
          builder: (context, setState) => AppRangeField(
            title: '年龄 ${values.start.round()} – ${values.end.round()} 岁',
            values: values,
            min: 18,
            max: 99,
            divisions: 81,
            onChanged: (next) => setState(() => values = next),
          ),
        ),
      ),
    ));

    expect(find.text('年龄 18 – 99 岁'), findsOneWidget);
    expect(find.byType(RangeSlider), findsOneWidget);

    // 抓「起点滑块」(轨道左端 = slider.left + 24,见 BaseRangeSliderTrackShape)
    // 往右拖;从正中拖会命中较近的那个滑块,断言会不稳。
    final slider = tester.getRect(find.byType(RangeSlider));
    await tester.dragFrom(
        Offset(slider.left + 24, slider.center.dy), const Offset(120, 0));
    await tester.pumpAndSettle();

    expect(values.start, greaterThan(18));
    expect(values.end, 99);
    expect(find.textContaining('年龄 ${values.start.round()}'), findsOneWidget);
  });
}
