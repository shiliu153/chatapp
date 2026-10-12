import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/app_skeleton.dart';
import 'package:chatapp_app/features/profile/widgets/profile_skeleton.dart';
import 'package:chatapp_app/features/profile/widgets/user_profile_skeleton.dart';

import '../../support/harness.dart';

Widget wrap(Widget child) => MaterialApp(home: Scaffold(body: child));

void main() {
  // 骨架是无限呼吸动画:一律有限 pump,禁 pumpAndSettle
  testWidgets('ProfileSkeleton 渲染身份卡 + 行骨架', (tester) async {
    await tester.pumpWidget(wrap(const ProfileSkeleton()));
    await pumpFrames(tester, frames: 3);

    expect(find.byKey(const Key('profile.skeleton')), findsOneWidget);
    expect(find.byType(AppSkeleton), findsWidgets);
  });

  testWidgets('UserProfileSkeleton 渲染头图 + 行骨架', (tester) async {
    await tester.pumpWidget(wrap(const UserProfileSkeleton()));
    await pumpFrames(tester, frames: 3);

    expect(find.byKey(const Key('user.skeleton')), findsOneWidget);
    expect(find.byType(AppSkeleton), findsWidgets);
  });
}
