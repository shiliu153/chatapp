import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

// 与 tokens.spec.ts 同理:工作目录固定是 web/,不用 import.meta.url(vitest+jsdom 下不是 file://)
const sha = (p: string) => createHash('sha256').update(readFileSync(p)).digest('hex')
const appFont = (n: string) => resolve(process.cwd(), '../app/assets/fonts', n)
const webFont = (n: string) => resolve(process.cwd(), 'public/fonts', n)

// 「余烬 Ember」§4.1:只打包 Fraunces 一个可变字体(标题档),中文走系统字族不打包。
// 旧的 Space Grotesk 三份静态字重随「心跳」退役,已删除 —— 这里只列**当前实际存在**的实物,
// 多一份少一份都判红(文件名写死而不是扫目录:扫描会让「误删字体」变成静默通过)。
const FONT_FILES = ['Fraunces-Variable.ttf', 'OFL.txt']

describe('字体文件与 App 同源', () => {
  for (const name of FONT_FILES) {
    it(`${name} 内容一致`, () => {
      expect(sha(webFont(name))).toBe(sha(appFont(name)))
    })
  }
})

describe('字体只留 Ember 需要的那一份', () => {
  it('Space Grotesk 的静态字重已从两端删除', () => {
    for (const name of [
      'SpaceGrotesk-Regular.ttf',
      'SpaceGrotesk-Medium.ttf',
      'SpaceGrotesk-Bold.ttf',
    ]) {
      expect(() => readFileSync(appFont(name))).toThrow()
      expect(() => readFileSync(webFont(name))).toThrow()
    }
  })

  it('OFL 许可证随包(Fraunces 的版权行)', () => {
    const license = readFileSync(appFont('OFL.txt'), 'utf8')
    expect(license).toContain('Fraunces')
    expect(license).toContain('SIL Open Font License')
  })
})
