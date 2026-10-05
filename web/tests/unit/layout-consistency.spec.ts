import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { layout } from '@/layout'

const css = readFileSync(resolve(process.cwd(), 'src/styles/tokens.css'), 'utf8')

function cssNumber(name: string): number {
  const m = css.match(new RegExp(`--${name}:\\s*([\\d.]+)(px|%)?;`))
  if (!m) throw new Error(`tokens.css 缺少 --${name}`)
  return Number(m[1])
}

describe('侧栏几何:JS 与 CSS 必须一致', () => {
  it('比例与上下限', () => {
    expect(cssNumber('sidebar-ratio')).toBe(layout.sidebar.ratio * 100)
    expect(cssNumber('sidebar-min')).toBe(layout.sidebar.min)
    expect(cssNumber('sidebar-max')).toBe(layout.sidebar.max)
  })

  it('拖拽范围与图标阈值', () => {
    expect(cssNumber('sidebar-drag-min')).toBe(layout.sidebar.dragMin)
    expect(cssNumber('sidebar-drag-max')).toBe(layout.sidebar.dragMax)
    expect(cssNumber('sidebar-icon-threshold')).toBe(layout.sidebar.iconThreshold)
  })

  it('会话列表宽度与气泡最大宽', () => {
    expect(cssNumber('chatlist-ratio')).toBe(layout.chatList.ratio * 100)
    expect(cssNumber('chatlist-min')).toBe(layout.chatList.min)
    expect(cssNumber('chatlist-max')).toBe(layout.chatList.max)
    expect(cssNumber('bubble-max-ratio')).toBe(layout.bubbleMaxRatio * 100)
  })
})
