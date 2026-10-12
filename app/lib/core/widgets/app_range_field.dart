import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_gradients.dart';
import '../theme/app_typography.dart';

/// 「心跳」§7 区间选择:标题 + 双滑块。
/// 选中轨道用 `gradientHeart` 着色(§7「选中:填充样式 + gradientHeart 着色」),
/// 由 [_GradientRangeTrackShape] 自绘;未选段 `divider`;滑块白底圆 + 卡片阴影。
class AppRangeField extends StatelessWidget {
  const AppRangeField({
    super.key,
    required this.title,
    required this.values,
    required this.min,
    required this.max,
    this.divisions,
    required this.onChanged,
  });

  final String title;
  final RangeValues values;
  final double min;
  final double max;
  final int? divisions;
  final ValueChanged<RangeValues> onChanged;

  static const trackHeight = 4.0;
  static const thumbRadius = 12.0;

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: AppText.subtitle.copyWith(color: AppColors.text1)),
          SliderTheme(
            data: SliderTheme.of(context).copyWith(
              trackHeight: trackHeight,
              activeTrackColor: AppColors.brand, // 自定义 track shape 会盖掉它
              inactiveTrackColor: AppColors.divider,
              thumbColor: AppColors.bgCard,
              overlayColor: AppColors.brand.withValues(alpha: .12),
              rangeTrackShape: const _GradientRangeTrackShape(),
              rangeThumbShape: const RoundRangeSliderThumbShape(
                enabledThumbRadius: thumbRadius,
                elevation: 2,
                pressedElevation: 4,
              ),
            ),
            child: RangeSlider(
              values: values,
              min: min,
              max: max,
              divisions: divisions,
              labels: RangeLabels(
                values.start.round().toString(),
                values.end.round().toString(),
              ),
              onChanged: onChanged,
            ),
          ),
        ],
      );
}

/// 选中段画 `gradientHeart`,未选段画 `divider`。
class _GradientRangeTrackShape extends RangeSliderTrackShape
    with BaseRangeSliderTrackShape {
  const _GradientRangeTrackShape();

  @override
  bool get isRounded => true;

  @override
  void paint(
    PaintingContext context,
    Offset offset, {
    required RenderBox parentBox,
    required SliderThemeData sliderTheme,
    required Animation<double> enableAnimation,
    required Offset startThumbCenter,
    required Offset endThumbCenter,
    bool isEnabled = false,
    bool isDiscrete = false,
    required TextDirection textDirection,
  }) {
    final rect = getPreferredRect(
      parentBox: parentBox,
      offset: offset,
      sliderTheme: sliderTheme,
      isEnabled: isEnabled,
      isDiscrete: isDiscrete,
    );
    if (rect.isEmpty) return;

    final radius = Radius.circular(rect.height / 2);
    final canvas = context.canvas;
    canvas.drawRRect(
      RRect.fromRectAndRadius(rect, radius),
      Paint()..color = sliderTheme.inactiveTrackColor ?? AppColors.divider,
    );

    final left = startThumbCenter.dx < endThumbCenter.dx
        ? startThumbCenter.dx
        : endThumbCenter.dx;
    final right = startThumbCenter.dx < endThumbCenter.dx
        ? endThumbCenter.dx
        : startThumbCenter.dx;
    final active = Rect.fromLTRB(left, rect.top, right, rect.bottom);
    if (active.isEmpty) return;
    canvas.drawRRect(
      RRect.fromRectAndRadius(active, radius),
      Paint()..shader = AppGradients.heart.createShader(active),
    );
  }
}
