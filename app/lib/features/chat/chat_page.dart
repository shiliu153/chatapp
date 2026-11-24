import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../core/api_exception.dart';
import '../../core/image_pick.dart';
import '../../core/theme/app_typography.dart';
import '../../core/theme/ember_motion.dart';
import '../../core/theme/ember_theme_context.dart';
import '../../core/theme/tokens.g.dart' as tokens;
import '../../core/ui/ember_ui.dart';
import '../../core/widgets/app_spinner.dart';
import '../../core/widgets/avatar_hero.dart';
import '../../im/im_client.dart';
import '../../im/im_manager.dart';
import '../../im/im_repository.dart';
import '../../im/voice_recorder.dart';
import '../presence/models.dart';
import '../presence/presence_controller.dart';
import '../profile/profile_controller.dart';
import 'chat_controller.dart';
import 'chat_items.dart';
import 'conversations_controller.dart';
import 'draft_store.dart';
import 'match_cache.dart';
import 'quote.dart';
import 'recall.dart';
import 'voice_record_controller.dart';
import 'widgets/chat_confirm_dialog.dart';
import 'widgets/chat_illustration.dart';
import 'widgets/chat_skeleton.dart';
import 'widgets/emoji_panel.dart';
import 'widgets/message_bubble.dart';
import 'widgets/more_panel.dart';
import 'widgets/photo_viewer.dart';
import 'widgets/voice_record_overlay.dart';

/// 聊天页(「余烬 Ember」§9.4 二级页 shell + E-5.3 page spec §1 / §3 / §5)。
///
/// 本单只换视觉与动效:`chat_controller` / `im/` 传输层一行没动。
/// 与心跳期(附录 B.2 / B.3)相比,用户看得见的变化(page spec §1 的表):
/// 1. 顶栏 62 → **52**(§9.4:返回 22 + 标题 17/w600 居中);
/// 2. 输入栏换 [EmberField](高 52,`surface.card` + 1px 描边 + `radius.md`);
/// 3. 表情 / 更多面板从「输入栏下方的常驻条」改 [EmberSheet](轻量选择,§9.3);
/// 4. 多选顶栏与底部操作条高度对齐 52,进出多选不跳版;
/// 5. 空 / 错两态换 [EmberEmpty] + unDraw 插画(灰色图标占位是 §6 明令禁止的);
/// 6. 图标一律 Phosphor,动效一律 spring(`_focusOn` 的滚动也改用弹簧曲线)。
class ChatPage extends ConsumerStatefulWidget {
  /// 构造聊天页。
  const ChatPage({
    super.key,
    required this.peerId,
    this.focusMsgId,
    this.pickImage = pickChatImageFromGallery,
  });

  /// 对方的 IM id,如 'u9'。
  final String peerId;

  /// 从搜索页点进来的定位目标:进入后回溯历史、滚到这条消息并高亮。
  final String? focusMsgId;

  /// 相册选图(测试注入用)。
  final PickImage pickImage;

  @override
  ConsumerState<ChatPage> createState() => _ChatPageState();
}

class _ChatPageState extends ConsumerState<ChatPage> {
  final _input = TextEditingController();
  final _focusNode = FocusNode();
  final _scroll = ScrollController();
  final _itemKeys = <String, GlobalKey>{};
  bool _sending = false;
  bool _focusStarted = false;
  String? _highlightMsgId;

  /// 多选模式(批次 T-2):顶栏换「已选 N 条」+ 取消,每条左侧出勾选圈,
  /// 底部输入栏换成「复制文本 / 删除」操作条。
  bool _selectMode = false;

  /// 已勾选的消息 id(按集合存:去重、与顺序无关,渲染时再按历史顺序取)。
  final _selected = <String>{};

  /// 草稿防抖定时器(批次 T-2):输入 300ms 没有新字符才落盘,免得一个字一次写。
  Timer? _draftTimer;

  /// 草稿读写的入口。存成字段是因为 `dispose` 里不能用 `ref`(同 [_chat])。
  DraftStore? _drafts;

  /// 输入停止多久后把草稿落盘。
  static const draftDebounce = Duration(milliseconds: 300);

  /// build 里存下的会话控制器:State.dispose 不能用 `ref`,而「离开页面清掉
  /// 正在输入」必须在那里同步做(见 [dispose])。
  ChatController? _chat;

  @override
  void initState() {
    super.initState();
    // 被对方解除配对时,本地缓存还是登录时的旧数据;进聊天页刷一次才能发现
    unawaited(ref.read(matchCacheProvider.notifier).refresh());
    // 回填草稿(批次 T-2):预加载是后台跑的,这里等它一次再读,读不到就空着。
    _drafts = ref.read(draftStoreProvider.notifier);
    unawaited(_restoreDraft());
  }

  /// 把本机会话草稿回填进输入框(只回填一次,且不覆盖用户已经打的字)。
  Future<void> _restoreDraft() async {
    await _drafts?.preload();
    if (!mounted) return;
    final draft = _drafts?.draftOf(widget.peerId);
    if (draft == null || _input.text.isNotEmpty) return;
    // 光标放到末尾:回填的草稿是「接着写」,不是「选中重写」。
    _input.value = TextEditingValue(
      text: draft,
      selection: TextSelection.collapsed(offset: draft.length),
    );
  }

  @override
  void dispose() {
    // 离开聊天页(批次 L-1):立即清掉「对方正在输入…」并取消 3 秒节流定时器。
    // 两个 provider 都是 autoDispose,但回收是**异步**的 —— 只靠它的话,退出瞬间
    // 还可能留着上一个人的提示与一个未取消的定时器。这里同步清一次。
    //
    // 用 build 里存下的控制器、而不是 `ref`:State.dispose 里碰 ref 是明确禁止的
    // (`ConsumerStatefulElement` 会抛「about to or has been unmounted is unsafe」)。
    _chat?.leaveChat();
    // 还有没落盘的草稿(打完字 300ms 内就按了返回):当场补存一次,
    // 否则「手快」会白打。这里不能 await、也不该 await —— 写 prefs 是页面生命周期
    // 之外的 I/O,用字段 [_drafts] 而不是 ref(dispose 里碰 ref 是禁止的)。
    if ((_draftTimer?.isActive ?? false) && _input.text.trim().isNotEmpty) {
      unawaited(_drafts?.save(widget.peerId, _input.text) ?? Future<void>.value());
    }
    _draftTimer?.cancel();
    _input.dispose();
    _focusNode.dispose();
    _scroll.dispose();
    super.dispose();
  }

  /// 搜索定位:先回溯历史直到目标进列表,再逐屏滚动找到它的渲染对象,
  /// 最后 ensureVisible 居中并高亮 1.5s。目标已撤回/被删就静默停在原位。
  Future<void> _focusOn(String msgId) async {
    // 减弱动态效果:直接落位(§7.3「取消位移」),不做滚动动画。
    // 在第一个 `await` **之前**取:跨 async gap 再用 context 会被
    // `use_build_context_synchronously` 判红,而且那时页面可能已被回收。
    final reduced = EmberMotion.reducedOf(context);
    final controller = ref.read(chatProvider(widget.peerId).notifier);
    await controller.loadOlder(untilMsgId: msgId);
    if (!mounted) return;
    await WidgetsBinding.instance.endOfFrame;
    for (var attempt = 0; attempt < 24; attempt++) {
      if (_itemKeys[msgId]?.currentContext != null) break;
      if (!_scroll.hasClients) return;
      final position = _scroll.position;
      final next = (position.pixels + position.viewportDimension * 0.8)
          .clamp(0.0, position.maxScrollExtent);
      if (next <= position.pixels + 1) break;
      _scroll.jumpTo(next);
      await WidgetsBinding.instance.endOfFrame;
      if (!mounted) return;
    }
    final targetContext = _itemKeys[msgId]?.currentContext;
    if (targetContext == null || !targetContext.mounted) return;
    await Scrollable.ensureVisible(
      targetContext,
      alignment: 0.5,
      // 位移类动画一律用 spring(§7.1):用弹簧采样出来的曲线,不写曲线常量。
      duration: reduced ? Duration.zero : const Duration(milliseconds: 420),
      curve: EmberMotion.gentleCurve,
    );
    if (!mounted) return;
    setState(() => _highlightMsgId = msgId);
    Timer(const Duration(milliseconds: 1500), () {
      if (mounted) setState(() => _highlightMsgId = null);
    });
  }

  Future<void> _send() async {
    final text = _input.text.trim();
    if (text.isEmpty || _sending) return;
    setState(() => _sending = true);
    await ref.read(chatProvider(widget.peerId).notifier).send(text);
    _input.clear();
    // 草稿的生命周期止于「发出去了」:输入框已清空,再留着 key 会让列表一直挂
    // 「[草稿] 」—— 而这段话已经变成气泡了(失败也还在气泡上,能点重发)。
    _draftTimer?.cancel();
    unawaited(_drafts?.clear(widget.peerId) ?? Future<void>.value());
    if (mounted) setState(() => _sending = false);
  }

  /// 输入框内容变化:转发「正在输入」+ 排一次草稿落盘。
  ///
  /// Args:
  ///   text: 输入框当前内容。
  void _onInputChanged(String text) {
    // 输入中状态(批次 L-1):节流在 controller 里(3 秒一次),这里只管转发
    ref.read(chatProvider(widget.peerId).notifier).notifyTyping(text);
    _draftTimer?.cancel();
    if (text.trim().isEmpty) {
      // 清空 = 这条不写了:立刻删 key,不留一个空草稿让列表挂前缀。
      unawaited(_drafts?.clear(widget.peerId) ?? Future<void>.value());
      return;
    }
    _draftTimer = Timer(draftDebounce, () {
      unawaited(_drafts?.save(widget.peerId, text) ?? Future<void>.value());
    });
  }

  /// 这条消息能不能进多选:已撤回 / 发送中 / 居中灰条都不给选。
  ///
  /// 已撤回本来就只剩一行灰字,删它没有意义;发送中的消息 id 还是 `local-` 前缀,
  /// 服务端不认识,混进批量会让整批 42201;灰条(系统通知)没有气泡本体可点。
  ///
  /// Args:
  ///   message: 待判断的消息。
  ///
  /// Returns:
  ///   可选返回 true。
  bool _canSelect(ChatMessage message) =>
      !message.isRevoked &&
      !message.isPending &&
      message.msgId.isNotEmpty &&
      (message.kind == ChatMessageKind.text ||
          message.kind == ChatMessageKind.image ||
          message.kind == ChatMessageKind.voice ||
          message.kind == ChatMessageKind.sticker);

  /// 进入多选模式:收掉输入区(表情/＋面板、引用条),清空上一次的选择。
  void _enterSelectMode() {
    setState(() {
      _selectMode = true;
      _selected.clear();
    });
    FocusScope.of(context).unfocus();
    // 引用是「下一条要发的内容」,多选期间输入栏都不在,留着只会误导。
    ref.read(chatQuoteTargetProvider(widget.peerId).notifier).clear();
  }

  /// 退出多选模式(取消 / 删除成功后调用)。
  void _exitSelectMode() {
    if (!_selectMode) return;
    setState(() {
      _selectMode = false;
      _selected.clear();
    });
  }

  /// 多选模式下点消息本体:切换这一条的选中状态。
  ///
  /// 上限 [ChatController.maxDeleteBatch] 条:imserver 的 `ids` 最多 50 条,超了整批
  /// 会 400。与其让用户勾满一屏再吃一个错误,不如在勾不动的那一刻就告诉他。
  ///
  /// Args:
  ///   message: 被点的消息(不可选的消息直接忽略)。
  void _toggleSelect(ChatMessage message) {
    if (!_canSelect(message)) return;
    final selected = _selected.contains(message.msgId);
    if (!selected && _selected.length >= ChatController.maxDeleteBatch) {
      EmberToast.show(context, '一次最多选 ${ChatController.maxDeleteBatch} 条');
      return;
    }
    setState(() {
      if (selected) {
        _selected.remove(message.msgId);
      } else {
        _selected.add(message.msgId);
      }
    });
  }

  /// 把当前**还在列表里**的选中项挑出来(按历史顺序,旧 → 新)。
  ///
  /// 剪掉「已经不在了」的 id:对方撤回 / 别的端删掉的消息会让集合里留下幽灵 id,
  /// 顶部「已选 N 条」就会比实际能删的多。
  ///
  /// Args:
  ///   messages: 当前会话的完整消息列表。
  ///
  /// Returns:
  ///   选中的消息,按历史顺序。
  List<ChatMessage> _selectedMessages(List<ChatMessage> messages) =>
      [for (final message in messages) if (_selected.contains(message.msgId)) message];

  /// 复制选中里的**文本**消息:按时间顺序用换行连接(多条粘出去仍是一条一句)。
  ///
  /// Args:
  ///   messages: 当前会话的完整消息列表。
  Future<void> _copySelected(List<ChatMessage> messages) async {
    final texts = [
      for (final message in _selectedMessages(messages))
        if (message.kind == ChatMessageKind.text && message.text.isNotEmpty) message.text,
    ];
    if (texts.isEmpty) return;
    await Clipboard.setData(ClipboardData(text: texts.join('\n')));
    if (mounted) EmberToast.show(context, '已复制');
  }

  /// 删除选中的消息:先确认,再走 IM 的批量删除。
  ///
  /// 失败时**保留选中**并 toast —— 清空等于把用户一条条勾出来的选择丢了,而失败
  /// 多半是网络 / 限流,重试一次远比重勾一遍便宜。
  Future<void> _deleteSelected() async {
    final messages = ref.read(chatProvider(widget.peerId)).value ?? const <ChatMessage>[];
    final ids = [for (final message in _selectedMessages(messages)) message.msgId];
    if (ids.isEmpty) return;
    final confirmed = await showChatConfirmDialog(
      context,
      icon: PhosphorIconsRegular.trash,
      title: '删除这 ${ids.length} 条?',
      message: '只在你这边删除,对方仍可见。',
      confirmLabel: '删除 ${ids.length} 条',
      danger: true,
      confirmKey: const Key('chat.select.confirm'),
    );
    if (!confirmed || !mounted) return;
    try {
      await ref.read(chatProvider(widget.peerId).notifier).deleteMessages(ids);
    } catch (error) {
      if (!mounted) return;
      EmberToast.show(context, _errorMessageOf(error));
      return; // 选中原样保留
    }
    if (!mounted) return;
    _exitSelectMode();
    EmberToast.show(context, '已删除');
  }

  /// 删除失败的提示文案:业务错误用服务端的话,其余给一句人话。
  ///
  /// Args:
  ///   error: 抛出物([ApiException] / [ImException] / 其它)。
  ///
  /// Returns:
  ///   给 toast 用的中文文案。
  String _errorMessageOf(Object error) {
    if (error is ApiException) return error.message;
    if (error is ImException) return error.message;
    return '删除失败,请重试';
  }

  void _openProfile(BuildContext context, Map<String, MatchEntry> cache) {
    // 优先用 matches 缓存里的真实 id;缓存没有(如刚被清)就按 u9 → 9 兜底
    final userId =
        cache[widget.peerId]?.userId ?? int.tryParse(widget.peerId.replaceFirst('u', ''));
    if (userId == null) return;
    context.push('/users/$userId', extra: 'avatar-chat-${widget.peerId}');
  }

  /// 表情面板(E-5.3:`EmberSheet` 轻量选择,选完即关)。
  Future<void> _openEmojiSheet() async {
    FocusScope.of(context).unfocus();
    final result = await EmberSheet.show<EmojiSheetResult>(
      context,
      maxHeightRatio: 0.5,
      // 内容本身是可滚的网格:下拉手势要留给网格,别把面板拖走。
      draggable: false,
      child: const EmojiSheet(),
    );
    if (!mounted || result == null) return;
    switch (result) {
      case EmojiPicked(:final emoji):
        setState(() => _insertEmoji(emoji));
        // 插完把焦点还给输入框:接着打字是常态,再点一次输入框很烦。
        _focusNode.requestFocus();
      case StickerPicked(:final stickerId):
        await _sendSticker(stickerId);
    }
  }

  /// ＋ 面板(E-5.3:`EmberSheet`),目前只有「相册」。
  Future<void> _openMoreSheet() async {
    FocusScope.of(context).unfocus();
    final action = await EmberSheet.show<MoreSheetAction>(
      context,
      maxHeightRatio: 0.3,
      child: const MoreSheet(),
    );
    if (!mounted || action == null) return;
    if (action == MoreSheetAction.image) await _pickAndSendImage();
  }

  void _insertEmoji(String emoji) {
    final selection = _input.selection;
    final start = selection.start >= 0 ? selection.start : _input.text.length;
    final end = selection.end >= 0 ? selection.end : _input.text.length;
    final text = _input.text.replaceRange(start, end, emoji);
    _input.value = TextEditingValue(
      text: text,
      selection: TextSelection.collapsed(offset: start + emoji.length),
    );
  }

  /// 重发一条失败的消息(M-3:语音转码失败 / 发送失败都走这里)。
  ///
  /// 语音要先确认那段本地录音还在:临时目录会被系统清理,文件没了还去重传只会再失败一次,
  /// 这时直接提示重录(与「点击重试」同一处入口,不给用户一个永远转圈的重试)。
  ///
  /// Args:
  ///   message: 被点重发的消息。
  Future<void> _retryMessage(ChatMessage message) async {
    if (message.kind == ChatMessageKind.voice) {
      final exists = await ref
          .read(voiceFileExistsProvider)(message.localPath ?? '');
      if (!mounted) return;
      if (!exists) {
        EmberToast.show(context, voiceRetryMissingFileText);
        return;
      }
    }
    await ref.read(chatProvider(widget.peerId).notifier).retry(message);
  }

  /// 贴纸是**直接发送**(不插输入框):点一下就是一条消息。
  Future<void> _sendSticker(String stickerId) async {
    await ref.read(chatProvider(widget.peerId).notifier).sendSticker(stickerId);
  }

  Future<void> _pickAndSendImage() async {
    final file = await widget.pickImage();
    if (file == null || !mounted) return;
    await ref.read(chatProvider(widget.peerId).notifier).sendImage(file.path);
  }

  /// 点图片气泡 → 全屏(批次 T-2)。
  ///
  /// 传的是**会话内全部图片** + 当前这条的下标,这样全屏里能左右滑着看这一串图,
  /// 而不是「退出去再点下一张」。`PhotoViewerPage` 本身早就支持缩放 + 左右切,
  /// 这里只是把「只有一张」改成「一串」。
  ///
  /// 没有可用地址的图片(如刚发出、只有本地文件的)跳过;当前这条跳过了就退回第一张。
  ///
  /// Args:
  ///   message: 被点的那条图片消息。
  void _openImage(ChatMessage message) {
    final messages = ref.read(chatProvider(widget.peerId)).value ?? const <ChatMessage>[];
    final images = [
      for (final item in messages)
        if (item.kind == ChatMessageKind.image && !item.isRevoked) item,
    ];
    final urls = <String>[];
    final owners = <String>[];
    for (final item in images) {
      final url = _imageUrlOf(item);
      if (url == null) continue;
      urls.add(url);
      owners.add(item.msgId);
    }
    if (urls.isEmpty) return;
    final index = owners.indexOf(message.msgId);
    openPhotoViewer(context, urls: urls, initialIndex: index < 0 ? 0 : index);
  }

  /// 全屏看图用的地址:优先原图,没有原图用缩略图;两者都空返回 null。
  ///
  /// Args:
  ///   message: 图片消息。
  ///
  /// Returns:
  ///   可直接给 `Image.network` 的地址。
  String? _imageUrlOf(ChatMessage message) {
    final large = message.imageLargeUrl;
    if (large != null && large.isNotEmpty) return large;
    final thumb = message.imageUrl;
    if (thumb != null && thumb.isNotEmpty) return thumb;
    return null;
  }

  /// 标题降级链的第三级:IM 会话名(昵称已由后端同步到 IM 资料)。
  String? _imNameOf(WidgetRef ref) {
    final conversations = ref.watch(conversationsProvider).value;
    if (conversations == null) return null;
    for (final conversation in conversations) {
      if (conversation.peerId == widget.peerId) return conversation.showName;
    }
    return null;
  }

  /// 头像降级链的第三级:IM 会话头像(同样来自后端同步的 IM 资料)。
  String? _imFaceUrlOf(WidgetRef ref) {
    final conversations = ref.watch(conversationsProvider).value;
    if (conversations == null) return null;
    for (final conversation in conversations) {
      if (conversation.peerId == widget.peerId) return conversation.faceUrl;
    }
    return null;
  }

  /// 长按气泡弹出操作菜单。
  ///
  /// Args:
  ///   itemContext: **气泡自己的** context(菜单要定位到它)。它只用来算菜单位置 ——
  ///     菜单关掉之后就不能再碰它:真机上输入框重新获得焦点会弹起键盘、把视口压小,
  ///     `ListView` 随之回收这条气泡,`itemContext.mounted` 立刻变成 false。曾经
  ///     这里用 `!context.mounted` 做守卫,结果「引用 / 复制 / 撤回 / 删除」在真机上
  ///     全部静默失效(菜单关了、什么都没发生)。判活要用页面自己的 [mounted]。
  ///   message: 被长按的消息。
  Future<void> _showMessageMenu(BuildContext itemContext, ChatMessage message) async {
    final renderObject = itemContext.findRenderObject();
    final overlay = Overlay.of(itemContext).context.findRenderObject();
    final position = (renderObject is RenderBox && overlay is RenderBox)
        ? RelativeRect.fromRect(
            Rect.fromPoints(
              renderObject.localToGlobal(Offset.zero, ancestor: overlay),
              renderObject.localToGlobal(renderObject.size.bottomRight(Offset.zero),
                  ancestor: overlay),
            ),
            Offset.zero & overlay.size,
          )
        : RelativeRect.fill;
    final action = await showMenu<String>(
      context: itemContext,
      position: position,
      items: [
        // 引用(批次 L-2):灰条 / 已撤回的消息没有可引用的内容,不给入口。
        if (canQuote(message))
          const PopupMenuItem(
              key: Key('chat.menu.quote'), value: 'quote', child: Text('引用')),
        if (canRecall(message))
          const PopupMenuItem(
              key: Key('chat.menu.recall'), value: 'recall', child: Text('撤回')),
        if (message.kind == ChatMessageKind.text)
          const PopupMenuItem(
              key: Key('chat.menu.copy'), value: 'copy', child: Text('复制')),
        // 多选(批次 T-2):从这里进「勾选 → 删除 / 复制」模式。
        const PopupMenuItem(
            key: Key('chat.menu.multi'), value: 'multi', child: Text('多选')),
        const PopupMenuItem(
            key: Key('chat.menu.delete'), value: 'delete', child: Text('删除')),
      ],
    );
    // 判活用**页面**的 mounted,不是气泡的 itemContext(见方法注释)。
    if (action == null || !mounted) return;
    if (action == 'quote') {
      _startQuote(message);
    } else if (action == 'copy') {
      await Clipboard.setData(ClipboardData(text: message.text));
      if (mounted) EmberToast.show(context, '已复制');
    } else if (action == 'multi') {
      _enterSelectMode();
    } else if (action == 'recall') {
      try {
        await ref.read(chatProvider(widget.peerId).notifier).revoke(message);
        if (mounted) EmberToast.show(context, '已撤回');
      } on ImException catch (error) {
        if (mounted) EmberToast.show(context, error.message);
      }
    } else if (action == 'delete') {
      await ref.read(chatProvider(widget.peerId).notifier).deleteLocal(message);
    }
  }

  /// 选中一条消息作为引用目标(批次 L-2):输入栏上方出现引用条。
  ///
  /// 只记 id 与本地摘要;发送时**只上行 `ref_msg_id`**,内容由服务端回库查后生成快照。
  ///
  /// Args:
  ///   message: 被引用的消息(调用方已用 [canQuote] 判过)。
  void _startQuote(ChatMessage message) {
    final msgId = int.tryParse(message.msgId);
    if (msgId == null) return;
    // 自己的消息用当前登录的 IM id 署名;对端的就是会话对端。
    final status = ref.read(imStatusProvider);
    final selfId = status is ImLoggedIn ? status.imUserId : '';
    ref.read(chatQuoteTargetProvider(widget.peerId).notifier).set(QuoteTarget(
          msgId: msgId,
          from: message.isSelf ? selfId : widget.peerId,
          text: quoteSummaryOf(message),
        ));
  }

  /// 点引用块:跳到被引用的原消息。
  ///
  /// 原消息不在当前已加载的记录里(翻页翻出去了 / 被删除)时只提示,不假装跳过去。
  ///
  /// Args:
  ///   msgId: 被引用消息的 id。
  void _jumpToQuote(String msgId) {
    final items = ref.read(chatProvider(widget.peerId)).value ?? const <ChatMessage>[];
    if (!items.any((item) => item.msgId == msgId)) {
      EmberToast.show(context, '原消息不在当前记录中');
      return;
    }
    unawaited(_focusOn(msgId));
  }

  Future<void> _unmatch() async {
    final userId = userIdFromImId(widget.peerId);
    if (userId == null) return;
    final confirmed = await showChatConfirmDialog(
      context,
      icon: PhosphorIconsRegular.linkBreak,
      title: '解除配对?',
      message: '解除后双方将无法再聊天,且无法恢复。',
      confirmLabel: '解除配对',
      danger: true,
      confirmKey: const Key('chat.unmatch.confirm'),
    );
    if (!confirmed || !mounted) return;
    try {
      await ref.read(imRepositoryProvider).unmatch(userId);
    } on ApiException catch (error) {
      if (mounted) EmberToast.show(context, error.message);
      return;
    }
    try {
      await ref.read(imClientProvider).deleteConversation(widget.peerId);
    } catch (_) {}
    ref.invalidate(matchCacheProvider);
    unawaited(ref.read(conversationsProvider.notifier).reload());
    if (!mounted) return;
    EmberToast.show(context, '已解除配对');
    Navigator.of(context).maybePop();
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final messages = ref.watch(chatProvider(widget.peerId));
    // 存一份控制器:dispose 里不能用 ref,而「离开页面清掉正在输入」必须同步做
    _chat = ref.read(chatProvider(widget.peerId).notifier);
    final imageEnabled = ref.read(imClientProvider).capabilities.image;
    final voiceEnabled = ref.read(imClientProvider).capabilities.voice;
    final readReceiptEnabled = ref.read(imClientProvider).capabilities.readReceipt;
    // 对端读到哪:下行 read 帧实时更新,打开会话时由 controller 从会话列表补拉一次
    final peerReadSeq = ref.watch(chatPeerReadSeqProvider(widget.peerId));
    // 对端是否正在输入(批次 L-1):收到 typing 帧置真,5 秒没有新帧自动置假。
    // 这个 provider 是 autoDispose,离开聊天页即销毁 —— 下次进来一定是干净的 false。
    final peerTyping = ref.watch(chatPeerTypingProvider(widget.peerId));
    // 引用目标(批次 L-2):长按「引用」后出现在输入栏上方;发送成功即清空。
    final quoteTarget = ref.watch(chatQuoteTargetProvider(widget.peerId));
    final cache = ref.watch(matchCacheProvider).value ?? const <String, MatchEntry>{};
    final selfAvatarUrl = ref.watch(profileProvider).value?.avatar?.url;
    final peerName = displayNameFor(cache, widget.peerId, imName: _imNameOf(ref));
    final peerAvatarUrl =
        avatarUrlFor(cache, widget.peerId, imFaceUrl: _imFaceUrlOf(ref));
    final presenceById = ref.watch(presenceProvider);
    final peerUserId = userIdFromImId(widget.peerId);
    if (peerUserId != null) {
      ref.read(presenceProvider.notifier).track('chat:${widget.peerId}', [peerUserId]);
    }
    final peerPresence = peerUserId == null ? null : presenceById[peerUserId];
    // 配对缓存已加载且没有这个人 → 已被对方解除(系统通知不是配对,排除)
    final matchesAsync = ref.watch(matchCacheProvider);
    final cacheReady = matchesAsync.value != null;
    final unmatched = cacheReady &&
        widget.peerId != systemNoticePeerId &&
        !matchesAsync.value!.containsKey(widget.peerId);
    // 多选模式的计数只在**还在列表里**的选中项上算:撤回 / 别的端删除会让集合里
    // 留下幽灵 id,直接拿 _selected.length 会多算(详见 [_selectedMessages])。
    final liveMessages = messages.value ?? const <ChatMessage>[];
    final selectedMessages = _selectedMessages(liveMessages);
    final selectedCount = selectedMessages.length;
    final hasSelectedText =
        selectedMessages.any((item) => item.kind == ChatMessageKind.text);
    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            if (_selectMode)
              _SelectHeader(count: selectedCount, onCancel: _exitSelectMode)
            else
              _ChatHeader(
                name: peerName,
                presence: peerPresence,
                typing: peerTyping,
                avatarUrl: peerAvatarUrl,
                heroTag: 'avatar-chat-${widget.peerId}',
                onTapTitle: () => _openProfile(context, cache),
                onMore: _unmatch,
              ),
            if (unmatched)
              Container(
                key: const Key('chat.unmatchedBanner'),
                width: double.infinity,
                // 提示条走凹陷面 + 次级文字(§8.3 次级容器),不抢正文视线。
                color: colors.surfaceSunken,
                padding: EdgeInsets.symmetric(
                  horizontal: tokens.space20,
                  vertical: tokens.space8,
                ),
                child: Text(
                  '你们已解除配对',
                  textAlign: TextAlign.center,
                  style: AppText.micro.copyWith(color: colors.textSecondary),
                ),
              ),
            Expanded(
              child: messages.when(
                loading: () => const ChatSkeleton(),
                error: (error, _) => _ChatErrorView(
                  message: apiMessageOf(error),
                  onRetry: () => ref.invalidate(chatProvider(widget.peerId)),
                ),
                data: (items) {
                  if (items.isEmpty) return const _ChatEmptyView();
                  if (!_focusStarted && widget.focusMsgId != null && items.isNotEmpty) {
                    _focusStarted = true;
                    WidgetsBinding.instance
                        .addPostFrameCallback((_) => _focusOn(widget.focusMsgId!));
                  }
                  final chatItems = buildChatItems(items);
                  return ListView.builder(
                    key: const Key('chat.list'),
                    controller: _scroll,
                    reverse: true, // 新消息在底部,进来就停在最新一条
                    padding: EdgeInsets.symmetric(vertical: tokens.space12),
                    itemCount: chatItems.length,
                    itemBuilder: (context, index) {
                      final item = chatItems[chatItems.length - 1 - index];
                      return switch (item) {
                        ChatTimeItem(:final label) => _TimeSeparator(label),
                        // Builder 包一层:itemBuilder 的 context 是 sliver,取不到气泡自己的
                        // 渲染对象(长按菜单要定位到气泡)
                        ChatMessageItem(:final message) => Builder(
                            key: _itemKeys.putIfAbsent(message.msgId, GlobalKey.new),
                            builder: (itemContext) => MessageBubble(
                              message: message,
                              peerName: peerName,
                              peerAvatarUrl: peerAvatarUrl,
                              selfAvatarUrl: selfAvatarUrl,
                              highlight: message.msgId == _highlightMsgId,
                              readReceiptEnabled: readReceiptEnabled,
                              // 我方消息 seq <= 对端已读位置 → 已读。seq=0 是本地乐观消息
                              // (还没拿到服务端序号),不能算已读。
                              isRead: message.seq > 0 && message.seq <= peerReadSeq,
                              // 多选模式(批次 T-2):点本体=切换选中,长按菜单失效;
                              // 入场时机体动作全部让给勾选(见 MessageBubble.selectionMode)。
                              selectionMode: _selectMode,
                              selectable: _canSelect(message),
                              selected: _selected.contains(message.msgId),
                              onToggleSelect: () => _toggleSelect(message),
                              onLongPress: () => _showMessageMenu(itemContext, message),
                              onTapImage: () => _openImage(message),
                              // 点引用块跳回原消息(批次 L-2)
                              onTapQuote: message.ref == null
                                  ? null
                                  : () => _jumpToQuote('${message.ref!.msgId}'),
                              onRetry: () => _retryMessage(message),
                            ),
                          ),
                      };
                    },
                  );
                },
              ),
            ),
            // 多选模式(批次 T-2):输入区整块让位给操作条。引用条也一起收掉 ——
            // 它的作用域是「下一条要发的消息」,多选期间不该出现。
            if (_selectMode)
              _SelectActionBar(
                count: selectedCount,
                canCopy: hasSelectedText,
                onCopy: () => _copySelected(liveMessages),
                onDelete: _deleteSelected,
              )
            else ...[
              // 引用条(批次 L-2):长按「引用」后出现在输入栏上方,可点 × 取消。
              if (quoteTarget != null)
                _QuoteBar(
                  key: const Key('chat.quoteBar'),
                  sender: quoteTarget.from == widget.peerId ? peerName : '我',
                  text: quoteTarget.text,
                  onClose: () =>
                      ref.read(chatQuoteTargetProvider(widget.peerId).notifier).clear(),
                ),
              _InputBar(
                controller: _input,
                focusNode: _focusNode,
                sending: _sending,
                enabled: !unmatched,
                showMore: imageEnabled,
                showVoice: voiceEnabled && !unmatched,
                onSend: _send,
                // 输入中状态(批次 L-1)+ 草稿落盘(批次 T-2),都在 _onInputChanged 里
                onInputChanged: _onInputChanged,
                onToggleEmoji: _openEmojiSheet,
                onToggleMore: _openMoreSheet,
                onSendVoice: (path, durationMs) => ref
                    .read(chatProvider(widget.peerId).notifier)
                    .sendVoice(path, durationMs),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// 多选模式的顶栏(批次 T-2):左「×」退出、中间「已选 N 条」。
///
/// 与 [_ChatHeader] 同高 **52**(§9.4),保证进出多选时消息列表不跳一下。
class _SelectHeader extends StatelessWidget {
  const _SelectHeader({required this.count, required this.onCancel});

  /// 已选条数(只算还在列表里的,见 `_ChatPageState._selectedMessages`)。
  final int count;

  /// 退出多选。
  final VoidCallback onCancel;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return SizedBox(
      height: tokens.sizeControlHeight,
      child: Row(
        children: [
          _HeaderIcon(
            entryKey: const Key('chat.select.cancel'),
            icon: PhosphorIconsRegular.x,
            label: '退出多选',
            onTap: onCancel,
          ),
          Expanded(
            child: Text(
              '已选 $count 条',
              key: const Key('chat.select.count'),
              style: AppText.subtitle.copyWith(color: colors.textPrimary),
            ),
          ),
          // 与左侧关闭键等宽:文字左对齐贴住关闭键,不居中飘着
          SizedBox(width: tokens.sizeTouchApp),
        ],
      ),
    );
  }
}

/// 多选模式的底部操作条(批次 T-2):复制文本(仅当选中里有文本)/ 删除。
///
/// 没有选中任何一条时两个按钮都是禁用态 —— 不给「点了没反应」的按钮。
class _SelectActionBar extends StatelessWidget {
  const _SelectActionBar({
    required this.count,
    required this.canCopy,
    required this.onCopy,
    required this.onDelete,
  });

  /// 已选条数。
  final int count;

  /// 选中里是否至少有一条文本消息(否则「复制文本」没内容可复制)。
  final bool canCopy;

  /// 复制选中的文本。
  final VoidCallback onCopy;

  /// 删除选中的消息(内部会先弹确认框)。
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return Container(
      color: colors.surfaceCard,
      child: SafeArea(
        top: false,
        child: Padding(
          padding: EdgeInsets.all(tokens.space12),
          child: Row(
            children: [
              Expanded(
                child: EmberButton(
                  key: const Key('chat.select.copy'),
                  label: '复制文本',
                  variant: EmberButtonVariant.secondary,
                  onPressed: canCopy ? onCopy : null,
                ),
              ),
              SizedBox(width: tokens.space12),
              Expanded(
                child: EmberButton(
                  key: const Key('chat.select.delete'),
                  label: '删除',
                  variant: EmberButtonVariant.danger,
                  onPressed: count == 0 ? null : onDelete,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// 顶栏图标按钮:热区 48×48、图标 24(§6 工具栏档 + §8.4 触控),读屏必带标签。
class _HeaderIcon extends StatelessWidget {
  const _HeaderIcon({
    required this.entryKey,
    required this.icon,
    required this.label,
    required this.onTap,
  });

  final Key entryKey;
  final IconData icon;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return EmberPressable(
      key: entryKey,
      onTap: onTap,
      pressedScale: 0.97,
      borderRadius: BorderRadius.circular(tokens.radiusPill),
      semanticLabel: label,
      builder: (context, state) => SizedBox(
        width: tokens.sizeTouchApp,
        height: tokens.sizeTouchApp,
        child: Icon(icon, size: tokens.sizeIcon24, color: colors.textPrimary),
      ),
    );
  }
}

/// 二级页顶栏(§9.4):高 **52**;返回 22 档 + 头像 32 + 标题 17/w600;右侧更多。
///
/// 与心跳期(附录 B.2,高 62)的差别就是这一档高度与图标字族 —— 结构(头像 Hero、
/// 名字 + 状态行、右侧「⋯」)保持不变,状态行仍然承载在线 / 正在输入。
class _ChatHeader extends StatelessWidget {
  const _ChatHeader({
    required this.name,
    required this.presence,
    required this.onTapTitle,
    required this.onMore,
    this.typing = false,
    this.avatarUrl,
    this.heroTag,
  });

  final String name;
  final Presence? presence;

  /// 对端正在输入(批次 L-1)。为真时状态行换成「对方正在输入…」。
  final bool typing;
  final VoidCallback onTapTitle;
  final VoidCallback onMore;
  final String? avatarUrl;
  final String? heroTag;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final online = presence?.online ?? false;
    // 在线单独组装(绿点 + 「在线」);离线才用 presenceLabel 的「x 分钟前在线」。
    // 正在输入时**只显示这一句**:它比在线状态更具体,两行挤在一起反而看不清;
    // 绿点也一起收起来,避免「绿点 + 正在输入」两种信号打架。
    final statusLabel =
        typing ? '对方正在输入…' : (online ? '在线' : presenceLabel(presence));
    return SizedBox(
      height: tokens.sizeControlHeight,
      child: Row(
        children: [
          _HeaderIcon(
            entryKey: const Key('chat.back'),
            icon: PhosphorIconsRegular.caretLeft,
            label: '返回',
            onTap: () => Navigator.of(context).maybePop(),
          ),
          Expanded(
            child: GestureDetector(
              key: const Key('chat.title'),
              behavior: HitTestBehavior.opaque,
              onTap: onTapTitle,
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  AvatarHero(
                    tag: heroTag,
                    imageUrl: avatarUrl,
                    fromRadius: tokens.radiusPill,
                    child: EmberAvatar(
                      image: (avatarUrl == null || avatarUrl!.isEmpty)
                          ? null
                          : NetworkImage(avatarUrl!),
                      size: EmberComponentSizes.avatarSm,
                      name: name,
                    ),
                  ),
                  SizedBox(width: tokens.space8),
                  Flexible(
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          name,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: AppText.subtitle.copyWith(color: colors.textPrimary),
                        ),
                        if (statusLabel != null)
                          Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              if (online && !typing) ...[
                                EmberOnlineDot(
                                  key: const Key('chat.onlineDot'),
                                  size: EmberComponentSizes.onlineDotSmall,
                                  background: colors.surfacePage,
                                ),
                                SizedBox(width: tokens.space4),
                              ],
                              Flexible(
                                child: Text(
                                  statusLabel,
                                  // 正在输入单独给个 key:页面测试按 key 断言,
                                  // 不去比文案(文案以后可能改)
                                  key: typing ? const Key('chat.typing') : null,
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  textScaler: TextScaler.noScaling,
                                  style: AppText.micro.copyWith(
                                    color: typing
                                        ? colors.brandDefault
                                        : colors.textSecondary,
                                  ),
                                ),
                              ),
                            ],
                          ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
          // 与左侧返回键等宽,保证「头像 + 名字」整块在屏幕上居中
          SizedBox(
            width: tokens.sizeTouchApp,
            height: tokens.sizeTouchApp,
            child: PopupMenuButton<String>(
              key: const Key('chat.more'),
              tooltip: '更多',
              padding: EdgeInsets.zero,
              icon: Icon(
                PhosphorIconsRegular.dotsThree,
                size: tokens.sizeIcon24,
                color: colors.textPrimary,
              ),
              onSelected: (value) {
                if (value == 'unmatch') onMore();
              },
              itemBuilder: (context) => [
                PopupMenuItem(
                  key: const Key('chat.menu.unmatch'),
                  value: 'unmatch',
                  child: Text(
                    '解除配对',
                    style: TextStyle(color: colors.statusDanger),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// 输入栏上方的引用条(批次 L-2):显示「引用谁 + 摘要」,点 × 取消引用。
///
/// 只显示本地摘要 —— 真正发给对端的快照由服务端生成,两边文案口径一致
/// (见 `imserver` 的 `build_ref_snapshot` 与 `quote.dart::quoteSummaryOf`)。
///
/// 视觉同气泡里的引用块: `surface.sunken` + `radius.sm` + 左侧 2px `brand.default`(§8.3)。
class _QuoteBar extends StatelessWidget {
  const _QuoteBar({
    super.key,
    required this.sender,
    required this.text,
    required this.onClose,
  });

  /// 被引用消息的发送者(显示名:「我」或对端昵称)。
  final String sender;

  /// 被引用内容的摘要。
  final String text;

  /// 取消引用。
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return Container(
      width: double.infinity,
      color: colors.surfacePage,
      padding: EdgeInsets.fromLTRB(
        tokens.space20,
        tokens.space8,
        tokens.space8,
        0,
      ),
      child: Row(
        children: [
          Expanded(
            child: ClipRRect(
              borderRadius: BorderRadius.circular(tokens.radiusSm),
              child: Container(
                padding: EdgeInsets.symmetric(
                  horizontal: tokens.space8,
                  vertical: tokens.space4,
                ),
                decoration: BoxDecoration(
                  color: colors.surfaceSunken,
                  border: Border(
                    left: BorderSide(color: colors.brandDefault, width: 2),
                  ),
                ),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '引用 $sender',
                      key: const Key('chat.quoteBar.sender'),
                      style: AppText.micro.copyWith(color: colors.brandDefault),
                    ),
                    Text(
                      text,
                      key: const Key('chat.quoteBar.text'),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppText.micro.copyWith(color: colors.textSecondary),
                    ),
                  ],
                ),
              ),
            ),
          ),
          EmberPressable(
            key: const Key('chat.quoteBar.close'),
            onTap: onClose,
            pressedScale: 0.97,
            borderRadius: BorderRadius.circular(tokens.radiusPill),
            semanticLabel: '取消引用',
            builder: (context, state) => SizedBox(
              width: tokens.sizeTouchWeb,
              height: tokens.sizeTouchWeb,
              child: Icon(
                PhosphorIconsRegular.x,
                size: tokens.sizeIcon20,
                color: colors.textSecondary,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// 时间条:12 / `text.tertiary` 居中,上下边距 12,间隔 >5 分钟插入(§8.2)。
///
/// 「12」这一档在 `design/tokens/scale.json` 里没有(只有 11 `micro` 与 13 `caption`),
/// 规范又禁止裸字号,所以取最接近的 `caption` 13 —— 与相邻的摘要同档,不跳字。
class _TimeSeparator extends StatelessWidget {
  const _TimeSeparator(this.label);

  final String label;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return Padding(
      key: const Key('chat.time'),
      padding: EdgeInsets.symmetric(vertical: tokens.space12),
      child: Center(
        child: Text(
          label,
          textScaler: TextScaler.noScaling,
          style: AppText.caption.copyWith(color: colors.textTertiary),
        ),
      ),
    );
  }
}

/// 历史为空:居中一句「打个招呼吧」,不占满屏(page spec §5)。
class _ChatEmptyView extends StatelessWidget {
  const _ChatEmptyView();

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return Center(
      child: Text(
        '打个招呼吧',
        textAlign: TextAlign.center,
        style: AppText.caption.copyWith(color: colors.textTertiary),
      ),
    );
  }
}

/// 历史加载失败:`EmberEmpty` 错误形态 + 「重试」(page spec §5)。
class _ChatErrorView extends StatelessWidget {
  const _ChatErrorView({required this.message, required this.onRetry});

  /// 后端 / 网络给的文案(页面不自己编)。
  final String message;

  /// 重试回调。
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) => SingleChildScrollView(
        child: ConstrainedBox(
          constraints: BoxConstraints(minHeight: constraints.maxHeight),
          child: Center(
            child: Padding(
              padding: EdgeInsets.all(tokens.space24),
              child: EmberEmpty(
                illustration: const ChatIllustration(ChatIllustrationKind.loadFailed),
                title: '没能加载出来',
                description: message,
                actionLabel: '重试',
                actionKey: const Key('chat.retryLoad'),
                onAction: onRetry,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _InputBar extends ConsumerStatefulWidget {
  const _InputBar({
    required this.controller,
    required this.focusNode,
    required this.sending,
    required this.enabled,
    this.showMore = true,
    this.showVoice = false,
    required this.onSend,
    required this.onInputChanged,
    required this.onToggleEmoji,
    required this.onToggleMore,
    required this.onSendVoice,
  });

  final TextEditingController controller;
  final FocusNode focusNode;
  final bool sending;

  /// 已解除配对时整栏禁用(历史仍可读,但不能再发消息)。
  final bool enabled;

  /// 当前后端是否支持图片;自建后端隐藏「＋」入口。
  final bool showMore;

  /// 当前实现是否支持语音;不支持时隐藏麦克风。
  final bool showVoice;
  final VoidCallback onSend;

  /// 输入框内容变化(批次 L-1):转发给控制器做 3 秒节流的「正在输入」。
  final ValueChanged<String> onInputChanged;
  final VoidCallback onToggleEmoji;
  final VoidCallback onToggleMore;

  /// 录完一段语音(本地路径 + 毫秒),由聊天页上传并发送。
  final void Function(String path, int durationMs) onSendVoice;

  @override
  ConsumerState<_InputBar> createState() => _InputBarState();
}

class _InputBarState extends ConsumerState<_InputBar> {
  late final VoiceRecordController _voice;

  @override
  void initState() {
    super.initState();
    _voice = VoiceRecordController(
      recorder: ref.read(voiceRecorderProvider),
      tempPath: ref.read(voiceTempPathProvider),
      onNotice: (message) {
        if (mounted) EmberToast.show(context, message);
      },
      onSend: (path, durationMs) async => widget.onSendVoice(path, durationMs),
    )..addListener(_onVoiceChanged);
  }

  void _onVoiceChanged() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    _voice
      ..removeListener(_onVoiceChanged)
      ..dispose();
    super.dispose();
  }

  /// 栏内图标:44×44 热区(§8.4),图标本体 24(§6 工具栏档)。
  Widget _iconButton({
    required Key key,
    required IconData icon,
    required String label,
    required Color color,
    required VoidCallback? onPressed,
  }) =>
      EmberPressable(
        key: key,
        onTap: onPressed,
        pressedScale: 0.97,
        borderRadius: BorderRadius.circular(tokens.radiusPill),
        semanticLabel: label,
        builder: (context, state) => SizedBox(
          width: tokens.sizeTouchWeb,
          height: tokens.sizeTouchWeb,
          child: Icon(icon, size: tokens.sizeIcon24, color: color),
        ),
      );

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final seconds = _voice.seconds;
    return Stack(
      clipBehavior: Clip.none,
      children: [
        Container(
          color: colors.surfacePage,
          child: SafeArea(
            top: false,
            child: Padding(
              padding: EdgeInsets.all(tokens.space8),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  if (widget.showVoice)
                    // 长按录音是**手势**不是点击,所以这里用 GestureDetector 而不是
                    // `EmberPressable`(后者的按压反馈由 tap 驱动,长按录音期间会让
                    // 麦克风一直缩着)。热区 44×44 不变(§8.4)。
                    Semantics(
                      button: true,
                      label: '按住说话',
                      child: GestureDetector(
                        key: const Key('chat.mic'),
                        behavior: HitTestBehavior.opaque,
                        onLongPressStart: widget.enabled ? (_) => _voice.start() : null,
                        onLongPressMoveUpdate: widget.enabled
                            ? (details) => _voice
                                .updateCancelArm(details.localOffsetFromOrigin.dy < -60)
                            : null,
                        onLongPressEnd:
                            widget.enabled ? (_) => _voice.stopAndSend() : null,
                        child: SizedBox(
                          width: tokens.sizeTouchWeb,
                          height: tokens.sizeTouchWeb,
                          child: Icon(
                            PhosphorIconsRegular.microphone,
                            size: tokens.sizeIcon24,
                            color: widget.enabled
                                ? colors.textSecondary
                                : colors.textTertiary,
                          ),
                        ),
                      ),
                    ),
                  // 表情在输入框左边
                  _iconButton(
                    key: const Key('chat.emoji.button'),
                    icon: PhosphorIconsRegular.smiley,
                    label: '表情',
                    color: widget.enabled ? colors.textSecondary : colors.textTertiary,
                    onPressed: widget.enabled ? widget.onToggleEmoji : null,
                  ),
                  Expanded(
                    // EmberField 的 `TextField` 自带自己的 key,这里再包一层同名 key:
                    // 页面测试按 `chat.input` 找输入框(整栏换组件后 key 不能丢)。
                    child: KeyedSubtree(
                      key: const Key('chat.input'),
                      child: EmberField(
                        controller: widget.controller,
                        focusNode: widget.focusNode,
                        enabled: widget.enabled,
                        placeholder: '说点什么…',
                        label: '消息',
                        onChanged: widget.onInputChanged,
                        onSubmitted: (_) => widget.onSend(),
                      ),
                    ),
                  ),
                  if (widget.showMore)
                    _iconButton(
                      key: const Key('chat.more.button'),
                      icon: PhosphorIconsRegular.plus,
                      label: '更多',
                      color: widget.enabled ? colors.textSecondary : colors.textTertiary,
                      onPressed: widget.enabled ? widget.onToggleMore : null,
                    ),
                  ListenableBuilder(
                    listenable: widget.controller,
                    // sending:转圈替换纸飞机并禁连点(§8.3 按钮 loading 行)。
                    builder: (context, _) => widget.sending
                        ? Semantics(
                            label: '发送中',
                            child: SizedBox(
                              width: tokens.sizeTouchWeb,
                              height: tokens.sizeTouchWeb,
                              child: Center(
                                child: AppSpinner(
                                  key: const Key('chat.send.busy'),
                                  size: tokens.sizeIcon20,
                                  color: colors.brandDefault,
                                ),
                              ),
                            ),
                          )
                        : _iconButton(
                            key: const Key('chat.send'),
                            icon: PhosphorIconsFill.paperPlaneRight,
                            label: '发送',
                            color: widget.controller.text.trim().isEmpty || !widget.enabled
                                ? colors.textTertiary
                                : colors.brandDefault,
                            onPressed: !widget.enabled ? null : widget.onSend,
                          ),
                  ),
                ],
              ),
            ),
          ),
        ),
        if (_voice.phase == VoicePhase.recording)
          Positioned(
            left: 0,
            right: 0,
            bottom: tokens.sizeControlHeight + tokens.space16,
            child: Center(
              child: VoiceRecordOverlay(
                seconds: seconds,
                cancelArmed: _voice.cancelArmed,
              ),
            ),
          ),
      ],
    );
  }
}
