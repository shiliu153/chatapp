import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/tokens.g.dart' as tokens;

/// `tokens.radiusPill`(999)在小尺寸下**等价于「高度一半」**的机械证明。
///
/// 为什么需要这条用例
/// ------------------
/// 裸值白名单里三条存量圆角(`profile_card` 的 6px 滑动指示点写 `circular(3)`、
/// `profile_voice_card` 的 4px 录制进度条写 `circular(2)` 两处)换 `tokens.radiusPill`
/// 之前,必须先证明「999 在这个尺寸下画出来的半径就是高度一半」,而不是凭直觉换 ——
/// 换错的后果是三个页面的圆角在真机上肉眼可辨地变。
///
/// 怎么证
/// ------
/// 圆角的钳位(`radius > 高度一半` 时按比例缩到高度一半)发生在**绘制期**(Skia 的
/// `SkRRect::setRectRadii` 归一化),`BorderRadius.circular()` 本身不做这件事。所以
/// 判据不是比较 `BorderRadius` 对象,而是**把两种取值真画出来,比较像素**:
/// 同一个尺寸、同一个颜色,只换圆角取值,逐字节比对 PNG —— 相同即「生效半径相同」。
///
/// 反例(让这条用例有牙):同一尺寸下 `circular(999)` 与 `circular(1)` 必须**不**相同,
/// 否则说明这套比对根本分不出差异。
///
/// 备注信息:
/// 光栅化跑在 `flutter test` 的 Skia 软件后端上;真机(Impeller)侧另有两条既有事实兜底:
/// ① `tokens.radiusPill` 在两端已有大量既有用法(聊天气泡、导航胶囊等,尺寸都远小于 999);
/// ② `profile_card` / `profile_edit` 的 golden 用例在本次改动后仍逐像素通过。
void main() {
  /// 把一个纯色圆角矩形画出来,返回 PNG 字节。
  Future<Uint8List> pixelsOf(
    WidgetTester tester, {
    required Size size,
    required double radius,
  }) async {
    final GlobalKey key = GlobalKey();
    tester.view.physicalSize = const Size(96, 96);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        home: Center(
          child: RepaintBoundary(
            key: key,
            child: Container(
              width: size.width,
              height: size.height,
              decoration: BoxDecoration(
                color: const Color(0xFF000000),
                borderRadius: BorderRadius.circular(radius),
              ),
            ),
          ),
        ),
      ),
    );
    await tester.pump();
    final RenderRepaintBoundary boundary =
        key.currentContext!.findRenderObject()! as RenderRepaintBoundary;
    late Uint8List bytes;
    await tester.runAsync(() async {
      final ui.Image image = await boundary.toImage();
      final ByteData? data = await image.toByteData(format: ui.ImageByteFormat.png);
      image.dispose();
      bytes = data!.buffer.asUint8List();
    });
    return bytes;
  }

  testWidgets('指示点 6×6:radiusPill 与 circular(3) 渲染逐字节相同', (tester) async {
    final Uint8List pill = await pixelsOf(
      tester,
      size: const Size(6, 6),
      radius: tokens.radiusPill,
    );
    final Uint8List half = await pixelsOf(
      tester,
      size: const Size(6, 6),
      radius: 3,
    );
    expect(listEquals(pill, half), isTrue);
  });

  testWidgets('指示点激活态 18×6:radiusPill 与 circular(3) 渲染逐字节相同', (tester) async {
    final Uint8List pill = await pixelsOf(
      tester,
      size: const Size(18, 6),
      radius: tokens.radiusPill,
    );
    final Uint8List half = await pixelsOf(
      tester,
      size: const Size(18, 6),
      radius: 3,
    );
    expect(listEquals(pill, half), isTrue);
  });

  testWidgets('录制进度条 4px:radiusPill 与 circular(2) 渲染逐字节相同', (tester) async {
    final Uint8List pill = await pixelsOf(
      tester,
      size: const Size(60, 4),
      radius: tokens.radiusPill,
    );
    final Uint8List half = await pixelsOf(
      tester,
      size: const Size(60, 4),
      radius: 2,
    );
    expect(listEquals(pill, half), isTrue);
  });

  testWidgets('反例:同尺寸下 radiusPill 与 circular(1) 必须不同', (tester) async {
    final Uint8List pill = await pixelsOf(
      tester,
      size: const Size(6, 6),
      radius: tokens.radiusPill,
    );
    final Uint8List sharp = await pixelsOf(
      tester,
      size: const Size(6, 6),
      radius: 1,
    );
    expect(listEquals(pill, sharp), isFalse);
  });

  testWidgets('反例:4px 进度条下 radiusPill 与 circular(1) 必须不同', (tester) async {
    final Uint8List pill = await pixelsOf(
      tester,
      size: const Size(60, 4),
      radius: tokens.radiusPill,
    );
    final Uint8List sharp = await pixelsOf(
      tester,
      size: const Size(60, 4),
      radius: 1,
    );
    expect(listEquals(pill, sharp), isFalse);
  });
}
