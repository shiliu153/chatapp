import type { PrimeVuePTOptions } from 'primevue/config'

/**
 * 「余烬 Ember」→ PrimeVue 无样式模式的 pass-through 映射。
 *
 * 为什么用无样式模式(PrimeVue `unstyled: true`):组件行为、键盘交互、焦点陷阱、
 * ARIA 这些东西 PrimeVue 已经做对了,而视觉要 100% 由 `design/tokens/*.json` 决定。
 * 无样式模式把两者切开:PrimeVue 只产结构,样式全部从下面这张表 + CSS 变量来。
 *
 * 三条硬约束(不遵守会被 `tests/unit/primevue-pass-through.spec.ts` 判红):
 *
 * 1. **只引用 CSS 变量,不写值**。每个声明值必须是单个 `var(--…)`,且该变量必须
 *    存在于 `src/styles/tokens.generated.css`。写死的色值、写死的尺寸都算违规 ——
 *    值一旦散进 TS,暗色模式与对比度门禁就都管不到它了。
 * 2. 需要"组合值"(阴影、径向光晕、两段式 padding)时,先在 CSS 里定义成变量再引用;
 *    本文件不接受复合表达式。
 * 3. 只映射 spec §8.2 / §8.3 已经给值的**常态**那一格。状态(pressed / focus /
 *    disabled / loading)由页面的 CSS 类负责 —— pt 只能给内联样式,没有伪类可用,
 *    写成内联反而会盖住状态样式。
 *
 * 未覆盖的一处口径缺口(留给 E-5 补 token,不要在页面里临时写死):
 * Toast 的「遮罩底 + 白字」在 spec §8.3 有值,但 `design/tokens/` 里没有
 * `on-overlay` 这一对语义 token(现有 `overlay.scrim` 只有底色),深色模式下
 * 也没有可用的浅色文字 token 能与它配对,所以 toast 的文字色**故意不在这里给**。
 */

/** 把一个组件的某一 part 写成"只含变量引用"的内联样式。 */
const style = (decls: Record<string, string>) => ({ style: decls })

export const emberPassThrough: PrimeVuePTOptions = {
  /**
   * 主按钮(spec §8.2「主按钮」):brand 实底 + brand.on 文字 16/w700,高 52,胶囊圆角。
   * `emberGlow` 光晕是径向光 + 按压 scale,靠页面的类实现,见 §8.3「pressed」。
   */
  button: {
    root: style({
      background: 'var(--color-brand-default)',
      color: 'var(--color-brand-on)',
      borderRadius: 'var(--radius-pill)',
      fontFamily: 'var(--font-family-body)',
      fontSize: 'var(--font-size-body)',
      fontWeight: 'var(--font-weight-bold)',
      height: 'var(--size-control-height)',
    }),
    label: style({ fontWeight: 'var(--font-weight-bold)' }),
  },

  /** 输入框(spec §8.3「输入框 default」):surface.card 底 + 1px divider 描边 + radius.md + 高 52。 */
  inputtext: {
    root: style({
      background: 'var(--color-surface-card)',
      borderColor: 'var(--color-border-divider)',
      borderRadius: 'var(--radius-md)',
      color: 'var(--color-text-primary)',
      fontFamily: 'var(--font-family-body)',
      fontSize: 'var(--font-size-body)',
      height: 'var(--size-control-height)',
    }),
  },

  /** 多行输入:口径同输入框(§8.3 只有一张「输入框」表,textarea 跟随)。 */
  textarea: {
    root: style({
      background: 'var(--color-surface-card)',
      borderColor: 'var(--color-border-divider)',
      borderRadius: 'var(--radius-md)',
      color: 'var(--color-text-primary)',
      fontFamily: 'var(--font-family-body)',
      fontSize: 'var(--font-size-body)',
    }),
  },

  /** 卡片(spec §8.3「卡片 default」):surface.card + radius.lg + elev.1 + 内边距 20;标题走 display 字族。 */
  card: {
    root: style({
      background: 'var(--color-surface-card)',
      borderRadius: 'var(--radius-lg)',
      boxShadow: 'var(--elevation-1)',
    }),
    body: style({ padding: 'var(--space-20)' }),
    title: style({
      color: 'var(--color-text-primary)',
      fontFamily: 'var(--font-family-display)',
      fontSize: 'var(--font-size-title)',
      fontWeight: 'var(--font-weight-semibold)',
    }),
  },

  /** 头像(spec §8.2「头像」):一律圆形;在线点与「新配对」光晕环由页面按状态画。 */
  avatar: {
    root: style({ borderRadius: 'var(--radius-pill)' }),
  },

  /** 角标(spec §8.3「角标 default」):brand 实底 + brand.on 字 11/w700 + 胶囊。 */
  badge: {
    root: style({
      background: 'var(--color-brand-default)',
      borderRadius: 'var(--radius-pill)',
      color: 'var(--color-brand-on)',
      fontSize: 'var(--font-size-micro)',
      fontWeight: 'var(--font-weight-bold)',
    }),
  },

  /** Chip(spec §8.3「Chip default」):未选中态 surface.sunken + text.secondary;选中态由页面加类。 */
  chip: {
    root: style({
      background: 'var(--color-surface-sunken)',
      borderRadius: 'var(--radius-pill)',
      color: 'var(--color-text-secondary)',
      fontSize: 'var(--font-size-caption)',
    }),
  },

  /**
   * 弹层(spec §8.3「Sheet default」):surface.card + 上圆角 24 + scrim 遮罩。
   * 拖把(36×4)是内容区的装饰元素,由页面画,不属于 PrimeVue 的 part。
   */
  dialog: {
    root: style({
      background: 'var(--color-surface-card)',
      borderTopLeftRadius: 'var(--radius-xl)',
      borderTopRightRadius: 'var(--radius-xl)',
      color: 'var(--color-text-primary)',
    }),
    header: style({ padding: 'var(--space-20)' }),
    title: style({
      fontFamily: 'var(--font-family-display)',
      fontSize: 'var(--font-size-title)',
      fontWeight: 'var(--font-weight-semibold)',
    }),
    mask: style({ background: 'var(--color-overlay-scrim)' }),
  },

  /**
   * Toast(spec §8.3「Toast default」):scrim 底 + radius.md + 13 号字。
   * 文字色缺 token(见文件顶部「口径缺口」),故意留空。
   */
  toast: {
    root: style({
      background: 'var(--color-overlay-scrim)',
      borderRadius: 'var(--radius-md)',
      fontFamily: 'var(--font-family-body)',
      fontSize: 'var(--font-size-caption)',
    }),
  },

  /** 骨架屏(spec §8.3「骨架 default」):surface.sunken 色块;透明度循环由页面动画负责。 */
  skeleton: {
    root: style({
      background: 'var(--color-surface-sunken)',
      borderRadius: 'var(--radius-sm)',
    }),
  },
}
