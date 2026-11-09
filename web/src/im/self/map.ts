import {
  ChatMessageKind,
  type ChatMessage,
  type ImConversation,
  type QuoteRef,
} from '../types'

function isSelf(uid: string, me: string): boolean {
  return uid === me
}

export function messageFromJson(
  json: Record<string, unknown>,
  me: string,
): ChatMessage {
  const from = String(json.from ?? '')
  const to = String(json.to ?? '')
  const self = isSelf(from, me)
  const kind = String(json.kind ?? 'text')
  const custom = (json.custom ?? {}) as Record<string, unknown>
  const image = (json.image ?? {}) as Record<string, unknown>
  const voice = (json.voice ?? {}) as Record<string, unknown>
  const customType = String(custom.type ?? '')
  let messageKind = ChatMessageKind.text
  if (kind === 'custom') {
    if (customType === 'match_notice') {
      messageKind = ChatMessageKind.matchNotice
    } else if (customType === 'sticker') {
      // 贴纸(批次 J):资源在本地,消息里只有 id
      messageKind = ChatMessageKind.sticker
    } else {
      messageKind = ChatMessageKind.banNotice
    }
  }
  if (kind === 'image') {
    messageKind = ChatMessageKind.image
  }
  if (kind === 'voice') {
    messageKind = ChatMessageKind.voice
  }
  const profile = (json.from_profile ?? {}) as Record<string, unknown>
  return {
    msgId: String(json.msg_id ?? ''),
    peerId: self ? to : from,
    isSelf: self,
    seq: Number(json.seq ?? 0),
    timestamp: Number(json.ts ?? 0),
    kind: messageKind,
    text: kind === 'custom' ? String(custom.desc ?? '') : String(json.text ?? ''),
    senderName: String(profile.nickname ?? ''),
    senderAvatar: (profile.avatar as string | undefined) ?? null,
    isPending: false,
    isFailed: false,
    imageUrl: (image.thumb_url as string | undefined) ?? null,
    imageLargeUrl: (image.url as string | undefined) ?? null,
    voiceUrl: (voice.url as string | undefined) ?? null,
    voiceDurationMs: Number(voice.duration_ms ?? 0),
    stickerId:
      messageKind === ChatMessageKind.sticker ? String(custom.id ?? '') : null,
    isRevoked: json.revoked === true,
    // 引用(批次 L-2):**没有引用时服务端根本不下发这个键**,所以这里必须容忍缺省。
    ref: quoteRefFromJson(json.ref),
  }
}

/**
 * 解析下行 `ref` 对象(批次 L-2)。
 *
 * Args:
 *   raw: 下行帧 / 历史接口里的 `ref`;没有引用时是 undefined。
 *
 * Returns:
 *   引用快照;没有引用时返回 null(不要给一个空对象,那会渲染出空引用块)。
 */
export function quoteRefFromJson(raw: unknown): QuoteRef | null {
  if (!raw || typeof raw !== 'object') return null
  const json = raw as Record<string, unknown>
  return {
    msgId: Number(json.msg_id ?? 0),
    from: String(json.from ?? ''),
    kind: String(json.kind ?? 'text'),
    text: String(json.text ?? ''),
    revoked: json.revoked === true,
  }
}

export function conversationFromJson(
  json: Record<string, unknown>,
  me: string,
): ImConversation {
  const peer = (json.peer ?? {}) as Record<string, unknown>
  const last = json.last_message
  return {
    peerId: String(peer.id ?? ''),
    unreadCount: Number(json.unread ?? 0),
    showName: String(peer.nickname ?? ''),
    faceUrl: (peer.avatar as string | undefined) ?? null,
    lastMessage: last ? messageFromJson(last as Record<string, unknown>, me) : null,
    // 已读回执的**离线补拉**入口:断线期间对方读过什么,重连后靠这个字段算
    peerReadSeq: Number(json.peer_read_seq ?? 0),
    // 置顶 / 免打扰(批次 N):缺字段时按 false 兜底 —— 老版本 imserver 不回这两个键时
    // 会话行退化成本单之前的观感,不能因为 undefined 被当成「已置顶 / 已免打扰」。
    pinned: json.pinned === true,
    muted: json.muted === true,
  }
}
