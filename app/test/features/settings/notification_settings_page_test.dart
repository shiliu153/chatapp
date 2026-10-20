import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/api_exception.dart';
import 'package:chatapp_app/core/push/push_controller.dart';
import 'package:chatapp_app/core/push/push_repository.dart';
import 'package:chatapp_app/features/settings/notification_settings_page.dart';

import '../../support/fake_push_service.dart';

/// 仓库替身:不发网络请求,只按内存里的偏好返回。
class _FakePushRepository implements PushRepository {
  _FakePushRepository(this.preferences, {this.failUpdate = false});

  PushPreferences preferences;
  final bool failUpdate;

  @override
  Future<PushPreferences> fetchPreferences() async => preferences;

  @override
  Future<PushPreferences> updatePreferences({bool? likes, bool? matches, bool? system}) async {
    if (failUpdate) throw ApiException('更新失败');
    preferences = preferences.copyWith(likes: likes, matches: matches, system: system);
    return preferences;
  }

  @override
  Future<void> registerDevice(String registrationId,
      {String platform = 'android', String? appVersion}) async {}

  @override
  Future<void> unregisterDevice(String registrationId) async {}
}

void main() {
  Future<FakePushService> pumpPage(
    WidgetTester tester, {
    PushPreferences? preferences,
    bool notificationEnabled = true,
    bool failUpdate = false,
  }) async {
    final fake = FakePushService(notificationEnabled: notificationEnabled);
    await tester.pumpWidget(ProviderScope(
      overrides: [
        pushServiceProvider.overrideWithValue(fake),
        pushRepositoryProvider.overrideWithValue(_FakePushRepository(
          preferences ?? const PushPreferences(likes: true, matches: true, system: true),
          failUpdate: failUpdate,
        )),
      ],
      child: const MaterialApp(home: NotificationSettingsPage()),
    ));
    await tester.pumpAndSettle();
    return fake;
  }

  testWidgets('三个开关按偏好渲染', (tester) async {
    await pumpPage(tester,
        preferences: const PushPreferences(likes: true, matches: true, system: false));

    expect(find.text('新的喜欢'), findsOneWidget);
    expect(find.text('配对成功'), findsOneWidget);
    expect(find.text('系统通知'), findsOneWidget);
    expect(find.text('新消息提醒需要接入离线推送,将在后续版本开放'), findsOneWidget);

    final switches = tester.widgetList<Switch>(find.byType(Switch)).toList();
    expect(switches, hasLength(3));
    expect(switches.every((item) => item.onChanged != null), isTrue);
    expect(switches.map((item) => item.value).toList(), [true, true, false]);
  });

  testWidgets('通知权限关闭时显示提示', (tester) async {
    await pumpPage(tester, notificationEnabled: false);
    expect(find.text('系统通知未开启'), findsOneWidget);
    expect(find.text('去开启'), findsOneWidget);
  });

  testWidgets('切换失败时回滚并提示', (tester) async {
    await pumpPage(tester, failUpdate: true);

    await tester.tap(find.byType(Switch).first);
    await tester.pumpAndSettle();

    expect(tester.widgetList<Switch>(find.byType(Switch)).first.value, isTrue);
    expect(find.text('更新失败'), findsOneWidget);

    await tester.pump(const Duration(seconds: 3)); // 放掉 AppToast 的自动消失定时器
  });
}
