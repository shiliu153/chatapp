import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../core/api_exception.dart';
import '../../core/ui/ember_ui.dart';
import '../moderation/widgets/report_sheet.dart';
import 'feed_repository.dart';
import 'widgets/post_confirm_dialog.dart';

/// 删除动态确认框(广场 / 详情 / 我的动态 / 收藏共用);用户确认返回 true。
///
/// Ember 口径:破坏性确认走 Dialog,**必须带图标 + 明确动词**(规范 §9.3)——
/// 所以这里是「垃圾桶图标 + 删除」,不是「确定 / 取消」那对无信息量的词。
Future<bool> confirmDeletePost(BuildContext context) => showPostConfirmDialog(
      context,
      icon: PhosphorIconsRegular.trash,
      title: '删除这条动态?',
      message: '删除后不可恢复',
      confirmLabel: '删除',
      confirmKey: const Key('post.delete.confirm'),
      danger: true,
    );

/// 举报动态:复用举报用户的 ReportSheet(四类原因 + 补充说明)。
///
/// 为什么还是 sheet 而不是 Dialog:§9.3 把「单一字段编辑 / 筛选」划给底部 sheet,
/// 举报要选原因 + 填说明,属于选择型流程;E-5.5 §2 的「Dialog」指的是删除这类
/// 破坏性确认。这条取舍记在 PR 说明里。
Future<void> reportPostFromSheet(
    BuildContext context, WidgetRef ref, int postId) async {
  final result = await showModalBottomSheet<({String type, String detail})>(
    context: context,
    isScrollControlled: true,
    builder: (context) => const ReportSheet(),
  );
  if (result == null || !context.mounted) return;
  void show(String message) => EmberToast.show(context, message);

  try {
    await ref
        .read(feedRepositoryProvider)
        .reportPost(postId, type: result.type, detail: result.detail);
    show('已收到举报,我们会尽快处理');
  } on ApiException catch (error) {
    show(error.message);
  }
}
