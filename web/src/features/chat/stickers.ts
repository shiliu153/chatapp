/**
 * 聊天贴纸目录(批次 J)。
 *
 * 事实来源是**资源目录** `web/public/stickers/`(12 张 512×512 PNG),必须与
 * `app/assets/stickers/` 逐字节一致 —— 由 `scripts/check_stickers.py` 在
 * `contract.yml` 里把关(删一个/改一张就会红)。
 *
 * id 形状 `sticker_NN` 是**跨栈契约**:imserver 的上行白名单按这个形状校验,
 * 客户端不能随手造 id。
 */

export interface ChatSticker {
  /** 资源 id,如 `sticker_01`。消息里传的就是它。 */
  id: string
  /** 文案(面板的 title / 无障碍标签;气泡里不显示)。 */
  label: string
  /** 静态资源地址(public 目录,构建后原样拷到 dist)。 */
  src: string
}

/** 12 张贴纸(与 App 的 `features/chat/stickers.dart` 一一对应)。 */
export const CHAT_STICKERS: ChatSticker[] = [
  { id: 'sticker_01', label: '你好' },
  { id: 'sticker_02', label: '哈哈' },
  { id: 'sticker_03', label: '点赞' },
  { id: 'sticker_04', label: '抱抱' },
  { id: 'sticker_05', label: '晚安' },
  { id: 'sticker_06', label: '想你' },
  { id: 'sticker_07', label: '加油' },
  { id: 'sticker_08', label: '害羞' },
  { id: 'sticker_09', label: '惊讶' },
  { id: 'sticker_10', label: '委屈' },
  { id: 'sticker_11', label: '比心' },
  { id: 'sticker_12', label: '拜拜' },
].map((item) => ({ ...item, src: `/stickers/${item.id}.png` }))

/** 未知贴纸的降级文案(与 App 同一份文案,别单边改)。 */
export const UNKNOWN_STICKER_LABEL = '[贴纸]'

/**
 * 按 id 找贴纸;**未知 id 返回 undefined**。
 *
 * 为什么允许未知:老版本客户端会收到新版本发的贴纸,渲染方降级成
 * `[贴纸]` 文本,而不是白屏或抛异常。
 */
export function stickerById(id?: string | null): ChatSticker | undefined {
  if (!id) return undefined
  return CHAT_STICKERS.find((item) => item.id === id)
}
