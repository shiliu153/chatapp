import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/settings/notification_settings_page.dart';

void main() {
  testWidgets('两个提醒开关都禁用,并标注即将上线', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: NotificationSettingsPage()));

    expect(find.text('新配对提醒'), findsOneWidget);
    expect(find.text('新消息提醒'), findsOneWidget);
    expect(find.text('即将上线'), findsNWidgets(2));

    final switches = tester.widgetList<Switch>(find.byType(Switch)).toList();
    expect(switches, hasLength(2));
    expect(switches.every((item) => item.onChanged == null), isTrue);
  });
}
