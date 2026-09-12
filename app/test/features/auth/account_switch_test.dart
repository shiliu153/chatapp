import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/im/im_client.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

const _loggedInAsU7 = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

void main() {
  testWidgets('被顶号退出后换账号登录,我的页要显示新账号的资料', (tester) async {
    var meCalls = 0;
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) {
        meCalls++;
        return ok(meCalls == 1
            ? profileJson(id: 7, nickname: 'Alice', gender: 'male')
            : profileJson(id: 8, nickname: 'Bob', gender: 'female'));
      },
      'POST /im/user_sig': (options) => ok({
            'user_sig': 'sig',
            'sdkappid': '1600161711',
            'im_user_id': 'u7',
            'expire': 604800,
          }),
      'POST /auth/sms/verify': (options) =>
          ok({'access': 'a3', 'refresh': 'r3', 'is_new_user': false, 'user_id': 8}),
    });
    final fake = await pumpApp(tester, adapter, prefs: _loggedInAsU7);
    await tester.pumpAndSettle();

    await tester.tap(navTab('我的'));
    await tester.pumpAndSettle();
    expect(find.text('Alice'), findsOneWidget);

    fake.emit(const ImKickedOffline());
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('login.phone')), findsOneWidget);

    await tester.enterText(find.byKey(const Key('login.phone')), '13300133002');
    await tester.enterText(find.byKey(const Key('login.code')), '123456');
    await tester.tap(find.byKey(const Key('login.submit')));
    await tester.pumpAndSettle();

    await tester.tap(navTab('我的'));
    await tester.pumpAndSettle();
    expect(find.text('Bob'), findsOneWidget);
    expect(find.text('Alice'), findsNothing);
  });
}
