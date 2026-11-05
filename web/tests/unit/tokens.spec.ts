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

/**
 * 取出某个选择器块的内容(第一个 `{` 到与之配对的 `}`)。
 * 暗色块是 `[data-theme='dark']`,浅色块是 `:root` —— 必须分开解析,
 * 否则同名变量会被后者覆盖,浅色那半的断言就形同虚设。
 */
function block(selector: string): string {
  const start = css.indexOf(selector + ' {')
  if (start < 0) throw new Error(`tokens.css 里找不到选择器 ${selector}`)
  const open = css.indexOf('{', start)
  let depth = 0
  for (let i = open; i < css.length; i++) {
    if (css[i] === '{') depth++
    else if (css[i] === '}') {
      depth--
      if (depth === 0) return css.slice(open + 1, i)
    }
  }
  throw new Error(`选择器 ${selector} 的块没有闭合`)
}

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

const rootVars = cssVars(block(':root'))
const darkVars = cssVars(block("[data-theme='dark']"))

/** 逐字段比对:Dart 的 Color 表 ↔ 某个 CSS 块(名称 kebab 化后加 --color- 前缀)。 */
function expectColorsMatch(
  src: Record<string, [number, number, number, number]>,
  vars: Record<string, [number, number, number, number]>,
  where: string,
) {
  for (const [name, expected] of Object.entries(src)) {
    const actual = vars['color-' + kebab(name)]
    expect(actual, `${where}:--color-${kebab(name)} 缺失`).toBeDefined()
    // RGB 必须逐通道精确相等:容差一旦放宽到 1,单个色阶的改动就抓不住了
    expect([actual[0], actual[1], actual[2]], `${where}:--color-${kebab(name)} 的 RGB`).toEqual([
      expected[0],
      expected[1],
      expected[2],
    ])
    // alpha 在 CSS 里写成百分比,四舍五入会差 1/255
    expect(
      Math.abs(actual[3] - expected[3]),
      `${where}:--color-${kebab(name)} 的 alpha`,
    ).toBeLessThanOrEqual(1)
  }
}

describe('心跳 token:Web 与 App 数值必须一致', () => {
  it('色板(浅色 :root ↔ app_colors.dart)', () => {
    const src = dartColors(dart('app_colors.dart'))
    // app_colors.dart 里有 14 个 Color(0x……) 字面量(success/warning 是 green/amber 的别名,不产生变量)
    expect(Object.keys(src).length).toBeGreaterThanOrEqual(14)
    expectColorsMatch(src, rootVars.colors, ':root')
  })

  it('色板(暗色 [data-theme="dark"] ↔ heart_colors.dart 的 HeartDarkColors)', () => {
    const src = dartColors(dart('heart_colors.dart'))
    // HeartDarkColors 是暗色值的唯一事实来源;HeartColors.light 只引用 AppColors,不产生字面量
    expect(Object.keys(src).length, 'HeartDarkColors 字段数应为 14').toBe(14)
    expectColorsMatch(src, darkVars.colors, 'dark')
  })

  it('暗色块必须覆盖 :root 的每一个色板变量(漏一个即暗色残留浅色块)', () => {
    const lightNames = Object.keys(rootVars.colors)
      .filter((n) => n.startsWith('color-'))
      .sort()
    const darkNames = Object.keys(darkVars.colors)
      .filter((n) => n.startsWith('color-'))
      .sort()
    // dark 允许比 root 多(派生色如 focus-ring 也反相),但不能少
    for (const name of lightNames) {
      expect(darkNames, `暗色块缺 --${name}`).toContain(name)
    }
  })

  it('间距', () => {
    const src = dartNumbers(dart('app_spacing.dart'))
    expect(Object.keys(src).length).toBe(9) // 防止解析失败导致空跑通过
    for (const [name, expected] of Object.entries(src)) {
      expect(rootVars.numbers['space-' + kebab(name)], `--space-${kebab(name)} 缺失`).toBe(expected)
    }
  })

  it('圆角', () => {
    const src = dartNumbers(dart('app_radius.dart'))
    expect(Object.keys(src).length).toBe(8)
    for (const [name, expected] of Object.entries(src)) {
      expect(rootVars.numbers['radius-' + kebab(name)], `--radius-${kebab(name)} 缺失`).toBe(expected)
    }
  })

  it('动效时长', () => {
    const src = dartNumbers(dart('app_motion.dart'))
    expect(Object.keys(src).length).toBe(6)
    for (const [name, expected] of Object.entries(src)) {
      expect(rootVars.numbers['motion-' + kebab(name)], `--motion-${kebab(name)} 缺失`).toBe(expected)
    }
  })
})
