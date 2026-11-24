import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../core/api_exception.dart';
import '../../core/theme/app_typography.dart';
import '../../core/theme/ember_theme_context.dart';
import '../../core/theme/tokens.g.dart' as tokens;
import '../../core/ui/ember_ui.dart';
import '../../im/im_client.dart';
import 'conversations_controller.dart';
import 'widgets/chat_confirm_dialog.dart';

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
/// 形态按 §9.3「轻量选择 → 底部 sheet」改用 [EmberSheet](E-5.3 page spec §2),
/// 删除的二次确认换成带图标 + 明确动词的 [showChatConfirmDialog]。
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
  final action = await EmberSheet.show<String>(
    context,
    // 内容是不可滚的行列表,允许下拉关闭(与内容滚动不抢手势)。
    maxHeightRatio: 0.4,
    child: _ConversationActionSheet(
      title: conversation.showName ?? '',
      pinned: pinned,
      muted: muted,
    ),
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

/// 会话行长按面板的内容:三行操作(行 key 固定 `actionSheet.<id>`,测试按它定位)。
class _ConversationActionSheet extends StatelessWidget {
  const _ConversationActionSheet({
    required this.title,
    required this.pinned,
    required this.muted,
  });

  /// 会话昵称(显示在拖把下方,确认「改的是哪一行」)。
  final String title;

  /// 当前是否置顶(决定文案是「置顶」还是「取消置顶」)。
  final bool pinned;

  /// 当前是否免打扰。
  final bool muted;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: EdgeInsets.fromLTRB(
            tokens.space20,
            tokens.space4,
            tokens.space20,
            tokens.space12,
          ),
          child: Text(
            title,
            textAlign: TextAlign.center,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: AppText.caption.copyWith(color: colors.textSecondary),
          ),
        ),
        _row(
          context,
          id: 'pin',
          icon: pinned ? PhosphorIconsFill.pushPin : PhosphorIconsRegular.pushPin,
          label: pinned ? '取消置顶' : '置顶',
        ),
        _row(
          context,
          id: 'mute',
          icon: muted ? PhosphorIconsRegular.bellSlash : PhosphorIconsRegular.bell,
          label: muted ? '取消免打扰' : '免打扰',
        ),
        _row(
          context,
          id: 'delete',
          icon: PhosphorIconsRegular.trash,
          label: '删除会话',
          danger: true,
        ),
        SizedBox(height: tokens.space8),
      ],
    );
  }

  /// 一行操作:图标 20 + 文字 17/`text.primary`;危险操作整行取 `status.danger`。
  ///
  /// 热区取 `size.touch.app`(48):行高比 48 高,可点区域就是整行(§8.4)。
  Widget _row(
    BuildContext context, {
    required String id,
    required IconData icon,
    required String label,
    bool danger = false,
  }) {
    final colors = context.ember;
    final foreground = danger ? colors.statusDanger : colors.textPrimary;
    return EmberPressable(
      key: Key('actionSheet.$id'),
      onTap: () => Navigator.of(context).pop(id),
      pressedScale: 0.97,
      semanticLabel: label,
      builder: (context, state) => Container(
        constraints: const BoxConstraints(minHeight: tokens.sizeTouchApp),
        color: state.pressed ? colors.surfaceSunken : Colors.transparent,
        padding: EdgeInsets.symmetric(
          horizontal: tokens.space20,
          vertical: tokens.space12,
        ),
        child: Row(
          children: [
            Icon(icon, size: tokens.sizeIcon20, color: foreground),
            SizedBox(width: tokens.space12),
            Expanded(
              child: Text(
                label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: AppText.subtitle.copyWith(color: foreground),
              ),
            ),
          ],
        ),
      ),
    );
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
    if (context.mounted) EmberToast.show(context, doneMessage);
  } catch (error) {
    if (!context.mounted) return;
    if (_codeOf(error) == _conversationGoneCode) {
      // 会话已经被删掉(另一台设备删了 / 解除了配对):提示 + 把列表拉回真实状态。
      EmberToast.show(context, '该会话已不存在');
      unawaited(ref.read(conversationsProvider.notifier).reload());
      return;
    }
    EmberToast.show(context, _textOf(error));
  }
}

/// 删除会话:二次确认 → 既有 `deleteConversation` → 行从列表移除。
///
/// Args:
///   context: 页面上下文。
///   ref: 会话列表控制器入口。
///   peerId: 会话对端 IM id。
Future<void> _delete(BuildContext context, WidgetRef ref, String peerId) async {
  final confirmed = await showChatConfirmDialog(
    context,
    icon: PhosphorIconsRegular.trash,
    title: '删除该会话?',
    message: '聊天记录会从你的列表里移除,对方不受影响。',
    confirmLabel: '删除会话',
    confirmKey: const Key('chats.delete.confirm'),
    danger: true,
  );
  if (!confirmed || !context.mounted) return;
  try {
    await ref.read(conversationsProvider.notifier).deleteConversation(peerId);
    if (context.mounted) EmberToast.show(context, '会话已删除');
  } catch (error) {
    if (context.mounted) EmberToast.show(context, _textOf(error));
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
