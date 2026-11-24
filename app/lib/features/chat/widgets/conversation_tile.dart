import 'package:flutter/material.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../../core/theme/app_typography.dart';
import '../../../core/theme/ember_theme_context.dart';
import '../../../core/theme/tokens.g.dart' as tokens;
import '../../../core/ui/ember_ui.dart';

/// 会话列表的一行(E-5.3 page spec §3「会话行」)。
///
/// 为什么从 `chats_page.dart` 抽出来:它是本单 golden 的一格(明 / 暗 × default /
/// 未读 / 草稿 = 6 张),也是 §8.4 读屏口径「昵称，最后一条，时间，N 条未读」的落点;
/// 抽成独立组件后 golden 只需要喂数据,不必把整个列表页(横滑条 / 置顶分组 / 骨架)
/// 也拖进截图。
///
/// 取值逐格对齐 spec:
/// - 行高 72(§5.2「列表行高 68–76」),水平内边距 20,底 `surface.page`,
///   按压 `surface.sunken`(列表行不用卡片阴影,§4);
/// - 头像 48([EmberAvatar],在线点 `status.success` 呼吸);
/// - 昵称 `subtitle` 17/w600,未读时 **w700**;摘要 `caption` 13 `text.secondary`,
///   草稿则前缀「[草稿] 」并转 `text.tertiary`;时间 `caption` 13 `text.tertiary`;
/// - 未读 [`EmberBadge`](≥100 显示「99+」);免打扰的未读改 **8px 灰点**。
class ConversationTile extends StatelessWidget {
  /// 构造会话行。
  const ConversationTile({
    super.key,
    required this.peerId,
    required this.name,
    required this.preview,
    this.avatarUrl,
    this.online = false,
    this.draft = false,
    this.timeLabel,
    this.unread = 0,
    this.muted = false,
    this.onTap,
    this.onLongPress,
  });

  /// 对端 IM id(如 `u9`):只用于给行内元素挂稳定 key,不参与显示。
  final String peerId;

  /// 昵称(已按 matches 缓存 → IM 资料 → 兜底 的降级链算好)。
  final String name;

  /// 摘要(最后一条消息的一句话预览,或草稿原文)。
  final String preview;

  /// 头像地址;`null` 时 [EmberAvatar] 回落到首字。
  final String? avatarUrl;

  /// 是否在线(在线点 + 读屏「在线」)。
  final bool online;

  /// 摘要是否来自**草稿**(批次 T-2):为真时加「[草稿] 」前缀并转 `text.tertiary`。
  final bool draft;

  /// 时间文案(今天 HH:mm / 更早 MM-DD);`null` 表示没有消息、不显示。
  final String? timeLabel;

  /// 未读条数;`0` 不显示角标。
  final int unread;

  /// 是否免打扰:未读改显示灰点(不显示数字,避免「要立刻处理」的误解)。
  final bool muted;

  /// 点行(进聊天页)。
  final VoidCallback? onTap;

  /// 长按(置顶 / 免打扰 / 删除面板)。
  final VoidCallback? onLongPress;

  /// 摘要的显示文案。
  String get _previewText => draft ? '[草稿] $preview' : preview;

  /// 行高(token 里没有「列表行」这一档,§5.2 给了 68–76 的区间,取中值 72)。
  static const rowHeight = 72.0;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final image = (avatarUrl == null || avatarUrl!.isEmpty)
        ? null
        : NetworkImage(avatarUrl!);
    return Semantics(
      // §8.4 读屏口径:一行读作「昵称，最后一条，时间，N 条未读」。
      // 内部文字 / 角标 / 在线点都由这一句覆盖,所以整块 excludeSemantics,
      // 不让它们再念一遍(角标自己的「N 条未读」也已在句子里)。
      container: true,
      button: true,
      label: _semanticLabel(),
      excludeSemantics: true,
      child: EmberPressable(
        onTap: onTap,
        onLongPress: onLongPress,
        pressedScale: 0.98,
        builder: (context, state) => Container(
          height: rowHeight,
          color: state.pressed ? colors.surfaceSunken : Colors.transparent,
          padding: EdgeInsets.symmetric(horizontal: tokens.space20),
          child: Row(
            children: [
              EmberAvatar(
                image: image,
                size: EmberComponentSizes.avatarLg,
                name: name,
                online: online,
              ),
              SizedBox(width: tokens.space12),
              Expanded(
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Flexible(
                          child: Text(
                            name,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: AppText.subtitle.copyWith(
                              color: colors.textPrimary,
                              // 未读 = 昵称加粗(§4「昵称 w700 + EmberBadge」)。
                              fontWeight:
                                  unread > 0 ? FontWeight.w700 : FontWeight.w600,
                            ),
                          ),
                        ),
                        // 免打扰标记(批次 N):声音关掉了,用静音铃铛代替「有声音」的暗示。
                        // 未读另给灰点,两者各说一件事(§4「免打扰」那两行)。
                        if (muted) ...[
                          SizedBox(width: tokens.space4),
                          Icon(
                            PhosphorIconsRegular.bellSlash,
                            key: Key('chats.muted:$peerId'),
                            size: tokens.sizeIcon16,
                            color: colors.textTertiary,
                          ),
                        ],
                      ],
                    ),
                    SizedBox(height: tokens.space4),
                    Text(
                      _previewText,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppText.caption.copyWith(
                        // 草稿是「我还没发出去」,比对方的话更弱一级(§4)。
                        color: draft ? colors.textTertiary : colors.textSecondary,
                      ),
                    ),
                  ],
                ),
              ),
              SizedBox(width: tokens.space8),
              Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  if (timeLabel != null)
                    Text(
                      timeLabel!,
                      // `micro` 档不跟随系统字号缩放(§4.3),时间戳留给缩放更稳。
                      textScaler: TextScaler.noScaling,
                      style: AppText.micro.copyWith(color: colors.textTertiary),
                    ),
                  SizedBox(height: tokens.space4),
                  if (muted && unread > 0)
                    _MutedDot(key: Key('chats.mutedDot:$peerId'))
                  else
                    ExcludeSemantics(child: EmberBadge(count: unread)),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  /// 读屏播报:「昵称，最后一条，时间，N 条未读」(缺的段直接不出现)。
  String _semanticLabel() => [
        name,
        if (online) '在线',
        _previewText,
        ?timeLabel,
        if (unread > 0) '$unread 条未读',
      ].join('，');
}

/// 免打扰会话的未读灰点:直径 8(§5.3 小场景点同档),`text.tertiary` 实心圆。
class _MutedDot extends StatelessWidget {
  const _MutedDot({super.key});

  static const _diameter = 8.0;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return Container(
      width: _diameter,
      height: _diameter,
      decoration: BoxDecoration(color: colors.textTertiary, shape: BoxShape.circle),
    );
  }
}
