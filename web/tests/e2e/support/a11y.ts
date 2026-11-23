import AxeBuilder from '@axe-core/playwright'
import { expect, type Page } from '@playwright/test'

/**
 * 无障碍冒烟(E-3.3):主流程页面 axe 零 **critical**。
 *
 * 为什么只卡 critical:axe 的 impact 分四档(critical / serious / moderate / minor)。
 * critical 是「屏幕阅读器完全无法使用该控件」那一档(按钮没有可访问名、aria 属性拼错、
 * 焦点陷阱写坏……),这一类必须零容忍;serious 里最大宗是配色对比度,归
 * `scripts/design_contrast.py --check` 与 spec §3.4 管(App 与 Web 用同一套阈值),
 * 在这里重判一遍只会得到两份口径。其余档位先只观测、不拦,等 E-5 逐页迁移时收紧。
 *
 * 用法:在每个"页面已经稳定渲染"的位置调一次(空态/加载态下扫描会得到噪声),
 * `where` 写人话(「登录页」),失败时报告里直接能看出是哪一页。
 */
export async function expectNoCriticalA11y(page: Page, where: string): Promise<void> {
  const { violations } = await new AxeBuilder({ page }).analyze()
  const critical = violations.filter((violation) => violation.impact === 'critical')
  const detail = critical
    .map(
      (violation) =>
        `- [${violation.id}] ${violation.help}\n`
        + violation.nodes.map((node) => `    ${node.target.join(' ')}`).join('\n'),
    )
    .join('\n')
  expect(critical, `${where} 有 ${critical.length} 条 critical 级无障碍违规:\n${detail}`)
    .toHaveLength(0)
}
