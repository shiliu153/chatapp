import { describe, expect, it } from 'vitest'
import { APP_NAME, DOWNLOADS_ENABLED, HEARTBEAT_INTERVAL_MS } from '@/constants'

describe('工程冒烟', () => {
  it('应用名与设计语言一致', () => {
    expect(APP_NAME).toBe('心跳')
  })

  it('商店未上架前下载入口关闭', () => {
    expect(DOWNLOADS_ENABLED).toBe(false)
  })

  it('在线心跳与 App 一致(45 秒)', () => {
    expect(HEARTBEAT_INTERVAL_MS).toBe(45_000)
  })
})
