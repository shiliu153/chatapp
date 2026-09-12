import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_exception.dart';
import '../moderation/widgets/report_sheet.dart';
import 'feed_repository.dart';

/// 删除动态确认框(广场/详情/我的动态共用);用户确认返回 true。
Future<bool> confirmDeletePost(BuildContext context) async {
  final confirmed = await showDialog<bool>(
    context: context,
    builder: (context) => AlertDialog(
      title: const Text('删除这条动态?'),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('取消')),
        FilledButton(
          key: const Key('post.delete.confirm'),
          onPressed: () => Navigator.pop(context, true),
          child: const Text('删除'),
        ),
      ],
    ),
  );
  return confirmed == true;
}

/// 举报动态:复用举报用户的 ReportSheet(四类原因 + 补充说明)。
Future<void> reportPostFromSheet(BuildContext context, WidgetRef ref, int postId) async {
  final result = await showModalBottomSheet<({String type, String detail})>(
    context: context,
    isScrollControlled: true,
    builder: (context) => const ReportSheet(),
  );
  if (result == null || !context.mounted) return;
  final messenger = ScaffoldMessenger.of(context);
  void show(String message) {
    messenger
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  try {
    await ref
        .read(feedRepositoryProvider)
        .reportPost(postId, type: result.type, detail: result.detail);
    show('已收到举报,我们会尽快处理');
  } on ApiException catch (error) {
    show(error.message);
  }
}
