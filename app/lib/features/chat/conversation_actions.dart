import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_exception.dart';
import '../../core/widgets/app_action_sheet.dart';
import '../../core/widgets/app_dialog.dart';
import '../../core/widgets/app_toast.dart';
import '../../im/im_client.dart';
import 'conversations_controller.dart';

/// imserver 的「会话不存在」业务码:未配对 / 从没聊过 / 已删除(§19.8)。
const _conversationGoneCode = 40401;

/// imserver 的写路径限流码(令牌桶 1/s、突发 20,§19.7)。
const _tooFrequentCode = 42901;

/// 会话行长按操作面板(批次 N):置顶 / 免打扰 / 删除会话。
///
/// 三个动作全部是**单方**行为:只改自己这一行,对端看不到,也不产生任何消息。
/// 置顶 / 免打扰走 imserver HTTP(不加 WS 帧),删除走既有的
/// [ImClient.deleteConversation](WS 帧早已存在,本单只补长按入口)。
///
/// Args:
///   context: 会话列表所在页面的 BuildContext(面板、确认框、Toast 都挂在它上面)。
///   ref: 用于取会话列表控制器。
///   conversation: 被长按的那一行。
Future<void> showConversationActions(
  BuildContext context,
  WidgetRef ref,
  ImConversation conversation,
) async {
  final pinned = conversation.pinned;
  final muted = conversation.muted;
  final action = await showAppActionSheet(
    context,
    title: conversation.showName,
    actions: [
      AppActionSheetAction(
        id: 'pin',
        label: pinned ? '取消置顶' : '置顶',
        icon: Icons.push_pin_rounded,
      ),
      AppActionSheetAction(
        id: 'mute',
        label: muted ? '取消免打扰' : '免打扰',
        icon: muted ? Icons.notifications_off_rounded : Icons.notifications_rounded,
      ),
      const AppActionSheetAction(
        id: 'delete',
        label: '删除会话',
        icon: Icons.delete_rounded,
        danger: true,
      ),
    ],
  );
  if (action == null || !context.mounted) return;

  switch (action) {
    case 'pin':
      await _setFlags(
        context,
        ref,
        conversation.peerId,
        pinned: !pinned,
        doneMessage: pinned ? '已取消置顶' : '已置顶',
      );
    case 'mute':
      await _setFlags(
        context,
        ref,
        conversation.peerId,
        muted: !muted,
        doneMessage: muted ? '已取消免打扰' : '已开启免打扰',
      );
    case 'delete':
      await _delete(context, ref, conversation.peerId);
  }
}

/// 写一个开关,并按结果给提示。
///
/// **失败保留原状态**:标志位只在服务端回读成功后才落进模型(见
/// `ConversationsController.setFlags`),所以失败时列表不会出现「以为置顶了」的假象。
///
/// Args:
///   context: 页面上下文(提示与刷新都用它)。
///   ref: 会话列表控制器入口。
///   peerId: 会话对端 IM id。
///   pinned: 置顶开关;null = 不改这一项。
///   muted: 免打扰开关;null = 不改这一项。
///   doneMessage: 写成功后的提示文案。
Future<void> _setFlags(
  BuildContext context,
  WidgetRef ref,
  String peerId, {
  bool? pinned,
  bool? muted,
  required String doneMessage,
}) async {
  try {
    await ref
        .read(conversationsProvider.notifier)
        .setFlags(peerId, pinned: pinned, muted: muted);
    if (context.mounted) AppToast.show(context, doneMessage);
  } catch (error) {
    if (!context.mounted) return;
    if (_codeOf(error) == _conversationGoneCode) {
      // 会话已经被删掉(另一台设备删了 / 解除了配对):提示 + 把列表拉回真实状态。
      AppToast.show(context, '该会话已不存在');
      unawaited(ref.read(conversationsProvider.notifier).reload());
      return;
    }
    AppToast.show(context, _textOf(error));
  }
}

/// 删除会话:二次确认 → 既有 `deleteConversation` → 行从列表移除。
///
/// Args:
///   context: 页面上下文。
///   ref: 会话列表控制器入口。
///   peerId: 会话对端 IM id。
Future<void> _delete(BuildContext context, WidgetRef ref, String peerId) async {
  final confirmed = await showConfirmDialog(
    context,
    title: '删除该会话?',
    message: '聊天记录会从你的列表里移除,对方不受影响。',
    confirmLabel: '删除',
    confirmKey: const Key('chats.delete.confirm'),
    danger: true,
  );
  if (!confirmed || !context.mounted) return;
  try {
    await ref.read(conversationsProvider.notifier).deleteConversation(peerId);
    if (context.mounted) AppToast.show(context, '会话已删除');
  } catch (error) {
    if (context.mounted) AppToast.show(context, _textOf(error));
  }
}

/// 取业务码:IM 侧错误与 HTTP 侧错误都认(imserver 的 HTTP 错误已翻成 [ApiException])。
int? _codeOf(Object error) => switch (error) {
      ImException(:final code) => code,
      ApiException(:final code) => code,
      _ => null,
    };

/// 限流判定:业务码 `42901` 或 HTTP 429(imserver 也可能只给状态码)。
bool _isTooFrequent(Object error) =>
    _codeOf(error) == _tooFrequentCode ||
    (error is ApiException && error.statusCode == 429);

/// 统一的提示文案:限流单独说,其余取后端中文 message。
String _textOf(Object error) {
  if (_isTooFrequent(error)) return '操作太频繁了,歇一下再试';
  if (error is ImException) return error.message;
  return apiMessageOf(error);
}
