/** 自建 IM 的 WebSocket 传输抽象:测试注入假实现。 */
export interface SelfTransport {
  onFrame(fn: (raw: string) => void): void
  connect(url: string): Promise<void>
  send(raw: string): void
  close(): Promise<void>
}

export class BrowserWebSocketTransport implements SelfTransport {
  private ws?: WebSocket
  private handler?: (raw: string) => void

  onFrame(fn: (raw: string) => void): void {
    this.handler = fn
  }

  connect(url: string): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      const ws = new WebSocket(url)
      this.ws = ws
      ws.onopen = () => resolve()
      ws.onerror = () => reject(new Error('ws error'))
      ws.onmessage = (event) => this.handler?.(String(event.data))
    })
  }

  send(raw: string): void {
    this.ws?.send(raw)
  }

  close(): Promise<void> {
    this.ws?.close()
    return Promise.resolve()
  }
}
