import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_colors.dart';
import 'package:chatapp_app/core/theme/app_gradients.dart';
import 'package:chatapp_app/core/theme/app_motion.dart';
import 'package:chatapp_app/core/theme/app_radius.dart';

void main() {
  test('色板与规则 §2.1 一致', () {
    expect(AppColors.brand, const Color(0xFFFF2C55));
    expect(AppColors.text1, const Color(0xFF16181D));
    expect(AppColors.bgPage, const Color(0xFFF6F7FB));
    expect(AppColors.divider, const Color(0xFFEEF0F4));
  });

  test('心跳渐变 135° 双色', () {
    expect(AppGradients.heart.colors, [AppColors.brand, AppColors.heartOrange]);
    expect(AppGradients.heart.begin, Alignment.topLeft);
    expect(AppGradients.heart.end, Alignment.bottomRight);
  });

  test('圆角与动效档位', () {
    expect(AppRadius.card, 20);
    expect(AppRadius.sheet, 24);
    expect(AppMotion.fast.inMilliseconds, 150);
    expect(AppMotion.medium.inMilliseconds, 320);
  });

  test('发现卡圆角与照片 scrim(附录 A)', () {
    expect(AppRadius.discoveryCard, 24);
    expect(AppColors.photoScrim, const Color(0xDE101114));
  });
}
