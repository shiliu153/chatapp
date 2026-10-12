import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

// 与 tokens.spec.ts 同理:工作目录固定是 web/,不用 import.meta.url(vitest+jsdom 下不是 file://)
const sha = (p: string) => createHash('sha256').update(readFileSync(p)).digest('hex')
const appFont = (n: string) => resolve(process.cwd(), '../app/assets/fonts', n)
const webFont = (n: string) => resolve(process.cwd(), 'public/fonts', n)

describe('字体文件与 App 同源', () => {
  for (const name of [
    'SpaceGrotesk-Regular.ttf',
    'SpaceGrotesk-Medium.ttf',
    'SpaceGrotesk-Bold.ttf',
  ]) {
    it(`${name} 内容一致`, () => {
      expect(sha(webFont(name))).toBe(sha(appFont(name)))
    })
  }
})
