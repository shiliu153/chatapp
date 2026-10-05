import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

// 注意:vitest + jsdom 下 import.meta.url 不是 file:// 协议,不能用它定位文件;
// 测试的工作目录固定是 web/(vitest 的 root)。
const themeDir = resolve(process.cwd(), '../app/lib/core/theme')
const dart = (f: string) => readFileSync(resolve(themeDir, f), 'utf8')
const css = readFileSync(resolve(process.cwd(), 'src/styles/tokens.css'), 'utf8')

/** 把 camelCase 转成 CSS 的 kebab-case(bgPage → bg-page)。 */
const kebab = (s: string) => s.replace(/[A-Z]/g, (c) => '-' + c.toLowerCase())

/** 解析 Dart 里 `static const name = 数字;` / `= Duration(milliseconds: 数字)`。 */
function dartNumbers(src: string): Record<string, number> {
  const out: Record<string, number> = {}
  for (const m of src.matchAll(/static const (\w+) = (\d+(?:\.\d+)?);/g)) out[m[1]] = Number(m[2])
  for (const m of src.matchAll(/static const (\w+) = Duration\(milliseconds: (\d+)\)/g)) {
    out[m[1]] = Number(m[2])
  }
  return out
}

/** 解析 Dart 的 `static const name = Color(0xAARRGGBB);` → [r,g,b,a]。 */
function dartColors(src: string): Record<string, [number, number, number, number]> {
  const out: Record<string, [number, number, number, number]> = {}
  for (const m of src.matchAll(/static const (\w+) = Color\(0x([0-9A-Fa-f]{8})\);/g)) {
    const v = parseInt(m[2], 16)
    out[m[1]] = [(v >>> 16) & 0xff, (v >>> 8) & 0xff, v & 0xff, (v >>> 24) & 0xff]
  }
  return out
}

/** 解析 CSS 变量 `--name: #RRGGBB;` 或 `--name: rgb(r g b / a%);` 或 `--name: 12px;`。 */
function cssVars(src: string) {
  const colors: Record<string, [number, number, number, number]> = {}
  const numbers: Record<string, number> = {}
  for (const m of src.matchAll(/--([\w-]+):\s*([^;]+);/g)) {
    const [, name, raw] = m
    const value = raw.trim()
    const hex = value.match(/^#([0-9A-Fa-f]{6})$/)
    const rgba = value.match(/^rgb\((\d+) (\d+) (\d+) \/ ([\d.]+)%\)$/)
    const px = value.match(/^(\d+(?:\.\d+)?)(?:px|ms)$/) // 间距/圆角用 px,动效时长用 ms
    if (hex) {
      const v = parseInt(hex[1], 16)
      colors[name] = [(v >>> 16) & 0xff, (v >>> 8) & 0xff, v & 0xff, 255]
    } else if (rgba) {
      colors[name] = [
        Number(rgba[1]),
        Number(rgba[2]),
        Number(rgba[3]),
        Math.round((Number(rgba[4]) / 100) * 255),
      ]
    } else if (px) {
      numbers[name] = Number(px[1])
    }
  }
  return { colors, numbers }
}

const vars = cssVars(css)

describe('心跳 token:Web 与 App 数值必须一致', () => {
  it('色板(RGB 精确;alpha 容差 1/255,因为 CSS 用百分比表达)', () => {
    const src = dartColors(dart('app_colors.dart'))
    // app_colors.dart 里有 14 个 Color(0x……) 字面量(success/warning 是 green/amber 的别名,不产生变量)
    expect(Object.keys(src).length).toBeGreaterThanOrEqual(14)
    for (const [name, expected] of Object.entries(src)) {
      const actual = vars.colors['color-' + kebab(name)]
      expect(actual, `--color-${kebab(name)} 缺失`).toBeDefined()
      // RGB 必须逐通道精确相等:容差一旦放宽到 1,单个色阶的改动就抓不住了
      expect([actual[0], actual[1], actual[2]], `--color-${kebab(name)} 的 RGB`).toEqual([
        expected[0],
        expected[1],
        expected[2],
      ])
      // alpha 在 CSS 里写成百分比,四舍五入会差 1/255
      expect(
        Math.abs(actual[3] - expected[3]),
        `--color-${kebab(name)} 的 alpha`,
      ).toBeLessThanOrEqual(1)
    }
  })

  it('间距', () => {
    const src = dartNumbers(dart('app_spacing.dart'))
    expect(Object.keys(src).length).toBe(9) // 防止解析失败导致空跑通过
    for (const [name, expected] of Object.entries(src)) {
      expect(vars.numbers['space-' + kebab(name)], `--space-${kebab(name)} 缺失`).toBe(expected)
    }
  })

  it('圆角', () => {
    const src = dartNumbers(dart('app_radius.dart'))
    expect(Object.keys(src).length).toBe(8)
    for (const [name, expected] of Object.entries(src)) {
      expect(vars.numbers['radius-' + kebab(name)], `--radius-${kebab(name)} 缺失`).toBe(expected)
    }
  })

  it('动效时长', () => {
    const src = dartNumbers(dart('app_motion.dart'))
    expect(Object.keys(src).length).toBe(6)
    for (const [name, expected] of Object.entries(src)) {
      expect(vars.numbers['motion-' + kebab(name)], `--motion-${kebab(name)} 缺失`).toBe(expected)
    }
  })
})
