import 'dart:io';

import 'package:flutter/material.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../../core/format.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/theme/ember_colors.dart';
import '../../../core/theme/ember_theme_context.dart';
import '../../../core/theme/tokens.g.dart' as tokens;
import '../../../core/ui/ember_ui.dart';
import '../../../core/widgets/avatar_hero.dart';
import '../../../core/widgets/app_spinner.dart';
import '../../../im/im_client.dart';
import '../../../im/voice_transcode.dart';
import '../stickers.dart';
import 'voice_bubble.dart';

/// 单条消息(「余烬 Ember」§8.3 气泡行 / E-5.3 page spec §3)。
///
/// 与心跳期(附录 B.3)的差别只有取值,结构不变:
/// - 圆角 18 → **16**(`radius.md`),靠头像侧上角 6;最大宽 72%;内边距 12/16;
/// - 自己 `brand.default` 实底 + `brand.on` 字;对方 `surface.card` + `text.primary`
///   (深色下再补 1px `border.divider` 分层 —— §5.3「深色不用阴影」);
/// - 头像 [EmberAvatar] 40;发送中在气泡右下角出 12 转圈;**失败不静默丢弃**:
///   左侧 `status.danger` 感叹号,点它重发;
/// - 读屏一句话(§8.4):「我 / 对方，内容，时间，发送状态」。
class MessageBubble extends StatelessWidget {
  /// 构造气泡。
  const MessageBubble({
    super.key,
    required this.message,
    this.peerName,
    this.peerAvatarUrl,
    this.selfAvatarUrl,
    this.onLongPress,
    this.onRetry,
    this.onTapImage,
    this.onTapQuote,
    this.onToggleSelect,
    this.onTapAvatar,
    this.avatarHeroTag,
    this.selectable = false,
    this.selected = false,
    this.selectionMode = false,
    this.highlight = false,
    this.isRead = false,
    this.readReceiptEnabled = false,
  });

  /// 这条消息。
  final ChatMessage message;

  /// 对端昵称(头像首字与引用署名都用它)。
  final String? peerName;

  /// 对端头像地址。
  final String? peerAvatarUrl;

  /// 自己的头像地址。
  final String? selfAvatarUrl;

  /// 长按(弹操作菜单)。
  final VoidCallback? onLongPress;

  /// 重发(发送失败 / 语音转码失败都走这里)。
  final VoidCallback? onRetry;

  /// 点图片气泡(全屏看图)。
  final VoidCallback? onTapImage;

  /// 点了气泡上方的引用块:跳到被引用的原消息(批次 L-2)。
  final VoidCallback? onTapQuote;

  /// 多选模式下点气泡本体:切换这条的选中状态(批次 T-2)。
  final VoidCallback? onToggleSelect;

  /// 点对端头像 → 对方资料页(E-5.4 page spec §3「对话页气泡头像 → 资料页」)。
  ///
  /// 自己的头像不给点:资料页的「我的」入口在底栏,从自己头像点过去等于绕路。
  final VoidCallback? onTapAvatar;

  /// 对端头像的 Hero tag(与资料页头图同名即飞)。
  ///
  /// **每条消息一个 tag**(`avatar-msg-<msgId>`):同一个人在同一屏会出现多次,
  /// 同一 tag 出现两次会让 Hero 直接抛「multiple heroes share the same tag」。
  final String? avatarHeroTag;

  /// 这条消息**能不能**被多选。已撤回 / 发送中 / 居中灰条都不给勾 ——
  /// 前两者删了没有意义(已撤回本来就不显示内容),灰条没有气泡本体可点。
  final bool selectable;

  /// 多选模式下这条是否已选中。
  final bool selected;

  /// 是否处于多选模式:为真时点本体=切换选中、长按菜单/点图/点引用**全部失效**,
  /// 语音气泡也不播(整块内容 IgnorePointer),免得「想勾选却点开了播放器」。
  final bool selectionMode;

  /// 搜索定位命中的气泡:主色淡底高亮 1.5s 后由外层取消。
  final bool highlight;

  /// 对端已读这条(我方消息才有意义;由 `chatPeerReadSeqProvider` 与 `seq` 比较得出)。
  final bool isRead;

  /// 是否支持已读回执(不支持时宁可不显示,也不要假状态)。
  final bool readReceiptEnabled;

  /// 居中灰条里「互相喜欢」的兜底文案。
  static const noticeFallback = '你们已互相喜欢,开始聊天吧';

  /// 搜索定位命中时的高亮淡入时长。
  ///
  /// 这是**纯透明度过渡**(无位移),不属于 §7.1 的四条 spring 位移档;规范只给了
  /// 「120ms 减弱动态效果」这一个时长值,300ms 沿用既有手感并单点声明在这里。
  static const _highlightFade = Duration(milliseconds: 300);

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    if (message.isRevoked) {
      return Padding(
        key: const Key('chat.revoked'),
        padding: EdgeInsets.symmetric(vertical: tokens.space8),
        child: Center(
          child: Text(
            message.isSelf ? '你撤回了一条消息' : '对方撤回了一条消息',
            style: AppText.caption.copyWith(color: colors.textTertiary),
          ),
        ),
      );
    }
    if (message.kind != ChatMessageKind.text &&
        message.kind != ChatMessageKind.image &&
        message.kind != ChatMessageKind.voice &&
        message.kind != ChatMessageKind.sticker) {
      final label = switch (message.kind) {
        ChatMessageKind.matchNotice => message.text.isEmpty ? noticeFallback : message.text,
        ChatMessageKind.banNotice => message.text.isEmpty ? '系统通知' : message.text,
        _ => '[暂不支持的消息]',
      };
      return Padding(
        key: const Key('chat.notice'),
        padding: EdgeInsets.symmetric(vertical: tokens.space8),
        child: Center(
          child: Container(
            padding: EdgeInsets.symmetric(
              horizontal: tokens.space12,
              vertical: tokens.space4,
            ),
            decoration: BoxDecoration(
              // 居中灰条是「系统口吻」,取凹陷面而不是卡片面(§8.3 次级容器)。
              color: colors.surfaceSunken,
              borderRadius: BorderRadius.circular(tokens.radiusPill),
            ),
            child: Text(
              label,
              textAlign: TextAlign.center,
              style: AppText.micro.copyWith(color: colors.textSecondary),
            ),
          ),
        ),
      );
    }

    final isSelf = message.isSelf;
    final avatar = _avatar(isSelf);
    final tappable = selectionMode && selectable;
    final bubble = GestureDetector(
      // 气泡本体的稳定 key:测试与 integration_test 用它点「这一条」,
      // 而不是点里面的文字 —— 多选模式下文字在被 IgnorePointer 挡住的子树里。
      key: Key('chat.bubble:${message.msgId}'),
      // 多选模式下长按菜单一律失效:此刻唯一动作是「勾选/取消勾选」,
      // 再弹菜单会让手指一抖就变成引用或撤回。
      onLongPress: selectionMode ? null : onLongPress,
      onTap: tappable ? onToggleSelect : null,
      // 只有「可勾」的气泡才整块吃事件;其它情况保持原样(deferToChild),
      // 免得把气泡外的空白也变成点击区。
      behavior: tappable ? HitTestBehavior.opaque : HitTestBehavior.deferToChild,
      // 多选模式下内容整块不吃指针:语音气泡、图片、引用块自己的 onTap 全部让位给
      // 外层的「切换选中」,否则「想勾选却点开了播放器 / 全屏大图」。
      child: IgnorePointer(
        ignoring: selectionMode,
        child: Opacity(
          opacity: message.isPending ? 0.6 : 1,
          child: ConstrainedBox(
            // 最大宽 72%(§8.3 气泡行)。
            constraints:
                BoxConstraints(maxWidth: MediaQuery.sizeOf(context).width * 0.72),
            // 引用块在气泡**上方**(批次 L-2):它是「我在回应什么」,不该抢正文的视线。
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment:
                  isSelf ? CrossAxisAlignment.end : CrossAxisAlignment.start,
              children: [
                if (message.ref != null) _quoteBlock(context, message.ref!),
                _bubbleContent(context),
              ],
            ),
          ),
        ),
      ),
    );

    return AnimatedContainer(
      // 搜索定位命中时整个消息行淡入主色底,1.5s 后由外层把 highlight 置回 false
      key: highlight ? Key('chat.highlight:${message.msgId}') : null,
      duration: _highlightFade,
      decoration: BoxDecoration(
        color: highlight
            ? colors.brandDefault.withValues(alpha: 0.08)
            : Colors.transparent,
        borderRadius: BorderRadius.circular(tokens.radiusMd),
      ),
      child: Padding(
        padding: EdgeInsets.symmetric(
          horizontal: tokens.space12,
          vertical: tokens.space4,
        ),
        child: Row(
          mainAxisAlignment: isSelf ? MainAxisAlignment.end : MainAxisAlignment.start,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 勾选圈与左右无关,一律在最左边(微信口径):多选时视线从左边扫下来
            // 对齐的是勾,不是头像。
            if (selectionMode && selectable) ...[
              _selectMark(colors),
              SizedBox(width: tokens.space8),
            ],
            if (!isSelf) ...[avatar, SizedBox(width: tokens.space8)],
            // 发送失败:左侧 `status.danger` 感叹号,点它重发(§8.3 气泡 error 行)。
            if (isSelf && message.isFailed)
              Padding(
                padding: EdgeInsets.only(right: tokens.space4),
                child: EmberPressable(
                  key: const Key('chat.retry'),
                  onTap: onRetry,
                  pressedScale: 0.97,
                  borderRadius: BorderRadius.circular(tokens.radiusPill),
                  semanticLabel: '发送失败，点按重发',
                  builder: (context, state) => SizedBox(
                    width: tokens.sizeTouchWeb,
                    height: tokens.sizeTouchWeb,
                    child: Icon(
                      PhosphorIconsFill.warningCircle,
                      size: tokens.sizeIcon20,
                      color: colors.statusDanger,
                    ),
                  ),
                ),
              ),
            if (isSelf && message.isTranscoding)
              Padding(
                padding: EdgeInsets.only(right: tokens.space4),
                child: Text(
                  voiceTranscodePendingText,
                  key: const Key('chat.status.transcoding'),
                  style: AppText.micro.copyWith(color: colors.textTertiary),
                ),
              ),
            if (isSelf && _readLabel() != null)
              Padding(
                padding: EdgeInsets.only(right: tokens.space4),
                child: Text(
                  _readLabel()!,
                  key: const Key('chat.status.read'),
                  style: AppText.micro.copyWith(color: colors.textTertiary),
                ),
              ),
            // 读屏一句话(§8.4):方向 + 内容 + 时间 + 发送状态。
            // 用 `excludeSemantics` 是为了**只念这一句**,不让里面的正文再念一遍;
            // 头像与重发按钮留在外面,各自带自己的语义。
            Semantics(
              container: true,
              label: _semanticLabel(),
              excludeSemantics: true,
              child: bubble,
            ),
            if (isSelf) ...[SizedBox(width: tokens.space8), avatar],
          ],
        ),
      ),
    );
  }

  /// 头像:对端头像可点(进资料页)且参与 Hero,自己头像只展示。
  ///
  /// 多选模式下不给点:此刻唯一动作是「勾选 / 取消勾选」,点头像跳页会让想勾选的
  /// 手指跑到别的页面去(与气泡本体同一条纪律)。
  Widget _avatar(bool isSelf) {
    final avatar = EmberAvatar(
      image: _avatarProvider(isSelf ? selfAvatarUrl : peerAvatarUrl),
      size: EmberComponentSizes.avatarMd,
      name: isSelf ? '我' : (peerName ?? ''),
    );
    final onTap = onTapAvatar;
    if (isSelf || selectionMode || onTap == null) return avatar;
    return EmberPressable(
      // 稳定 key:测试与 integration_test 按「哪条消息的头像」定点点击
      key: Key('chat.avatar:${message.msgId}'),
      onTap: onTap,
      pressedScale: 0.97,
      borderRadius: BorderRadius.circular(tokens.radiusPill),
      semanticLabel: '${peerName ?? '对方'}的头像，查看资料',
      builder: (context, state) => AvatarHero(
        tag: avatarHeroTag,
        imageUrl: peerAvatarUrl,
        fromRadius: tokens.radiusPill,
        child: avatar,
      ),
    );
  }

  /// 头像图:地址为空或非法时返回 `null`,由 [EmberAvatar] 回落到首字。
  ///
  /// Args:
  ///   url: 头像地址(可能为 null / 空串)。
  ///
  /// Returns:
  ///   `NetworkImage` 或 null。
  ImageProvider? _avatarProvider(String? url) =>
      (url == null || url.isEmpty) ? null : NetworkImage(url);

  /// 多选态的勾选圈(批次 T-2)。
  ///
  /// 选中 = 主色实心圆:这正是主色该出现的「视线锚点」(§2),未选 = `text.tertiary`
  /// 空心。key 挂在圈上,测试按 `chat.select:<msgId>` 断言某一行的勾选态。
  ///
  /// Args:
  ///   colors: 「余烬 Ember」色板(浅 / 深两套)。
  Widget _selectMark(EmberColors colors) => Icon(
        selected ? PhosphorIconsFill.checkCircle : PhosphorIconsRegular.circle,
        key: Key('chat.select:${message.msgId}'),
        size: tokens.sizeIcon24,
        color: selected ? colors.brandDefault : colors.textTertiary,
      );

  /// 我方消息的「已读」标记(其它情况返回 null)。
  ///
  /// 口径(微信):
  /// - 失败不写字 —— 左侧已有 `status.danger` 感叹号,再写字是重复;
  /// - **未读不写字** —— 一屏十几条都挂「未读」是纯噪声,「有没有『已读』」本身就是
  ///   未读的信号;
  /// - 不支持已读回执 / 发送中 / 转码中一律不显示,不给假状态。
  String? _readLabel() {
    if (!message.isSelf) return null;
    if (message.isPending || message.isTranscoding || message.isFailed) return null;
    if (!readReceiptEnabled || message.isRevoked) return null;
    return isRead ? '已读' : null;
  }

  /// 读屏播报用的内容文案(图片 / 语音 / 贴纸给词,不念 URL)。
  String _semanticContent() => switch (message.kind) {
        ChatMessageKind.text => message.text,
        ChatMessageKind.image => '图片',
        ChatMessageKind.voice => '语音 ${(message.voiceDurationMs / 1000).round()} 秒',
        ChatMessageKind.sticker => '贴纸',
        _ => message.text,
      };

  /// 读屏播报用的发送状态(§8.4「方向 + 内容 + 时间 + 发送状态」)。
  ///
  /// 对端消息没有发送状态可言(它已经在我这儿了),所以这一段只在我方消息上出现。
  String? _semanticStatus() {
    if (!message.isSelf) return null;
    if (message.isTranscoding) return voiceTranscodePendingText;
    if (message.isPending) return '发送中';
    if (message.isFailed) return '发送失败，点按重发';
    if (readReceiptEnabled && message.seq > 0) return isRead ? '已读' : '已送达';
    return '已发送';
  }

  /// 拼成一句话:方向，内容，时间，状态(缺的段直接不出现,不念「无」)。
  String _semanticLabel() => [
        message.isSelf ? '我' : '对方',
        _semanticContent(),
        formatMessageTime(
          DateTime.fromMillisecondsSinceEpoch(message.timestamp),
        ),
        ?_semanticStatus(),
      ].join('，');

  /// 气泡上方的引用块(批次 L-2)。
  ///
  /// 摘要来自**服务端快照**(`ref.text`):文本前 120 字,图片 / 语音 / 贴纸是
  /// `[图片]` / `[语音]` / `[贴纸]`;`revoked` 时只显示「消息已撤回」,不显示原文。
  ///
  /// 视觉按 §8.3 次级容器:`surface.sunken` 底 + `radius.sm` + 左侧 2px `brand.default` 竖线。
  ///
  /// Args:
  ///   context: 构建上下文(取「余烬 Ember」色板)。
  ///   ref: 服务端生成的引用快照。
  ///
  /// Returns:
  ///   可点击的引用块(点击跳回原消息)。
  Widget _quoteBlock(BuildContext context, QuoteRef ref) {
    final colors = context.ember;
    // 一个会话只有两个人:引用块的署名不是对端就是我自己。
    final sender = ref.from == message.peerId ? (peerName ?? '对方') : '我';
    return ClipRRect(
      borderRadius: BorderRadius.circular(tokens.radiusSm),
      child: GestureDetector(
        key: Key('chat.quote:${message.msgId}'),
        behavior: HitTestBehavior.opaque,
        onTap: onTapQuote,
        child: Container(
          margin: EdgeInsets.only(bottom: tokens.space4),
          padding: EdgeInsets.symmetric(
            horizontal: tokens.space8,
            vertical: tokens.space4,
          ),
          decoration: BoxDecoration(
            color: colors.surfaceSunken,
            // §8.3 引用条:左侧 2px `brand.default` 竖线。
            border: Border(
              left: BorderSide(color: colors.brandDefault, width: 2),
            ),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                sender,
                style: AppText.micro.copyWith(color: colors.brandDefault),
              ),
              Text(
                ref.displayText,
                key: ref.revoked ? const Key('chat.quote.revoked') : null,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: AppText.micro.copyWith(color: colors.textSecondary),
              ),
            ],
          ),
        ),
      ),
    );
  }

  /// 气泡本体:按消息类型分派。
  Widget _bubbleContent(BuildContext context) {
    final colors = context.ember;
    if (message.kind == ChatMessageKind.voice) {
      // 转码中(M-3):还没有可播放地址,气泡先显示「转圈 + 处理中」,
      // 别拿本地文件先播 —— 用户会以为已经发出去了。
      if (message.isTranscoding) return _voiceTranscoding(colors);
      return MessageBubble._withPendingSpin(colors, message, VoiceBubble(message: message));
    }
    if (message.kind == ChatMessageKind.sticker) {
      return _sticker(colors);
    }
    if (message.kind == ChatMessageKind.image) {
      return GestureDetector(
        key: const Key('chat.image'),
        onTap: onTapImage,
        child: ClipRRect(
          borderRadius: BorderRadius.circular(tokens.radiusSm),
          child: SizedBox(width: 140, height: 140, child: _image(colors)),
        ),
      );
    }
    return MessageBubble._withPendingSpin(
      colors,
      message,
      _textBubble(context, colors),
    );
  }

  /// 文字气泡:自己 `brand.default` + `brand.on`;对方 `surface.card` + `text.primary`。
  ///
  /// 圆角 `radius.md`(16),**靠头像侧上角 6**(自己=右上、对方=左上);
  /// 深色下对方气泡补 1px `border.divider` —— 深色不用阴影(§5.3)。
  ///
  /// Args:
  ///   context: 取当前亮度(深色要描边分层)。
  ///   colors: 「余烬 Ember」色板。
  Widget _textBubble(BuildContext context, EmberColors colors) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final isSelf = message.isSelf;
    return Container(
      padding: EdgeInsets.symmetric(
        horizontal: tokens.space16,
        vertical: tokens.space12,
      ),
      decoration: BoxDecoration(
        color: isSelf ? colors.brandDefault : colors.surfaceCard,
        borderRadius: BorderRadius.only(
          topLeft: Radius.circular(isSelf ? tokens.radiusMd : 6),
          topRight: Radius.circular(isSelf ? 6 : tokens.radiusMd),
          bottomLeft: Radius.circular(tokens.radiusMd),
          bottomRight: Radius.circular(tokens.radiusMd),
        ),
        border: (!isSelf && isDark)
            ? Border.all(color: colors.borderDivider)
            : null,
      ),
      child: Text(
        message.text,
        style: AppText.body.copyWith(
          color: isSelf ? colors.brandOn : colors.textPrimary,
        ),
      ),
    );
  }

  /// 发送中:气泡右下角 12 转圈(§8.3 气泡 loading 行),不另外写字。
  ///
  /// 12 的圆点正好落在气泡内边距(16/12)之外的那一小块留白里,不会盖住文字。
  ///
  /// Args:
  ///   colors: 「余烬 Ember」色板。
  ///   message: 这条消息(取 `isPending` / `isSelf`)。
  ///   child: 气泡本体。
  static Widget _withPendingSpin(EmberColors colors, ChatMessage message, Widget child) {
    if (!message.isPending) return child;
    return Stack(
      children: [
        child,
        Positioned(
          right: tokens.space4,
          bottom: tokens.space4,
          child: SizedBox(
            width: tokens.space12,
            height: tokens.space12,
            child: CircularProgressIndicator(
              key: const Key('chat.status.pending'),
              strokeWidth: 1.5,
              color: message.isSelf ? colors.brandOn : colors.textTertiary,
            ),
          ),
        ),
      ],
    );
  }

  /// 语音「转码中」占位气泡(M-3):转圈 + 「处理中」,尺寸与语音气泡同高。
  ///
  /// 颜色口径:进行中状态走中性色(主色留给真正的高音);自己这边气泡底是
  /// `brand.default` 实底,所以内容用 `brand.on`,对端用 `text.tertiary`。
  ///
  /// Args:
  ///   colors: 「余烬 Ember」色板(浅 / 深两套)。
  Widget _voiceTranscoding(EmberColors colors) {
    final foreground = message.isSelf ? colors.brandOn : colors.textTertiary;
    return Container(
      key: const Key('chat.voice.transcoding'),
      width: 150,
      padding: EdgeInsets.symmetric(
        horizontal: tokens.space12,
        vertical: tokens.space8,
      ),
      decoration: BoxDecoration(
        color: message.isSelf ? colors.brandDefault : colors.surfaceCard,
        borderRadius: BorderRadius.circular(tokens.radiusMd),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          AppSpinner(size: tokens.sizeIcon16, color: foreground),
          SizedBox(width: tokens.space8),
          Text(
            voiceTranscodePendingText,
            style: AppText.micro.copyWith(color: foreground),
          ),
        ],
      ),
    );
  }

  /// 贴纸气泡(批次 J):**不画气泡底色**,只显示图片本身(贴纸自带描边与圆角)。
  ///
  /// 未知 id(老版本收到新贴纸)降级成 `[贴纸]` 文本 pill,不白屏、不抛异常。
  Widget _sticker(EmberColors colors) {
    final sticker = stickerById(message.stickerId);
    if (sticker == null) {
      return Container(
        key: const Key('chat.sticker.unknown'),
        padding: EdgeInsets.symmetric(
          horizontal: tokens.space16,
          vertical: tokens.space12,
        ),
        decoration: BoxDecoration(
          color: colors.surfaceSunken,
          borderRadius: BorderRadius.circular(tokens.radiusMd),
        ),
        child: Text(
          unknownStickerLabel,
          style: AppText.body.copyWith(color: colors.textSecondary),
        ),
      );
    }
    return Image.asset(
      sticker.assetPath,
      key: Key('chat.sticker.${sticker.id}'),
      width: 132,
      height: 132,
      fit: BoxFit.contain,
      errorBuilder: (context, error, stack) => Container(
        width: 132,
        height: 132,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: colors.surfaceSunken,
          borderRadius: BorderRadius.circular(tokens.radiusSm),
        ),
        child: Text(
          unknownStickerLabel,
          style: AppText.micro.copyWith(color: colors.textTertiary),
        ),
      ),
    );
  }

  /// 图片内容:本地文件优先(刚发出的图),其次远程地址,都失败给占位。
  ///
  /// Args:
  ///   colors: 「余烬 Ember」色板(errorBuilder 里取不到可靠的主题上下文)。
  Widget _image(EmberColors colors) {
    final path = message.localPath;
    if (path != null && path.isNotEmpty) {
      return Image.file(
        File(path),
        fit: BoxFit.cover,
        errorBuilder: (_, _, _) => _fallback(colors),
      );
    }
    final url = message.imageUrl;
    if (url != null && url.isNotEmpty) {
      return Image.network(
        url,
        fit: BoxFit.cover,
        errorBuilder: (_, _, _) => _fallback(colors),
      );
    }
    return _fallback(colors);
  }

  /// 图片占位:`surface.sunken` + 破损图标(禁用灰色 Material 图标,§6)。
  Widget _fallback(EmberColors colors) => Container(
        color: colors.surfaceSunken,
        child: Center(
          child: Icon(
            PhosphorIconsRegular.imageBroken,
            size: tokens.sizeIcon24,
            color: colors.textTertiary,
          ),
        ),
      );
}
