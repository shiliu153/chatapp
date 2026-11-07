/// 聊天贴纸目录(批次 J)。
///
/// 事实来源是**资源目录** `app/assets/stickers/`(12 张 512×512 PNG);
/// `web/public/stickers/` 必须与它逐字节一致,由 `scripts/check_stickers.py`
/// 在 `contract.yml` 里把关(删一个/改一张就会红)。
///
/// id 形状 `sticker_NN` 是**跨栈契约**:imserver 的上行白名单按这个形状校验
/// (`ws_server.cpp::is_sticker_id`),客户端不能随手造 id。
library;

/// 一张贴纸:本地资源 id + 无障碍/兜底文案。
class ChatSticker {
  const ChatSticker({required this.id, required this.label});

  /// 资源 id,如 `sticker_01`。消息里传的就是它。
  final String id;

  /// 文案(面板的 tooltip / 无障碍标签;气泡里不显示)。
  final String label;

  /// Flutter 资源路径。
  String get assetPath => 'assets/stickers/$id.png';
}

/// 12 张贴纸(与 `web/src/features/chat/stickers.ts` 一一对应)。
const chatStickers = <ChatSticker>[
  ChatSticker(id: 'sticker_01', label: '你好'),
  ChatSticker(id: 'sticker_02', label: '哈哈'),
  ChatSticker(id: 'sticker_03', label: '点赞'),
  ChatSticker(id: 'sticker_04', label: '抱抱'),
  ChatSticker(id: 'sticker_05', label: '晚安'),
  ChatSticker(id: 'sticker_06', label: '想你'),
  ChatSticker(id: 'sticker_07', label: '加油'),
  ChatSticker(id: 'sticker_08', label: '害羞'),
  ChatSticker(id: 'sticker_09', label: '惊讶'),
  ChatSticker(id: 'sticker_10', label: '委屈'),
  ChatSticker(id: 'sticker_11', label: '比心'),
  ChatSticker(id: 'sticker_12', label: '拜拜'),
];

/// 按 id 找贴纸;**未知 id 返回 null**。
///
/// 为什么允许未知:老版本客户端会收到新版本发的贴纸。返回 null 让渲染方降级成
/// 「[贴纸]」文本,而不是白屏或抛异常。
///
/// Args:
///   id: 消息里的贴纸 id。
///
/// Returns:
///   命中的贴纸;未知 id 返回 null。
ChatSticker? stickerById(String? id) {
  if (id == null || id.isEmpty) return null;
  for (final sticker in chatStickers) {
    if (sticker.id == id) return sticker;
  }
  return null;
}

/// 未知贴纸的降级文案(双端同一份文案,别单边改)。
const unknownStickerLabel = '[贴纸]';
