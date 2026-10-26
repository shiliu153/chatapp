import { createImClient } from './client'
import {
  type ChatMessage,
  type ImBootstrap,
  type ImCapabilities,
  type ImClient,
  type ImConversation,
  type ImEvent,
} from './types'
import { SelfImClient } from './self/client'

/** 按引导包选择腾讯/自建实现;业务层只依赖 ImClient。 */
export class RoutingImClient implements ImClient {
  private active?: ImClient
  private listeners: ((event: ImEvent) => void)[] = []

  get capabilities(): ImCapabilities {
    return this.active?.capabilities ?? { image: false, search: false }
  }

  onEvent(listener: (event: ImEvent) => void): void {
    this.listeners.push(listener)
  }

  async init(bootstrap: ImBootstrap): Promise<void> {
    this.active = bootstrap.backend === 'self'
      ? new SelfImClient()
      : createImClient()
    this.active.onEvent((event) => {
      for (const listener of this.listeners) listener(event)
    })
    await this.active.init(bootstrap)
  }

  login(userId: string, userSig: string): Promise<void> {
    return this.active!.login(userId, userSig)
  }

  logout(): Promise<void> {
    return this.active?.logout() ?? Promise.resolve()
  }

  fetchConversations(): Promise<ImConversation[]> {
    return this.active!.fetchConversations()
  }

  fetchHistory(peerId: string, count?: number, beforeSeq?: number): Promise<ChatMessage[]> {
    return this.active!.fetchHistory(peerId, count, beforeSeq)
  }

  searchMessages(keyword: string, limit?: number, beforeId?: string) {
    return this.active!.searchMessages(keyword, limit, beforeId)
  }

  sendText(peerId: string, text: string): Promise<ChatMessage> {
    return this.active!.sendText(peerId, text)
  }

  sendImage(peerId: string, file: File): Promise<ChatMessage> {
    return this.active!.sendImage(peerId, file)
  }

  deleteMessage(msgId: string): Promise<void> {
    return this.active!.deleteMessage(msgId)
  }

  revokeMessage(msgId: string): Promise<void> {
    return this.active!.revokeMessage(msgId)
  }

  markConversationRead(peerId: string): Promise<void> {
    return this.active!.markConversationRead(peerId)
  }

  deleteConversation(peerId: string): Promise<void> {
    return this.active!.deleteConversation(peerId)
  }
}
