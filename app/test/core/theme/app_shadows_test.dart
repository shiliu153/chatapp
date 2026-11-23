import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_shadows.dart';
import 'package:chatapp_app/core/theme/tokens.g.dart' as tokens;

void main() {
  test('elevation.1 / elevation.2 解析成暖色阴影(不是心跳期的冷灰)', () {
    final card = AppShadows.parse(tokens.elevation1);
    expect(card.offset, const Offset(0, 2));
    expect(card.blurRadius, 8);
    // rgba(28,23,20,.06):暖色 + 6% 透明度
    expect(card.color, const Color.fromRGBO(28, 23, 20, 0.06));

    final floating = AppShadows.parse(tokens.elevation2);
    expect(floating.offset, const Offset(0, 10));
    expect(floating.blurRadius, 24);
    expect(floating.color, const Color.fromRGBO(28, 23, 20, 0.10));
  });

  test('负偏移与整数透明度也能解析(生成器换格式时不至于静默错位)', () {
    final shadow = AppShadows.parse('-2px 4px 12px rgba(1, 2, 3, 1)');
    expect(shadow.offset, const Offset(-2, 4));
    expect(shadow.blurRadius, 12);
    expect(shadow.color, const Color.fromRGBO(1, 2, 3, 1));
  });

  test('解析失败直接抛 StateError(不静默回退成「没有阴影」)', () {
    expect(() => AppShadows.parse('#EDE6DF'), throwsStateError);
    expect(() => AppShadows.parse('0 2px 8px #000'), throwsStateError);
  });

  test('主按钮光晕取 brand @12%(§18.6),零位移', () {
    const brand = Color(0xFFC93C22);
    final glow = AppShadows.primaryGlow(brand).single;
    expect(glow.offset, Offset.zero);
    expect(glow.color.a, closeTo(0.12, 0.001));
    expect(glow.color.r, closeTo(brand.r, 0.001));
  });
}
