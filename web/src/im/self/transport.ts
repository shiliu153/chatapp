/** 连接被关闭时的信息(服务端空闲踢出是 1000,同端顶号是 4001)。 */
export interface TransportClose {
  code: number
  reason: string
}

/**
 * 自建 IM 的 WebSocket 传输抽象:测试注入假实现。
 *
 * ⚠️ `onClose` 只上报「非本端主动关闭」的关闭/错误。服务端 75 秒空闲会 `do_close(1000)`
 * (见 imserver `ws_server.cpp` 的 `arm_idle_timer`),前端若不听这个事件,连接断了
 * 仍显示 ready,对方新消息会静默丢失(2026-11-03 全栈审查 N-1)。
 */
export interface SelfTransport {
  onFrame(fn: (raw: string) => void): void
  onClose(fn: (info: TransportClose) => void): void
  connect(url: string): Promise<void>
  send(raw: string): void
  close(): Promise<void>
}

export class BrowserWebSocketTransport implements SelfTransport {
  private ws?: WebSocket
  private handler?: (raw: string) => void
  private closeHandler?: (info: TransportClose) => void
  /** 握手完成前出错要让 connect() 失败;完成后再出错交给 onclose 走断线流程 */
  private opened = false
  /** 本端主动 close():不上报 onClose,否则退出登录会被当成断线重连 */
  private closedByUs = false

  onFrame(fn: (raw: string) => void): void {
    this.handler = fn
  }

  onClose(fn: (info: TransportClose) => void): void {
    this.closeHandler = fn
  }

  connect(url: string): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      const ws = new WebSocket(url)
      this.ws = ws
      ws.onopen = () => {
        this.opened = true
        resolve()
      }
      ws.onerror = () => {
        if (!this.opened) reject(new Error('ws error'))
      }
      ws.onmessage = (event) => this.handler?.(String(event.data))
      ws.onclose = (event) => {
        if (this.closedByUs) return
        this.closeHandler?.({ code: event.code, reason: event.reason ?? '' })
      }
    })
  }

  send(raw: string): void {
    this.ws?.send(raw)
  }

  close(): Promise<void> {
    this.closedByUs = true
    this.ws?.close()
    return Promise.resolve()
  }
}
