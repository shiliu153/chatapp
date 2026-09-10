import 'package:flutter_test/flutter_test.dart';

import '../../support/harness.dart';
import '../../support/scripted_adapter.dart';

void main() {
  testWidgets('没有本地凭证启动 → 落在登录页', (tester) async {
    await pumpApp(tester, ScriptedAdapter({}));
    await tester.pumpAndSettle();
    expect(find.text('获取验证码'), findsOneWidget);
  });
}
