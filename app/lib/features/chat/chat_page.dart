import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/image_pick.dart';
import '../../core/theme/heart_theme_context.dart';
import '../../core/theme/app_radius.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_avatar.dart';
import '../../core/widgets/app_button.dart';
import '../../core/widgets/app_dialog.dart';
import '../../core/widgets/app_empty_state.dart';
import '../../core/widgets/app_error_view.dart';
import '../../core/widgets/app_toast.dart';
import '../../core/widgets/avatar_hero.dart';
import '../../core/widgets/breathing_dot.dart';
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
import 'widgets/chat_bubbles_mark.dart';
import 'widgets/chat_skeleton.dart';
import 'widgets/emoji_panel.dart';
import 'widgets/message_bubble.dart';
import 'widgets/more_panel.dart';
import 'widgets/photo_viewer.dart';
import 'widgets/voice_record_overlay.dart';

class ChatPage extends ConsumerStatefulWidget {
  const ChatPage({super.key, required this.peerId, this.focusMsgId,
      this.pickImage = pickChatImageFromGallery});

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
  bool _showEmoji = false;
  bool _showMore = false;
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
    // 键盘弹起时收起表情/＋面板
    _focusNode.addListener(() {
      if (_focusNode.hasFocus && (_showEmoji || _showMore)) {
        setState(() {
          _showEmoji = false;
          _showMore = false;
        });
      }
    });
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
      duration: const Duration(milliseconds: 250),
      curve: Curves.easeOut,
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
      _showEmoji = false;
      _showMore = false;
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
      AppToast.show(context, '一次最多选 ${ChatController.maxDeleteBatch} 条');
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
    if (mounted) AppToast.show(context, '已复制');
  }

  /// 删除选中的消息:先确认,再走 IM 的批量删除。
  ///
  /// 失败时**保留选中**并 toast —— 清空等于把用户一条条勾出来的选择丢了,而失败
  /// 多半是网络 / 限流,重试一次远比重勾一遍便宜。
  Future<void> _deleteSelected() async {
    final messages = ref.read(chatProvider(widget.peerId)).value ?? const <ChatMessage>[];
    final ids = [for (final message in _selectedMessages(messages)) message.msgId];
    if (ids.isEmpty) return;
    final confirmed = await showConfirmDialog(
      context,
      title: '删除这 ${ids.length} 条?',
      message: '只在你这边删除,对方仍可见。',
      confirmLabel: '删除',
      danger: true,
      confirmKey: const Key('chat.select.confirm'),
    );
    if (!confirmed || !mounted) return;
    try {
      await ref.read(chatProvider(widget.peerId).notifier).deleteMessages(ids);
    } catch (error) {
      if (!mounted) return;
      AppToast.show(context, _errorMessageOf(error));
      return; // 选中原样保留
    }
    if (!mounted) return;
    _exitSelectMode();
    AppToast.show(context, '已删除');
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

  void _toggleEmoji() {
    setState(() {
      _showEmoji = !_showEmoji;
      _showMore = false;
    });
    if (_showEmoji) FocusScope.of(context).unfocus();
  }

  void _toggleMore() {
    setState(() {
      _showMore = !_showMore;
      _showEmoji = false;
    });
    if (_showMore) FocusScope.of(context).unfocus();
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

  /// 贴纸是**直接发送**(不插输入框):点一下就是一条消息。
  Future<void> _sendSticker(String stickerId) async {
    await ref.read(chatProvider(widget.peerId).notifier).sendSticker(stickerId);
  }

  Future<void> _pickAndSendImage() async {
    final file = await widget.pickImage();
    if (file == null || !mounted) return;
    setState(() => _showMore = false);
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
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('已复制')));
      }
    } else if (action == 'multi') {
      _enterSelectMode();
    } else if (action == 'recall') {
      try {
        await ref.read(chatProvider(widget.peerId).notifier).revoke(message);
        if (mounted) AppToast.show(context, '已撤回');
      } on ImException catch (error) {
        if (mounted) AppToast.show(context, error.message);
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
      AppToast.show(context, '原消息不在当前记录中');
      return;
    }
    unawaited(_focusOn(msgId));
  }

  Future<void> _unmatch() async {
    final userId = userIdFromImId(widget.peerId);
    if (userId == null) return;
    final confirmed = await showConfirmDialog(
      context,
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
      if (mounted) AppToast.show(context, error.message);
      return;
    }
    try {
      await ref.read(imClientProvider).deleteConversation(widget.peerId);
    } catch (_) {}
    ref.invalidate(matchCacheProvider);
    unawaited(ref.read(conversationsProvider.notifier).reload());
    if (!mounted) return;
    AppToast.show(context, '已解除配对');
    Navigator.of(context).maybePop();
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
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
    final hasSelectedText = selectedMessages.any((item) => item.kind == ChatMessageKind.text);
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
              color: colors.divider,
              padding: const EdgeInsets.symmetric(
                  horizontal: AppSpacing.pageH, vertical: AppSpacing.sm),
              child: Text('你们已解除配对',
                  textAlign: TextAlign.center,
                  style: AppText.micro.copyWith(color: colors.text2)),
            ),
          Expanded(
            child: messages.when(
              loading: () => const ChatSkeleton(),
              error: (error, _) => AppErrorView(
                message: apiMessageOf(error),
                onRetry: () => ref.invalidate(chatProvider(widget.peerId)),
              ),
              data: (items) {
                if (items.isEmpty) {
                  return const Center(
                    child: AppEmptyState(
                      mark: ChatBubblesMark(),
                      title: '打个招呼吧',
                      description: '发条消息,开始你们的故事',
                    ),
                  );
                }
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
                  padding: const EdgeInsets.symmetric(vertical: 12),
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
                            onRetry: () =>
                                ref.read(chatProvider(widget.peerId).notifier).retry(message),
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
              onToggleEmoji: _toggleEmoji,
              onToggleMore: _toggleMore,
              onSendVoice: (path, durationMs) => ref
                  .read(chatProvider(widget.peerId).notifier)
                  .sendVoice(path, durationMs),
            ),
            if (_showEmoji)
              EmojiPanel(onSelect: _insertEmoji, onSendSticker: _sendSticker)
            else if (_showMore && imageEnabled)
              MorePanel(onPickImage: _pickAndSendImage),
          ],
        ],
        ),
      ),
    );
  }
}

/// 多选模式的顶栏(批次 T-2):左「×」退出、中间「已选 N 条」。
///
/// 与 [_ChatHeader] 同高 62,保证进出多选时消息列表不跳一下。
class _SelectHeader extends StatelessWidget {
  const _SelectHeader({required this.count, required this.onCancel});

  /// 已选条数(只算还在列表里的,见 `_ChatPageState._selectedMessages`)。
  final int count;

  /// 退出多选。
  final VoidCallback onCancel;

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    return SizedBox(
      height: 62,
      child: Row(
        children: [
          IconButton(
            key: const Key('chat.select.cancel'),
            tooltip: '退出多选',
            onPressed: onCancel,
            icon: Icon(Icons.close_rounded, size: 22, color: colors.text1),
          ),
          Expanded(
            child: Text(
              '已选 $count 条',
              key: const Key('chat.select.count'),
              style: AppText.subtitle.copyWith(fontSize: 17, color: colors.text1),
            ),
          ),
          // 与左侧关闭键等宽:文字左对齐贴住关闭键,不居中飘着
          const SizedBox(width: 48),
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
    final colors = context.heart;
    return Container(
      color: colors.bgCard,
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.sm),
          child: Row(
            children: [
              Expanded(
                child: AppButton(
                  key: const Key('chat.select.copy'),
                  label: '复制文本',
                  variant: AppButtonVariant.secondary,
                  onPressed: canCopy ? onCopy : null,
                ),
              ),
              const SizedBox(width: AppSpacing.md),
              Expanded(
                child: AppButton(
                  key: const Key('chat.select.delete'),
                  label: '删除',
                  variant: AppButtonVariant.dangerFilled,
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

/// 「心跳」附录 B.2 + C.8:高 62;返回 22;头像 32(带 Hero);标题两行居中(名字 + 状态行)。
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
    final colors = context.heart;
    final online = presence?.online ?? false;
    // 在线单独组装(绿点 + 「在线」);离线才用 presenceLabel 的「x 分钟前在线」。
    // 正在输入时**只显示这一句**:它比在线状态更具体,两行挤在一起反而看不清;
    // 绿点也一起收起来,避免「绿点 + 正在输入」两种信号打架。
    final statusLabel =
        typing ? '对方正在输入…' : (online ? '在线' : presenceLabel(presence));
    return SizedBox(
      height: 62,
      child: Row(
        children: [
          IconButton(
            key: const Key('chat.back'),
            onPressed: () => Navigator.of(context).maybePop(),
            icon: Icon(Icons.arrow_back_ios_new_rounded,
                size: 22, color: colors.text1),
          ),
          Expanded(
            child: GestureDetector(
              key: const Key('chat.title'),
              behavior: HitTestBehavior.opaque,
              onTap: onTapTitle,
              child: Row(
                children: [
                  AvatarHero(
                    tag: heroTag,
                    imageUrl: avatarUrl,
                    fromRadius: AppRadius.full,
                    child: AppAvatar(
                      imageUrl: avatarUrl,
                      size: 32,
                      fallbackText: name,
                    ),
                  ),
                  const SizedBox(width: AppSpacing.sm),
                  Expanded(
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Text(name,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: AppText.subtitle
                                .copyWith(fontSize: 17, color: colors.text1)),
                        if (statusLabel != null) ...[
                          const SizedBox(height: 1),
                          Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              if (online && !typing) ...[
                                BreathingDot(
                                    key: const Key('chat.onlineDot'),
                                    size: 8,
                                    borderColor: colors.bgPage),
                                const SizedBox(width: AppSpacing.xs),
                              ],
                              Text(statusLabel,
                                  // 正在输入单独给个 key:页面测试按 key 断言,
                                  // 不去比文案(文案以后可能改)
                                  key: typing ? const Key('chat.typing') : null,
                                  style: AppText.micro.copyWith(
                                      color: typing ? colors.brand : colors.text2)),
                            ],
                          ),
                        ],
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
          // 与左侧返回键(48)等宽,保证「头像 + 名字」整块在屏幕上居中
          SizedBox(
            width: 48,
            height: 48,
            child: PopupMenuButton<String>(
              key: const Key('chat.more'),
              icon: Icon(Icons.more_horiz_rounded, size: 22, color: colors.text1),
              padding: EdgeInsets.zero,
              onSelected: (value) {
                if (value == 'unmatch') onMore();
              },
              itemBuilder: (context) => [
                PopupMenuItem(
                  key: const Key('chat.menu.unmatch'),
                  value: 'unmatch',
                  child: Text('解除配对', style: TextStyle(color: colors.danger)),
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
    final colors = context.heart;
    return Container(
      width: double.infinity,
      color: colors.bgCard,
      padding: const EdgeInsets.fromLTRB(
          AppSpacing.pageH, AppSpacing.sm, AppSpacing.sm, 0),
      child: Row(
        children: [
          Expanded(
            child: ClipRRect(
              borderRadius: BorderRadius.circular(AppRadius.chip),
              child: Container(
                padding: const EdgeInsets.symmetric(
                    horizontal: AppSpacing.sm, vertical: 6),
                decoration: BoxDecoration(
                  color: colors.divider,
                  border:
                      Border(left: BorderSide(color: colors.brand, width: 3)),
                ),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('引用 $sender',
                        key: const Key('chat.quoteBar.sender'),
                        style: AppText.micro.copyWith(color: colors.brand)),
                    Text(
                      text,
                      key: const Key('chat.quoteBar.text'),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppText.micro.copyWith(color: colors.text2),
                    ),
                  ],
                ),
              ),
            ),
          ),
          IconButton(
            key: const Key('chat.quoteBar.close'),
            onPressed: onClose,
            tooltip: '取消引用',
            visualDensity: VisualDensity.compact,
            icon: Icon(Icons.close_rounded, size: 20, color: colors.text2),
          ),
        ],
      ),
    );
  }
}

class _TimeSeparator extends StatelessWidget {
  const _TimeSeparator(this.label);

  final String label;

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    return Padding(
        key: const Key('chat.time'),
        padding: const EdgeInsets.symmetric(vertical: AppSpacing.md),
        child: Center(
          child: Text(label, style: AppText.micro.copyWith(color: colors.text3)),
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
        if (mounted) AppToast.show(context, message);
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

  /// 栏内图标:44 方块(与输入框同高,保证同行对齐),图标 24 居中。
  Widget _iconButton({
    required Key key,
    required IconData icon,
    required Color color,
    required VoidCallback? onPressed,
  }) =>
      IconButton(
        key: key,
        onPressed: onPressed,
        padding: EdgeInsets.zero,
        constraints: const BoxConstraints.tightFor(width: 44, height: 44),
        icon: Icon(icon, size: 24, color: color),
      );

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    final seconds = _voice.seconds;
    return Stack(
      clipBehavior: Clip.none,
      children: [
        Container(
          color: colors.bgCard,
          child: SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.all(AppSpacing.sm),
              child: Row(
                children: [
                  if (widget.showVoice)
                    GestureDetector(
                      key: const Key('chat.mic'),
                      behavior: HitTestBehavior.opaque,
                      onLongPressStart: (_) => _voice.start(),
                      onLongPressMoveUpdate: (details) =>
                          _voice.updateCancelArm(details.localOffsetFromOrigin.dy < -60),
                      onLongPressEnd: (_) => _voice.stopAndSend(),
                      child: SizedBox(
                        width: 44,
                        height: 44,
                        child: Icon(
                          Icons.mic_rounded,
                          size: 24,
                          color: widget.enabled ? colors.text2 : colors.text3,
                        ),
                      ),
                    ),
                  // 表情在输入框左边
                  _iconButton(
                    key: const Key('chat.emoji.button'),
                    icon: Icons.emoji_emotions_rounded,
                    color: colors.text2,
                    onPressed: widget.enabled ? widget.onToggleEmoji : null,
                  ),
                  Expanded(
                    child: ListenableBuilder(
                      listenable: widget.focusNode,
                      builder: (context, child) => Container(
                        height: 44,
                        decoration: BoxDecoration(
                          color: colors.bgCard,
                          borderRadius: BorderRadius.circular(AppRadius.input),
                          border: Border.all(
                            color: widget.focusNode.hasFocus
                                ? colors.brand
                                : colors.divider,
                            width: widget.focusNode.hasFocus ? 1.5 : 1,
                          ),
                          boxShadow: widget.focusNode.hasFocus
                              ? [
                                  BoxShadow(
                                    color: colors.brand.withValues(alpha: .12),
                                    blurRadius: 12,
                                  ),
                                ]
                              : null,
                        ),
                        // 外观由外层容器绘制,TextField 自身无边框(避免装饰器自带
                        // 高度约束在真机上把可见框压小)
                        child: child,
                      ),
                      child: TextField(
                        key: const Key('chat.input'),
                        controller: widget.controller,
                        focusNode: widget.focusNode,
                        enabled: widget.enabled,
                        textInputAction: TextInputAction.send,
                        onChanged: widget.onInputChanged,
                        onSubmitted: (_) => widget.onSend(),
                        expands: true,
                        maxLines: null,
                        minLines: null,
                        textAlignVertical: TextAlignVertical.center,
                        style: AppText.body.copyWith(color: colors.text1),
                        decoration: InputDecoration(
                          isCollapsed: true,
                          border: InputBorder.none,
                          hintText: '说点什么…',
                          hintStyle: AppText.body.copyWith(color: colors.text3),
                          contentPadding: const EdgeInsets.symmetric(horizontal: 14),
                        ),
                      ),
                    ),
                  ),
                  if (widget.showMore)
                    _iconButton(
                      key: const Key('chat.more.button'),
                      icon: Icons.add_circle_rounded,
                      color: colors.text2,
                      onPressed: widget.enabled ? widget.onToggleMore : null,
                    ),
                  ListenableBuilder(
                    listenable: widget.controller,
                    builder: (context, _) => _iconButton(
                      key: const Key('chat.send'),
                      icon: Icons.send_rounded,
                      color: widget.controller.text.trim().isEmpty || !widget.enabled
                          ? colors.text3
                          : colors.brand,
                      onPressed: widget.sending || !widget.enabled ? null : widget.onSend,
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
            bottom: 64,
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
