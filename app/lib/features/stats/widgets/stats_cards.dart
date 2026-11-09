import 'package:flutter/material.dart';

import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/theme/heart_theme_context.dart';
import '../../../core/widgets/app_card.dart';
import '../models.dart';

/// 七张数字卡的键与中文标签:顺序即展示顺序,与 `docs/api/stats.md` §1.1 的七项一一对应。
///
/// 骨架屏按同一个列表摆占位,所以卡片增删只改这一处。
const statsCardSpecs = <({String key, String label})>[
  (key: 'matches', label: '新的配对'),
  (key: 'likes_given', label: '喜欢给出'),
  (key: 'likes_received', label: '喜欢收到'),
  (key: 'visits', label: '访客'),
  (key: 'posts', label: '动态'),
  (key: 'post_likes', label: '动态获赞'),
  (key: 'new_followers', label: '新粉丝'),
];

/// 取某张卡对应的数字。
///
/// 键是给排版/测试用的稳定标识;`switch` 末尾的兜底分支只为「后端将来多回一项、
/// 前端列表被误加一行」时不崩,正常路径永远命中上面七条之一。
int statsValue(StatsReport report, String key) => switch (key) {
      'matches' => report.matches,
      'likes_given' => report.likesGiven,
      'likes_received' => report.likesReceived,
      'visits' => report.visits,
      'posts' => report.posts,
      'post_likes' => report.postLikes,
      'new_followers' => report.newFollowers,
      _ => 0,
    };

/// 七张数字卡:两列排布、卡间 12(§5.1),奇数张时最后一行只占左列。
///
/// 不用 `GridView`:它要求固定宽高比,而卡高由字阶决定,在窄屏上很容易撑出
/// 一次 `RenderFlex overflow`;两列 `Row` + `Expanded` 的高度自适应内容,不会溢出。
class StatsCards extends StatelessWidget {
  const StatsCards({super.key, required this.report});

  final StatsReport report;

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (var i = 0; i < statsCardSpecs.length; i += 2) ...[
            if (i > 0) const SizedBox(height: AppSpacing.cardGap),
            // IntrinsicHeight + stretch:同一行的两张卡等高(标签换行时不会一高一矮)。
            // 不能用不带 IntrinsicHeight 的 stretch —— 纵向约束是无界的,会直接断言失败。
            IntrinsicHeight(
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Expanded(child: _NumberCard(spec: statsCardSpecs[i], report: report)),
                  const SizedBox(width: AppSpacing.cardGap),
                  Expanded(
                    child: i + 1 < statsCardSpecs.length
                        ? _NumberCard(spec: statsCardSpecs[i + 1], report: report)
                        : const SizedBox.shrink(),
                  ),
                ],
              ),
            ),
          ],
        ],
      );
}

/// 一张数字卡:数字(display 32/w800)+ 中文标签(caption/text2)。
///
/// `0` 正常显示 `0`:新用户或某周确实没发生的事就是 0,不做「—」之类的替换。
class _NumberCard extends StatelessWidget {
  const _NumberCard({required this.spec, required this.report});

  final ({String key, String label}) spec;
  final StatsReport report;

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    return AppCard(
      key: Key('stats.card.${spec.key}'),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '${statsValue(report, spec.key)}',
            key: Key('stats.value.${spec.key}'),
            style: AppText.display.copyWith(color: colors.text1),
          ),
          const SizedBox(height: AppSpacing.xs),
          Text(spec.label, style: AppText.caption.copyWith(color: colors.text2)),
        ],
      ),
    );
  }
}
