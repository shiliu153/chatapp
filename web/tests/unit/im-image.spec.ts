import { describe, expect, it } from 'vitest'

import { CHAT_IMAGE_MAX_SIDE, CHAT_IMAGE_QUALITY, compressImage } from '@/im/self/image'

describe('compressImage', () => {
  it('压缩参数与设计一致(长边 1920 / 质量 0.8)', () => {
    expect(CHAT_IMAGE_MAX_SIDE).toBe(1920)
    expect(CHAT_IMAGE_QUALITY).toBe(0.8)
  })

  it('画布不可用时原样返回文件(jsdom 没有 createImageBitmap)', async () => {
    const file = new File([new Uint8Array([1, 2, 3])], 'a.jpg', { type: 'image/jpeg' })
    const result = await compressImage(file)
    expect(result).toBe(file)
  })
})
