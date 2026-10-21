import {
  ChatMessageKind,
  type ChatMessage,
  type ImConversation,
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
  const customType = String(custom.type ?? '')
  let messageKind = ChatMessageKind.text
  if (kind === 'custom') {
    messageKind = customType === 'match_notice'
      ? ChatMessageKind.matchNotice
      : ChatMessageKind.banNotice
  }
  const profile = (json.from_profile ?? {}) as Record<string, unknown>
  return {
    msgId: String(json.msg_id ?? ''),
    peerId: self ? to : from,
    isSelf: self,
    timestamp: Number(json.ts ?? 0),
    kind: messageKind,
    text: kind === 'custom' ? String(custom.desc ?? '') : String(json.text ?? ''),
    senderName: String(profile.nickname ?? ''),
    senderAvatar: (profile.avatar as string | undefined) ?? null,
    isPending: false,
    isFailed: false,
    imageUrl: null,
    imageLargeUrl: null,
    isRevoked: json.revoked === true,
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
  }
}
