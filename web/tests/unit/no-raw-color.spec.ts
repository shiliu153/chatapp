import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * 「禁用裸色值」硬门禁(计划 F-3 / spec §2.1「防回退」)。
 *
 * 为什么必须有它:暗色主题全靠 `[data-theme='dark']` 覆盖 CSS 变量。只要页面里
 * 出现一处裸 `#rrggbb` 或 `rgb(...)`,那块在暗色下就会保持浅色 —— 而且**不会有
 * 任何报错**,只有这条测试会红。
 *
 * 扫描范围:`src/**` 的 .vue / .css / .ts,排除 `src/styles/tokens.css`
 * (那里就是色值的唯一事实来源)。
 *
 * 白名单:纯黑 / 纯白 / 全透明三色(`#fff` / `#ffffff` / `#000` / `#000000` /
 * `rgb(0 0 0)` 等)。它们在两种主题下语义相同,且没有对应语义 token
 * (如照片查看器纯黑底)。
 */
const SRC = resolve(process.cwd(), 'src')
const TOKENS_FILE = resolve(SRC, 'styles/tokens.css')

/** 允许的裸色值(小写比较)。 */
const ALLOWED = new Set([
  '#fff',
  '#ffffff',
  '#000',
  '#000000',
  'rgb(0 0 0)',
  'rgba(0, 0, 0, 1)',
  'rgb(255 255 255)',
  'rgba(255, 255, 255, 1)',
  'transparent',
])

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) {
      if (name === 'node_modules' || name === 'dist') continue
      walk(full, out)
    } else if (/\.(vue|css|ts)$/.test(name)) {
      out.push(full)
    }
  }
  return out
}

const files = walk(SRC).filter((f) => f !== TOKENS_FILE)

/** 逐行找裸色值,返回 `相对路径:行号: 内容` 列表。 */
function findRawColors(): string[] {
  const hex = /#[0-9a-fA-F]{3,8}\b/g
  const rgb = /\brgba?\([^)]*\)/g
  const hits: string[] = []
  for (const file of files) {
    const lines = readFileSync(file, 'utf8').split('\n')
    lines.forEach((line, i) => {
      // 注释里的色值不算(文档注释常引用 §2.1.1 的取值)
      const code = line.replace(/\/\*.*?\*\//g, '').replace(/\/\/.*$/, '')
      for (const re of [hex, rgb]) {
        for (const m of code.matchAll(re)) {
          if (ALLOWED.has(m[0].toLowerCase())) continue
          hits.push(`${relative(SRC, file).replace(/\\/g, '/')}:${i + 1}: ${line.trim()}`)
        }
      }
    })
  }
  return hits
}

describe('禁用裸色值(Web)', () => {
  it('扫描范围非空(防止路径写错导致空跑通过)', () => {
    expect(files.length).toBeGreaterThan(30)
  })

  it('src/**(除 styles/tokens.css)不得出现裸 hex / rgb()', () => {
    const hits = findRawColors()
    expect(
      hits,
      '裸色值请先加进 tokens.css(:root + [data-theme=\'dark\'] 各一份),再引用变量:\n' +
        hits.join('\n'),
    ).toEqual([])
  })
})
