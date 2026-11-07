// L3 冒烟:安卓模拟器上跑一次「冷启动 → 登录页」。
//
// 门槛很低,但跑的是**真 App**:真 provider、真 Dio、真 go_router、真插件。
// 后端**故意不可达**(由 --dart-define=API_BASE=http://127.0.0.1:1/api/v1 注入,
// 见 .github/workflows/app-ui.yml),所以这条用例不依赖真网络 / 真短信 / 真数据库:
// 它证明的是「后端连不上时,App 仍能落到登录页而不是卡在启动页或直接崩溃」。
//
// 本机(WSL)没有安卓模拟器,只能由 CI 跑;`flutter test` 只扫 app/test/,
// 所以现有的 App 轨(.github/workflows/app.yml)不受这个目录影响。

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/features/legal/legal_texts.dart';
import 'package:chatapp_app/main.dart' as app;

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('冷启动(后端不可达)进登录页;非法手机号被本地校验拦下', (tester) async {
    // 真机首启会先弹协议弹窗,那样会停在协议态而不是登录页。
    // 与 test/support/harness.dart 的 pumpApp 同口径:预置「已同意当前版本协议」。
    // 这是 shared_preferences 的内存实现(纯 Dart,只换 platform instance),不依赖平台通道。
    SharedPreferences.setMockInitialValues({'legal.agreed_version': legalVersion});

    // 走真实入口:main.dart 的 main()(错误上报 → 证书预热 → 外观模式 → ProviderScope + ChatApp)
    await app.main();
    // 启动链里有真实网络调用(/app/config 连不上)与会话 bootstrap,
    // 要几轮真实帧才落地,所以用有界重试的 pumpAndSettle(不是 sleep)。
    await settleUntil(tester, find.byKey(const Key('login.submit')));

    // 断言 1:副标题(login_page.dart 的「手机号登录 / 注册」)
    expect(find.text('手机号登录 / 注册'), findsOneWidget);
    // 断言 2:主按钮文案(login_page.dart 的「登录 / 注册」)
    expect(find.text('登录 / 注册'), findsOneWidget);

    // 断言 3:非法手机号 → 本地校验 Toast,不发任何请求(login_page.dart:63)
    await tester.enterText(find.byKey(const Key('login.phone')), '12345');
    await tester.tap(find.byKey(const Key('login.submit')));
    await tester.pumpAndSettle();
    expect(find.text('请输入正确的手机号'), findsOneWidget);

    // AppToast 自带 2s 自动消失 Timer:把假时钟推过超时点,收尾不留 pending timer。
    await tester.pump(const Duration(seconds: 3));
  });
}

/// pumpAndSettle 只推进「已排帧」的动画,而启动链里的网络失败要走真实事件循环;
/// 所以有界地重试若干轮,直到 [finder] 命中或次数用尽(仍会由后面的 expect 报失败)。
Future<void> settleUntil(WidgetTester tester, Finder finder, {int attempts = 30}) async {
  for (var i = 0; i < attempts; i++) {
    await tester.pumpAndSettle();
    if (finder.evaluate().isNotEmpty) return;
    await tester.pump(const Duration(milliseconds: 200));
  }
}
