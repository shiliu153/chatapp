import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/app_row_group.dart';
import '../../support/heart_theme.dart';

void main() {
  testWidgets('行之间插 1px divider;单行不插', (tester) async {
    await tester.pumpWidget(MaterialApp(theme: heartTheme, 
      home: Scaffold(
        body: AppRowGroup(children: [Text('A'), Text('B'), Text('C')]),
      ),
    ));
    expect(find.byType(Divider), findsNWidgets(2));

    await tester.pumpWidget(MaterialApp(theme: heartTheme, 
      home: Scaffold(body: AppRowGroup(children: [Text('A')])),
    ));
    expect(find.byType(Divider), findsNothing);
  });
}
