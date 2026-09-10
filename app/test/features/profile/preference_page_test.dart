import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

void main() {
  testWidgets('设置偏好并保存 → PATCH 内容正确', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'PATCH /users/me/preference': (options) =>
          ok({'target_gender': 'female', 'age_min': 20, 'age_max': 30, 'city': ''}),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await tester.tap(navTab('我的'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('想找的人'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('女'));
    await tester.tap(find.byKey(const Key('preference.save')));
    await tester.pumpAndSettle();

    final patch =
        adapter.log.lastWhere((r) => r.method == 'PATCH').data as Map<String, dynamic>;
    expect(patch['target_gender'], 'female');
    expect(patch['age_min'], 18);
    expect(patch['age_max'], 99);
  });
}
