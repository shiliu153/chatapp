import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import stylelint from 'stylelint'
import { describe, expect, it } from 'vitest'

/**
 * 「裸值」门禁(Web 侧)的行为自测 —— 门禁本体是 `web/.stylelintrc.json`
 * + `npm run lint:styles`(门禁 `web-raw-values`)。
 *
 * 为什么要有这条 spec:App 侧的同构门禁 `scripts/check_app_raw_values.py` 有
 * `scripts/test_check_app_raw_values.py` 钉住「四类裸值都判红、误报方向不误伤」;
 * Web 侧的判据住在 stylelint 配置里,配置本身**不会自己喊**:把某条规则删掉、把
 * `ignoreFiles` 加宽、把 `.vue` 的 customSyntax 去掉,门禁都会**静默变绿**。
 * 这条 spec 把 Judge 真的跑一遍,判的是「配置现在到底判不判」,而不是「配置写了什么」
 * (后者由 `scripts/check_web_raw_values.py --check` 在 contract 轨守)。
 *
 * 判据口径与 App 侧逐条对齐(Ember §11.2 的「裸值」一行):
 *
 * | 类别 | App(`check_app_raw_values.py`) | Web(本文件 + `.stylelintrc.json`) |
 * |---|---|---|
 * | 裸 hex | `0x` + 6/8 位十六进制 | `color-no-hex` |
 * | 裸非法色值 | —— | `color-no-invalid-hex` |
 * | 裸 `rgb()` / `hsl()` | —— | `function-disallowed-list`(rgb / rgba / hsl / hsla) |
 * | 裸字号 | `fontSize: 17` | `font-size` / `font` 上的 `px/rem/em/pt/vh/vw` |
 * | 裸间距 | `EdgeInsets.all(16)` | `padding*` / `margin*` / `gap` 上的同类单位 |
 * | 裸圆角 | `BorderRadius.circular(9)` | `border-radius*` 上的同类单位 |
 *
 * 两条与 App 侧一致的例外:
 * 1. **`0` 不算裸值**(CSS 里 `0` 本来就没有单位,自然通过);
 * 2. **由 token 派生的表达式不算裸值** —— `var(--space-4)`(App 侧对应 `tokens.space4`)、
 *    `calc(var(--space-4) / 2)`(对应 `tokens.space4 / 2`)、`color-mix(... var(--x) ...)`、
 *    百分比、`auto`、`inherit` 一律放行。
 *
 * 白名单:逐处 `/* stylelint-disable-next-line <rule> -- 原因;到期:… *\/` 行内注释,
 * 不是整条规则豁免 —— 带原因由 `--report-descriptionless-disables` 机械要求,
 * 存量清掉后忘删由 `--report-needless-disables` 机械判红(对应 App 侧的「白名单条目
 * 在文件里找不到片段即判红」)。
 */

const WEB_ROOT = process.cwd()

/** 一支「假的」源文件路径:stylelint 只用它决定配置发现与 `overrides` 匹配,不读文件。 */
function fixturePath(name: string): string {
  return resolve(WEB_ROOT, 'src', name)
}

/** 把一段样式包成 `.vue` 的 `<style>` 块(与真实页面的写法一致)。 */
function vue(source: string): string {
  return `<template>\n  <div class="a" />\n</template>\n\n<style scoped>\n${source}\n</style>\n`
}

/** 跑一次门禁判据,返回命中的规则 id(去重、排序,便于断言)。 */
async function rulesOf(source: string, name = '__fixture__.vue'): Promise<string[]> {
  const result = await stylelint.lint({
    code: source,
    codeFilename: fixturePath(name),
    reportNeedlessDisables: true,
    reportDescriptionlessDisables: true,
    reportInvalidScopeDisables: true,
    maxWarnings: 0,
  })
  const warnings = result.results.flatMap((item) => item.warnings)
  return [...new Set(warnings.map((warning) => String(warning.rule)))].sort()
}

const UNIT_RULE = 'declaration-property-unit-disallowed-list'

describe('裸值门禁(Web):三类裸值必须判红', () => {
  it('裸 hex / 裸字号 / 裸间距 一处都不放过', async () => {
    const rules = await rulesOf(vue('.a {\n  color: #FF0000;\n  font-size: 13px;\n  padding: 7px;\n}'))
    expect(rules).toEqual([UNIT_RULE, 'color-no-hex'].sort())
  })

  it('裸圆角、裸 margin、裸 rgb()/hsl() 同样判红', async () => {
    const rules = await rulesOf(
      vue('.a {\n  border-radius: 9px;\n  margin: 8px auto;\n  background: rgb(255 0 0);\n  color: hsl(0 0% 0%);\n}'),
    )
    expect(rules).toEqual([UNIT_RULE, 'function-disallowed-list'].sort())
  })

  it('独立 .css 文件走同一套判据(不只在 .vue 的 style 块里生效)', async () => {
    const rules = await rulesOf('.a {\n  gap: 2px;\n  font-size: 12px;\n}', '__fixture__.css')
    expect(rules).toEqual([UNIT_RULE])
  })

  it('非法的 hex 写法也判(不是「写了十六进制就算过」)', async () => {
    const rules = await rulesOf(vue('.a {\n  color: #12345;\n}'))
    expect(rules).toContain('color-no-invalid-hex')
  })
})

describe('裸值门禁(Web):token 派生写法不得误报', () => {
  it('var() / calc() / color-mix() / 0 / 百分比 / auto / inherit 全部放行', async () => {
    const rules = await rulesOf(
      vue(
        [
          '.a {',
          '  padding: var(--space-4) var(--space-8);',
          '  margin: 0 auto;',
          '  gap: calc(var(--space-4) / 2);',
          '  border-radius: 50%;',
          '  font-size: var(--text-body);',
          '  font-family: inherit;',
          '  color: color-mix(in srgb, var(--color-text-primary) 45%, transparent);',
          '  background: var(--color-surface-card);',
          '}',
        ].join('\n'),
      ),
    )
    expect(rules).toEqual([])
  })

  it('白名单:带「原因 + 到期」的 next-line 放行,且不判「多余」', async () => {
    const rules = await rulesOf(
      vue(
        [
          '.a {',
          `  /* stylelint-disable-next-line ${UNIT_RULE} -- 2px 无对应档位(space 从 4 起);到期:E-5 迁移该页时清掉 */`,
          '  gap: 2px;',
          '}',
        ].join('\n'),
      ),
    )
    expect(rules).toEqual([])
  })
})

describe('裸值门禁(Web):白名单只增不减、不能静默扩豁免', () => {
  it('没有原因(说明)的放行判红', async () => {
    const rules = await rulesOf(
      vue(['.a {', `  /* stylelint-disable-next-line ${UNIT_RULE} */`, '  gap: 2px;', '}'].join('\n')),
    )
    expect(rules).toContain('--report-descriptionless-disables')
  })

  it('存量已清掉却没删的放行判红(对应 App 侧「白名单条目失效」)', async () => {
    const rules = await rulesOf(
      vue(
        [
          '.a {',
          `  /* stylelint-disable-next-line ${UNIT_RULE} -- 这处已经改成 token 了;到期:早就该删 */`,
          '  gap: var(--space-4);',
          '}',
        ].join('\n'),
      ),
    )
    expect(rules).toContain('--report-needless-disables')
  })

  it('放行了不存在的规则判红(敲错的规则名不会变成一张空头豁免)', async () => {
    const rules = await rulesOf(
      vue(
        [' .a {', '  /* stylelint-disable-next-line color-no-shouting -- 敲错的规则名;到期:不适用 */', '  gap: 2px;', '}'].join(
          '\n',
        ),
      ),
    )
    expect(rules).toContain('--report-invalid-scope-disables')
  })
})

describe('裸值门禁(Web):生成物整文件排除', () => {
  it('token 生成物里的成片 hex / rgba 不算违规', async () => {
    // 判的是**真实文件内容**:它是 design/tokens/*.json 的唯一产物,裸值正是它该有的样子。
    // 这条同时钉住 ignoreFiles —— 路径写错会立刻在这里红,而不是在门禁里红成几千条。
    const generated = readFileSync(resolve(WEB_ROOT, 'src/styles/tokens.generated.css'), 'utf8')
    expect(generated).toContain('#B4610C')
    expect(await rulesOf(generated, 'styles/tokens.generated.css')).toEqual([])
  })
})
