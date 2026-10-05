# 网页端(PC Web)实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: 用 `executing-plans` **内联**逐任务实现(项目全局约定:superpowers 类任务一律内联执行,不派发子 agent)。进度以本文件的 checkbox 为准。每组末尾是检查点:门禁不绿不进下一组。

**Goal:** 交付一个面向桌面浏览器的完整网页端(11 个业务模块、30 个业务接口),与现有 Flutter App 共用同一套 Django REST 后端,视觉严格遵循「心跳」设计语言。

**Architecture:** 新建 `web/`(Vue 3 + Vite + TypeScript SPA)。后端与 App **零改动**;Web 通过 axios 调 `/api/v1`,消息走腾讯云 IM 的**浏览器端无头 SDK** `@tencentcloud/chat`(Flutter 插件编不到 Web,实测见 spec §2)。状态用 Pinia,一路由一 store 一领域;视觉用 CSS 变量承接「心跳」token。

**Tech Stack:** Vue 3 `<script setup>` · Vite · TypeScript · vue-router(history)· Pinia · axios · 原生 CSS + CSS 变量 · `@tencentcloud/chat` ^3.6.7 · Vitest + @vue/test-utils + MSW · Playwright · npm

**关联文档:** 设计 spec `docs/superpowers/specs/2026-10-05-web-frontend-design.md`;接口契约 `docs/api/`(10 册 32 接口);视觉规则 `docs/superpowers/specs/2026-09-15-ui-design-language-design.md`。

## Global Constraints

以下每条对**所有**任务生效,不再逐任务重复:

- **环境**:Node 22.15.0 / npm 10.9.2(本机已装);依赖用 `npm install` 取当前稳定版,安装后把 major 固化进 `package.json`(不预写可能不存在的版本号);`package-lock.json` 必须入库。
- **零改动红线**:`app/`(Flutter)、`chatapp/`(Django)、`docs/api/` **一行不改**。任何任务若发现必须改后端,停下来找用户确认。
- **跨栈契约**(照抄,不许改):
  - IM 账号 ID = `u{user_id}`;系统通知账号 = `system_notice`
  - 错误响应形状 = `{"code": <HTTP 状态码>, "message": "<中文>", "request_id": "..."}`;业务码前 3 位 = HTTP 状态码
  - `401 + 40101` = 被顶号(单设备登录);`403` = 封禁(`banned_light` 只禁滑卡,`banned_heavy` 全域)
  - Bearer JWT:access 30 分钟 / refresh 30 天,刷新即轮换
- **「心跳」token 双份纪律**:改任何视觉 token,**必须在同一次改动内同时改** `app/lib/core/theme/*.dart` 与 `web/src/styles/tokens.css`;**字体文件同理**(`app/assets/fonts/*.ttf` ↔ `web/public/fonts/*.ttf`)。由 `tokens.spec.ts` 的对照测试兜底。
- **禁止裸值**:Web 端新代码不出现裸 hex、裸字号、裸间距;比例值也进 token。
- **门禁(每组结束必须全绿)**:`npm run type-check`(vue-tsc 零错误)+ `npm run lint`(零错误)+ `npm run test:run`(Vitest 全绿)。
- **提交**:每个 Task 结束提交一次,Conventional Commits + 中文,例如 `feat(web): 登录页与验证码倒计时`。
- **不做**(spec §15):手机浏览器适配、暗色模式、SSR/SEO、Web 推送、多设备同时在线、官方 IM UIKit、完整无障碍。
- **测试纪律**:测试替身只在**网络层**(MSW)与**IM 层**(假 IM 客户端);组件、store、路由都跑真实实现。

---

## 文件结构总览

```
web/
├── index.html                      # 挂载点 + 站点标题/描述
├── package.json / package-lock.json / tsconfig.json / vite.config.ts / vitest.config.ts
├── eslint.config.js / .prettierrc / .gitignore
├── .env.development                # VITE_API_BASE=/api/v1(走 Vite proxy)
├── .env.production                 # VITE_API_BASE=/api/v1(同域,nginx 反代)
├── public/fonts/                   # SpaceGrotesk-{Regular,Medium,Bold}.ttf + OFL.txt(与 app 同源)
├── src/
│   ├── main.ts                     # createApp + pinia + router
│   ├── App.vue                     # RouterView + 全局浮层(AppKickedOverlay)
│   ├── constants.ts                # APP_NAME、下载入口开关等全局常量
│   ├── api/
│   │   ├── http.ts                 # axios 实例 + 请求/响应拦截器(含 401 刷新通道)
│   │   ├── error.ts                # ApiError 类型与错误信封解析
│   │   ├── types.ts                # 接口出入参 TS 类型
│   │   ├── auth.ts / users.ts / discovery.ts / im.ts / feed.ts / moderation.ts / presence.ts
│   ├── stores/
│   │   ├── session.ts              # 令牌、当前用户 id、登录/登出/启动恢复
│   │   ├── profile.ts / discovery.ts / chat.ts / feed.ts / presence.ts
│   ├── im/
│   │   ├── client.ts               # @tencentcloud/chat 初始化/登录/事件总线
│   │   ├── map.ts                  # SDK 消息 → ChatMessage 纯函数映射(可单测)
│   │   └── types.ts                # ChatMessage / ImConversation / ImEvent
│   ├── styles/
│   │   ├── tokens.css              # 「心跳」token(CSS 变量)
│   │   └── base.css                # 重置、@font-face、焦点圈、滚动条
│   ├── components/                 # AppButton/AppInput/AppCard/AppAvatar/AppBadge/AppSkeleton/AppEmpty/AppErrorView/AppKickedOverlay
│   ├── composables/
│   │   ├── useDevice.ts            # 移动端判定(UA/platform/maxTouchPoints)
│   │   ├── useSidebar.ts           # 侧栏宽度状态、拖拽、阈值、记忆
│   │   └── useHeartbeat.ts         # 45s 在线心跳(含 visibilitychange)
│   ├── layouts/
│   │   ├── DesktopShell.vue        # PC 壳层(可拖拽侧栏 + 内容区)
│   │   └── MobileGuard.vue         # 移动端引导页
│   ├── router/index.ts             # 路由表 + 守卫
│   └── features/                   # auth onboarding discovery chat square profile settings moderation legal dev
└── tests/
    ├── unit/                       # tokens/http/session/useDevice/useSidebar/im.map
    ├── component/                  # 组件与页面(MSW 假网络)
    └── e2e/                        # Playwright
```

---

## 组 T1:工程骨架与设计底座(7 个任务)

产出:一个能 `npm run dev` 打开的空壳应用 + 与 App 数值一致的「心跳」token + 8 个基础组件 + 开发期组件展示页。

### Task 1.1:初始化 Vite + Vue3 + TS 工程与测试骨架

**Files:**
- Create: `web/package.json`、`web/vite.config.ts`、`web/vitest.config.ts`、`web/tsconfig.json`、`web/tsconfig.node.json`、`web/index.html`、`web/.gitignore`、`web/.env.development`、`web/.env.production`、`web/eslint.config.js`、`web/.prettierrc`、`web/src/main.ts`、`web/src/App.vue`、`web/src/constants.ts`
- Test: `web/tests/unit/smoke.spec.ts`

**Interfaces:**
- Produces: `APP_NAME`(常量,值为 `'心跳'`)、`DOWNLOADS_ENABLED = false`(下载入口开关,商店上架后改 `true`)、脚本 `dev` / `build` / `preview` / `type-check` / `lint` / `test` / `test:run`

- [ ] **Step 1:建目录与配置文件**

`web/package.json`(先写脚本与元信息,依赖下一步装):

```json
{
  "name": "chatapp-web",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vue-tsc --noEmit && vite build",
    "preview": "vite preview",
    "type-check": "vue-tsc --noEmit",
    "lint": "eslint . --max-warnings 0",
    "test": "vitest",
    "test:run": "vitest run"
  }
}
```

`web/vite.config.ts`:

```ts
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: {
      // 开发期同域:前端 /api/v1 → 本机 Django,避免跨域
      '/api/v1': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/media': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
```

`web/tsconfig.json`(严格模式):

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "jsx": "preserve",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "types": ["vitest/globals", "node"],
    "baseUrl": ".",
    "paths": { "@/*": ["./src/*"] },
    "noEmit": true,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "isolatedModules": true
  },
  "include": ["src/**/*.ts", "src/**/*.vue", "tests/**/*.ts", "*.config.ts"]
}
```

`web/.gitignore`:`node_modules/`、`dist/`、`coverage/`、`.vite/`、`test-results/`、`playwright-report/`

`web/.env.development` 与 `web/.env.production` 都写:

```
VITE_API_BASE=/api/v1
```

`web/index.html`:

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>心跳</title>
    <meta name="description" content="心跳 —— 认真交友" />
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.ts"></script>
  </body>
</html>
```

- [ ] **Step 2:安装依赖**

```bash
cd web
npm install vue vue-router pinia axios @tencentcloud/chat
npm install -D vite @vitejs/plugin-vue typescript vue-tsc vitest @vue/test-utils jsdom msw eslint @eslint/js typescript-eslint eslint-plugin-vue globals prettier @playwright/test
```

装完后**核对 `package.json` 里各依赖的 major 版本**,若有与计划假设不符(例如 Vite 8、Vitest 4)以实际安装为准,并在本任务提交信息里写明。

- [ ] **Step 3:写失败的冒烟测试**

`web/tests/unit/smoke.spec.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { APP_NAME, DOWNLOADS_ENABLED } from '@/constants'

describe('工程冒烟', () => {
  it('应用名与设计语言一致', () => {
    expect(APP_NAME).toBe('心跳')
  })

  it('商店未上架前下载入口关闭', () => {
    expect(DOWNLOADS_ENABLED).toBe(false)
  })
})
```

`web/vitest.config.ts`:

```ts
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  test: {
    globals: true,
    environment: 'jsdom',
    include: ['tests/**/*.spec.ts'],
    exclude: ['tests/e2e/**'],
  },
})
```

- [ ] **Step 4:跑测试确认失败**

Run: `cd web && npm run test:run`
Expected: FAIL —— 找不到模块 `@/constants`

- [ ] **Step 5:写最小实现**

`web/src/constants.ts`:

```ts
/** 应用名(与 App、软著、备案名保持一致,改名要全栈同步)。 */
export const APP_NAME = '心跳'

/** 移动端引导页的「下载 App」入口开关:商店上架后改 true 即出现真实入口。 */
export const DOWNLOADS_ENABLED = false

/** 在线心跳间隔(毫秒),与 App 一致。 */
export const HEARTBEAT_INTERVAL_MS = 45_000
```

`web/src/App.vue`(本任务先最小,`AppKickedOverlay` 在 Task 2.3 加):

```vue
<script setup lang="ts"></script>

<template>
  <RouterView />
</template>
```

`web/src/main.ts`:

```ts
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { router } from './router'

createApp(App).use(createPinia()).use(router).mount('#app')
```

`src/router` 与样式在 Task 1.2/1.3/3.1 补齐;本步骤先建一个占位路由文件,保证能编译:

`web/src/router/index.ts`:

```ts
import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory(),
  routes: [{ path: '/', component: { template: '<div />' } }],
})
```

- [ ] **Step 6:跑测试确认通过**

Run: `cd web && npm run test:run && npm run type-check`
Expected: 2 passed;type-check 无输出(零错误)

- [ ] **Step 7:提交**

```bash
git add web
git commit -m "feat(web): 初始化 Vue3+Vite+TS 工程与测试骨架"
```

### Task 1.2:「心跳」token 移植为 CSS 变量 + 对照测试

**Files:**
- Create: `web/src/styles/tokens.css`
- Test: `web/tests/unit/tokens.spec.ts`

**Interfaces:**
- Produces: 全部 CSS 变量(下表)。后续所有组件的样式**只能**引用这些变量。
- Consumes: Task 1.1 的 vitest 配置。

**权威来源**:`app/lib/core/theme/{app_colors,app_gradients,app_typography,app_spacing,app_radius,app_motion,app_shadows}.dart`(已读,数值照抄)。

- [ ] **Step 1:写失败的对照测试**

`web/tests/unit/tokens.spec.ts`——它把 Dart 常量与 CSS 变量两边都解析出来比对,是「双份纪律」的机器兜底:

```ts
import { readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'
import { describe, expect, it } from 'vitest'

const themeDir = fileURLToPath(new URL('../../../app/lib/core/theme/', import.meta.url))
const dart = (f: string) => readFileSync(themeDir + f, 'utf8')
const css = readFileSync(fileURLToPath(new URL('../../src/styles/tokens.css', import.meta.url)), 'utf8')

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
    const px = value.match(/^(\d+(?:\.\d+)?)px$/)
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
  it('色板(含 alpha,容差 1/255)', () => {
    const src = dartColors(dart('app_colors.dart'))
    // app_colors.dart 里有 14 个 Color(0x……) 字面量(success/warning 是 green/amber 的别名,不产生变量)
    expect(Object.keys(src).length).toBeGreaterThanOrEqual(14)
    for (const [name, expected] of Object.entries(src)) {
      const actual = vars.colors['color-' + kebab(name)]
      expect(actual, `--color-${kebab(name)} 缺失`).toBeDefined()
      expected.forEach((channel, i) => {
        expect(Math.abs(actual[i] - channel), `--color-${kebab(name)} 第 ${i} 通道`).toBeLessThanOrEqual(1)
      })
    }
  })

  it('间距', () => {
    const src = dartNumbers(dart('app_spacing.dart'))
    for (const [name, expected] of Object.entries(src)) {
      expect(vars.numbers['space-' + kebab(name)], `--space-${kebab(name)} 缺失`).toBe(expected)
    }
  })

  it('圆角', () => {
    const src = dartNumbers(dart('app_radius.dart'))
    for (const [name, expected] of Object.entries(src)) {
      expect(vars.numbers['radius-' + kebab(name)], `--radius-${kebab(name)} 缺失`).toBe(expected)
    }
  })

  it('动效时长', () => {
    const src = dartNumbers(dart('app_motion.dart'))
    for (const [name, expected] of Object.entries(src)) {
      expect(vars.numbers['motion-' + kebab(name)], `--motion-${kebab(name)} 缺失`).toBe(expected)
    }
  })
})
```

- [ ] **Step 2:跑测试确认失败**

Run: `cd web && npm run test:run tests/unit/tokens.spec.ts`
Expected: FAIL —— 读不到 `src/styles/tokens.css`

- [ ] **Step 3:写 tokens.css(数值从 Dart 照抄)**

```css
/* 「心跳」设计语言 token —— 权威来源 app/lib/core/theme/*.dart
   ⚠️ 改这里必须同一次改动内改 Dart 那边(由 tests/unit/tokens.spec.ts 兜底)。 */
:root {
  /* 色板 app_colors.dart */
  --color-brand: #ff2c55;
  --color-violet: #7c5cff;
  --color-green: #12c48b;
  --color-amber: #ffb020;
  --color-text1: #16181d;
  --color-text2: #8a8f9e;
  --color-text3: #b3b7c0;
  --color-divider: #eef0f4;
  --color-bg-page: #f6f7fb;
  --color-bg-card: #ffffff;
  --color-danger: #fa5151;
  --color-heart-orange: #ff7a45;
  --color-system-blue: #4f8cff;
  /* photoScrim = Color(0xDE101114):alpha 222/255 = 87% */
  --color-photo-scrim: rgb(16 17 20 / 87%);

  /* 渐变 app_gradients.dart(135° = 左上→右下) */
  --gradient-heart: linear-gradient(135deg, var(--color-brand), var(--color-heart-orange));
  --gradient-system: linear-gradient(135deg, var(--color-violet), var(--color-system-blue));

  /* 间距 app_spacing.dart */
  --space-xs: 4px;
  --space-sm: 8px;
  --space-md: 12px;
  --space-lg: 16px;
  --space-xl: 20px;
  --space-xxl: 24px;
  --space-page-h: 16px;
  --space-card-gap: 12px;
  --space-section-gap: 24px;

  /* 圆角 app_radius.dart */
  --radius-card: 20px;
  --radius-input: 16px;
  --radius-chip: 8px;
  --radius-sheet: 24px;
  --radius-discovery-card: 24px;
  --radius-bubble: 18px;
  --radius-image: 12px;
  --radius-full: 999px;

  /* 动效 app_motion.dart(曲线取 Flutter 同名曲线的 CSS 近似) */
  --motion-fast: 150ms;
  --motion-base: 220ms;
  --motion-medium: 320ms;
  --motion-hero: 380ms;
  --motion-cinematic: 1200ms;
  --motion-loop: 1200ms;
  --ease-out: cubic-bezier(0.215, 0.61, 0.355, 1);      /* easeOutCubic */
  --ease-out-back: cubic-bezier(0.175, 0.885, 0.32, 1.275); /* easeOutBack */

  /* 阴影 app_shadows.dart */
  --shadow-card: 0 6px 18px rgb(22 24 29 / 6%);
  --shadow-floating-bar: 0 10px 24px rgb(22 24 29 / 10%);
  --shadow-primary-button: 0 10px 24px rgb(255 44 85 / 35%);

  /* 字阶 app_typography.dart 的 size/weight/letter-spacing/line-height */
  --font-latin: 'Space Grotesk', 'PingFang SC', 'MiSans', 'HarmonyOS Sans', sans-serif;
  --text-display: 32px;
  --text-title: 20px;
  --text-subtitle: 16px;
  --text-body: 15px;
  --text-caption: 13px;
  --text-micro: 12px;
  --text-badge: 11px;
  --text-emoji: 72px;
  --weight-regular: 400;
  --weight-medium: 500;
  --weight-semibold: 600;
  --weight-bold: 700;
  --weight-extrabold: 800;
  --leading-tight: 1.2;
  --leading-body: 1.45;

  /* Web 新增维度(spec §6.4):焦点圈用中性色,避免一屏两个高音 */
  --color-focus-ring: rgb(22 24 29 / 45%);
  --hover-overlay: rgb(22 24 29 / 4%);
  --hover-overlay-strong: rgb(22 24 29 / 8%);

  /* 自适应布局比例(spec §6.2/§6.3;Web 专属,无 Dart 对照) */
  --sidebar-ratio: 16%;
  --sidebar-min: 208px;
  --sidebar-max: 264px;
  --sidebar-drag-min: 72px;
  --sidebar-drag-max: 360px;
  --sidebar-icon-threshold: 176px;
  --chatlist-ratio: 22%;
  --chatlist-min: 264px;
  --chatlist-max: 360px;
  --bubble-max-ratio: 72%;
  --feed-card-max: 520px;
  --form-card-ratio: 32%;
  --form-card-min: 420px;
  --form-card-max: 520px;
}
```

- [ ] **Step 4:跑测试确认通过**

Run: `cd web && npm run test:run tests/unit/tokens.spec.ts`
Expected: 4 passed(色板/间距/圆角/动效)

- [ ] **Step 5:提交**

```bash
git add web/src/styles/tokens.css web/tests/unit/tokens.spec.ts
git commit -m "feat(web): 心跳 token 移植为 CSS 变量 + Dart 对照测试"
```

### Task 1.3:全局样式、字体与焦点圈

**Files:**
- Create: `web/src/styles/base.css`、`web/public/fonts/`(3 个 ttf + OFL.txt,从 `app/assets/fonts/` 复制)、`web/tests/unit/fonts.spec.ts`
- Modify: `web/src/main.ts`(引入两个样式文件)

**Interfaces:**
- Consumes: Task 1.2 的 token 变量。
- Produces: 全局字体栈、`*:focus-visible` 焦点圈、滚动条样式;`tests/unit/fonts.spec.ts` 守字体同步。

- [ ] **Step 1:复制字体并写失败的同步测试**

```bash
mkdir -p web/public/fonts
cp app/assets/fonts/SpaceGrotesk-Regular.ttf app/assets/fonts/SpaceGrotesk-Medium.ttf app/assets/fonts/SpaceGrotesk-Bold.ttf app/assets/fonts/OFL.txt web/public/fonts/
```

`web/tests/unit/fonts.spec.ts`:

```ts
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'
import { describe, expect, it } from 'vitest'

const sha = (p: string) => createHash('sha256').update(readFileSync(p)).digest('hex')
const appFont = (n: string) => fileURLToPath(new URL(`../../../app/assets/fonts/${n}`, import.meta.url))
const webFont = (n: string) => fileURLToPath(new URL(`../../public/fonts/${n}`, import.meta.url))

describe('字体文件与 App 同源', () => {
  for (const name of ['SpaceGrotesk-Regular.ttf', 'SpaceGrotesk-Medium.ttf', 'SpaceGrotesk-Bold.ttf']) {
    it(`${name} 内容一致`, () => {
      expect(sha(webFont(name))).toBe(sha(appFont(name)))
    })
  }
})
```

- [ ] **Step 2:跑测试确认通过(文件已复制)**

Run: `cd web && npm run test:run tests/unit/fonts.spec.ts`
Expected: 3 passed。**故意改坏一个字节会红** —— 这就是这道门禁的意义。

- [ ] **Step 3:写 base.css**

```css
/* 全局重置、字体、焦点圈。数值只引用 tokens.css 的变量。 */
@font-face {
  font-family: 'Space Grotesk';
  src: url('/fonts/SpaceGrotesk-Regular.ttf') format('truetype');
  font-weight: 400;
  font-display: swap;
}
@font-face {
  font-family: 'Space Grotesk';
  src: url('/fonts/SpaceGrotesk-Medium.ttf') format('truetype');
  font-weight: 500;
  font-display: swap;
}
@font-face {
  font-family: 'Space Grotesk';
  src: url('/fonts/SpaceGrotesk-Bold.ttf') format('truetype');
  font-weight: 700;
  font-display: swap;
}

* { box-sizing: border-box; }

html, body, #app { height: 100%; margin: 0; }

body {
  font-family: var(--font-latin);
  font-size: var(--text-body);
  font-weight: var(--weight-medium);
  line-height: var(--leading-body);
  color: var(--color-text1);
  background: var(--color-bg-page);
  -webkit-font-smoothing: antialiased;
}

button { font: inherit; color: inherit; }

a { color: inherit; text-decoration: none; }

/* 焦点圈:仅键盘聚焦时出现,中性色(不用 brand) */
:focus { outline: none; }
:focus-visible {
  outline: 2px solid var(--color-focus-ring);
  outline-offset: 2px;
}

/* 滚动条:细、中性、悬停加深 */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-thumb {
  background: var(--color-text3);
  border-radius: var(--radius-full);
}
::-webkit-scrollbar-thumb:hover { background: var(--color-text2); }
::-webkit-scrollbar-track { background: transparent; }

/* 尊重系统的「减弱动态效果」 */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

- [ ] **Step 4:挂到入口**

`web/src/main.ts` 顶部加两行(顺序:token 在前):

```ts
import './styles/tokens.css'
import './styles/base.css'
```

- [ ] **Step 5:验证并提交**

Run: `cd web && npm run type-check && npm run test:run`
Expected: 零错误;测试全绿

```bash
git add web/public/fonts web/src/styles/base.css web/src/main.ts web/tests/unit/fonts.spec.ts
git commit -m "feat(web): 全局样式与字体(含与 App 的字体同步测试)"
```

### Task 1.4:基础组件(一)AppButton / AppInput / AppCard

**Files:**
- Create: `web/src/components/AppButton.vue`、`AppInput.vue`、`AppCard.vue`
- Test: `web/tests/component/app-button.spec.ts`、`app-input.spec.ts`、`app-card.spec.ts`

**Interfaces:**
- Consumes: tokens.css 变量。
- Produces(后续所有页面都用这三个,签名固定):
  - `AppButton`:props `variant?: 'primary'|'ghost'|'danger'`(默认 primary)、`size?: 'md'|'lg'`(默认 md)、`disabled?`、`loading?`、`block?`;emits `click`;默认插槽为文字
  - `AppInput`:props `modelValue: string`、`type?`(默认 text)、`inputmode?`、`placeholder?`、`maxlength?`、`disabled?`、`error?: string`;emits `update:modelValue`、`enter`
  - `AppCard`:props `padding?: 'md'|'lg'`(默认 md)、`hoverable?`;默认插槽为内容

- [ ] **Step 1:写失败的组件测试**

`web/tests/component/app-button.spec.ts`:

```ts
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppButton from '@/components/AppButton.vue'

describe('AppButton', () => {
  it('渲染默认插槽文字并采用 primary 主按钮样式', () => {
    const w = mount(AppButton, { slots: { default: '开始' } })
    expect(w.text()).toBe('开始')
    expect(w.classes()).toContain('app-button--primary')
    expect(w.attributes('disabled')).toBeUndefined()
  })

  it('disabled 时不派发 click', async () => {
    const w = mount(AppButton, { props: { disabled: true }, slots: { default: '开始' } })
    await w.trigger('click')
    expect(w.emitted('click')).toBeUndefined()
  })

  it('loading 时阻止点击并展示加载态', async () => {
    const w = mount(AppButton, { props: { loading: true }, slots: { default: '登录' } })
    expect(w.find('.app-button__spinner').exists()).toBe(true)
    await w.trigger('click')
    expect(w.emitted('click')).toBeUndefined()
  })

  it('ghost 与 danger 走各自变体类', () => {
    expect(mount(AppButton, { props: { variant: 'ghost' } }).classes()).toContain('app-button--ghost')
    expect(mount(AppButton, { props: { variant: 'danger' } }).classes()).toContain('app-button--danger')
  })
})
```

`web/tests/component/app-input.spec.ts`:

```ts
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppInput from '@/components/AppInput.vue'

describe('AppInput', () => {
  it('输入时向父组件同步值', async () => {
    const w = mount(AppInput, { props: { modelValue: '' } })
    await w.find('input').setValue('13800000001')
    expect(w.emitted('update:modelValue')?.[0]).toEqual(['13800000001'])
  })

  it('回车时派发 enter 事件', async () => {
    const w = mount(AppInput, { props: { modelValue: 'x' } })
    await w.find('input').trigger('keyup.enter')
    expect(w.emitted('enter')).toHaveLength(1)
  })

  it('error 文案可见且带上错误态类', () => {
    const w = mount(AppInput, { props: { modelValue: '', error: '验证码错误' } })
    expect(w.text()).toContain('验证码错误')
    expect(w.classes()).toContain('app-input--error')
  })

  it('disabled 时输入框不可编辑', () => {
    const w = mount(AppInput, { props: { modelValue: '', disabled: true } })
    expect(w.find('input').attributes('disabled')).toBeDefined()
  })
})
```

`web/tests/component/app-card.spec.ts`:

```ts
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppCard from '@/components/AppCard.vue'

describe('AppCard', () => {
  it('渲染插入内容', () => {
    const w = mount(AppCard, { slots: { default: '<p>资料卡</p>' } })
    expect(w.find('p').text()).toBe('资料卡')
  })

  it('hoverable 时带悬停类(Web 新增维度)', () => {
    expect(mount(AppCard, { props: { hoverable: true } }).classes()).toContain('app-card--hoverable')
  })
})
```

- [ ] **Step 2:跑测试确认失败**

Run: `cd web && npm run test:run tests/component`
Expected: FAIL —— 组件文件不存在

- [ ] **Step 3:实现三个组件**

`web/src/components/AppButton.vue`:

```vue
<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    variant?: 'primary' | 'ghost' | 'danger'
    size?: 'md' | 'lg'
    disabled?: boolean
    loading?: boolean
    block?: boolean
  }>(),
  { variant: 'primary', size: 'md', disabled: false, loading: false, block: false },
)

const emit = defineEmits<{ click: [MouseEvent] }>()

function onClick(event: MouseEvent) {
  // 禁用/加载中一律不派发业务事件
  if (props.disabled || props.loading) return
  emit('click', event)
}
</script>

<template>
  <button
    type="button"
    class="app-button"
    :class="[`app-button--${variant}`, `app-button--${size}`, { 'app-button--block': block }]"
    :disabled="disabled || loading"
    @click="onClick"
  >
    <span v-if="loading" class="app-button__spinner" aria-hidden="true" />
    <slot />
  </button>
</template>

<style scoped>
.app-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-sm);
  border: 1px solid transparent;
  border-radius: var(--radius-input);
  font-family: var(--font-latin);
  font-weight: var(--weight-semibold);
  cursor: pointer;
  transition: background var(--motion-fast) var(--ease-out), opacity var(--motion-fast) var(--ease-out);
}
.app-button--md { height: 44px; padding: 0 var(--space-lg); font-size: var(--text-subtitle); }
.app-button--lg { height: 52px; padding: 0 var(--space-xl); font-size: var(--text-subtitle); }
.app-button--block { width: 100%; }
.app-button:disabled { opacity: 0.5; cursor: not-allowed; }

.app-button--primary {
  background: var(--gradient-heart);
  color: var(--color-bg-card);
  box-shadow: var(--shadow-primary-button);
}
.app-button--primary:not(:disabled):hover { filter: brightness(1.04); }

.app-button--ghost {
  background: var(--color-bg-card);
  border-color: var(--color-divider);
  color: var(--color-text1);
}
.app-button--ghost:not(:disabled):hover { background: var(--hover-overlay); }

.app-button--danger {
  background: var(--color-bg-card);
  border-color: var(--color-danger);
  color: var(--color-danger);
}
.app-button--danger:not(:disabled):hover { background: var(--hover-overlay); }

.app-button__spinner {
  width: 16px;
  height: 16px;
  border: 2px solid currentColor;
  border-top-color: transparent;
  border-radius: var(--radius-full);
  animation: app-button-spin var(--motion-loop) linear infinite;
}
@keyframes app-button-spin { to { transform: rotate(360deg); } }
</style>
```

> `onClick` 依赖 `props`,故 `props` 必须先声明;模板里 `variant`/`size`/`block`/`disabled`/`loading` 由 `<script setup>` 自动暴露,无需再包一层。

`web/src/components/AppInput.vue`:

```vue
<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    modelValue: string
    type?: string
    inputmode?: string
    placeholder?: string
    maxlength?: number
    disabled?: boolean
    error?: string
  }>(),
  { type: 'text', inputmode: undefined, placeholder: '', maxlength: undefined, disabled: false, error: '' },
)

const emit = defineEmits<{ 'update:modelValue': [string]; enter: [] }>()
</script>

<template>
  <div class="app-input" :class="{ 'app-input--error': !!props.error }">
    <input
      class="app-input__field"
      :type="props.type"
      :inputmode="props.inputmode"
      :value="props.modelValue"
      :placeholder="props.placeholder"
      :maxlength="props.maxlength"
      :disabled="props.disabled"
      @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
      @keyup.enter="emit('enter')"
    />
    <p v-if="props.error" class="app-input__error">{{ props.error }}</p>
  </div>
</template>

<style scoped>
.app-input { display: flex; flex-direction: column; gap: var(--space-xs); }
.app-input__field {
  height: 44px;
  padding: 0 var(--space-lg);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-input);
  background: var(--color-bg-card);
  color: var(--color-text1);
  font-size: var(--text-body);
  transition: border-color var(--motion-fast) var(--ease-out), box-shadow var(--motion-fast) var(--ease-out);
}
.app-input__field::placeholder { color: var(--color-text3); }
.app-input__field:focus {
  border-color: var(--color-brand);
  box-shadow: 0 0 0 3px rgb(255 44 85 / 12%);
}
.app-input--error .app-input__field { border-color: var(--color-danger); }
.app-input__error {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-danger);
}
</style>
```

`web/src/components/AppCard.vue`:

```vue
<script setup lang="ts">
const props = withDefaults(defineProps<{ padding?: 'md' | 'lg'; hoverable?: boolean }>(), {
  padding: 'md',
  hoverable: false,
})
</script>

<template>
  <section
    class="app-card"
    :class="[`app-card--${props.padding}`, { 'app-card--hoverable': props.hoverable }]"
  >
    <slot />
  </section>
</template>

<style scoped>
.app-card {
  background: var(--color-bg-card);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
  transition: box-shadow var(--motion-base) var(--ease-out), transform var(--motion-base) var(--ease-out);
}
.app-card--md { padding: var(--space-lg); }
.app-card--lg { padding: var(--space-xl); }
.app-card--hoverable:hover {
  box-shadow: var(--shadow-floating-bar);
  transform: translateY(-2px);
}
</style>
```

- [ ] **Step 4:跑测试确认通过**

Run: `cd web && npm run test:run tests/component && npm run type-check`
Expected: 10 passed;零类型错误

- [ ] **Step 5:提交**

```bash
git add web/src/components web/tests/component
git commit -m "feat(web): 基础组件 AppButton/AppInput/AppCard"
```

### Task 1.5:基础组件(二)AppAvatar / AppBadge / AppSkeleton

**Files:**
- Create: `web/src/components/AppAvatar.vue`、`AppBadge.vue`、`AppSkeleton.vue`
- Test: `web/tests/component/app-avatar.spec.ts`、`app-badge.spec.ts`、`app-skeleton.spec.ts`

**Interfaces:**
- Produces:
  - `AppAvatar`:props `src?: string | null`、`name?: string`、`size?: number`(默认 40);无 `src` 时用 `name` 首字 + 心跳渐变底
  - `AppBadge`:props `count: number`、`max?: number`(默认 99);`count <= 0` 时不渲染;`count > max` 显示 `${max}+`
  - `AppSkeleton`:props `width?: string`(默认 `100%`)、`height?: string`(默认 `16px`)、`radius?: string`(默认 `--radius-image`)

- [ ] **Step 1:写失败的测试**

`web/tests/component/app-avatar.spec.ts`:

```ts
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppAvatar from '@/components/AppAvatar.vue'

describe('AppAvatar', () => {
  it('有图时渲染 img,尺寸跟随 size', () => {
    const w = mount(AppAvatar, { props: { src: 'https://cdn/x.jpg', name: '小雨', size: 48 } })
    const img = w.find('img')
    expect(img.attributes('src')).toBe('https://cdn/x.jpg')
    expect(w.attributes('style')).toContain('48px')
  })

  it('无图时用昵称首字占位(心跳渐变底)', () => {
    const w = mount(AppAvatar, { props: { name: '小雨' } })
    expect(w.text()).toBe('小')
    expect(w.classes()).toContain('app-avatar--fallback')
  })

  it('昵称为空时占位为 ♥', () => {
    expect(mount(AppAvatar, { props: {} }).text()).toBe('♥')
  })
})
```

`web/tests/component/app-badge.spec.ts`:

```ts
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppBadge from '@/components/AppBadge.vue'

describe('AppBadge', () => {
  it('未读为 0 时不渲染', () => {
    expect(mount(AppBadge, { props: { count: 0 } }).find('.app-badge').exists()).toBe(false)
  })

  it('正常数字直接展示', () => {
    expect(mount(AppBadge, { props: { count: 3 } }).text()).toBe('3')
  })

  it('超过上限显示 99+', () => {
    expect(mount(AppBadge, { props: { count: 120 } }).text()).toBe('99+')
  })
})
```

`web/tests/component/app-skeleton.spec.ts`:

```ts
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppSkeleton from '@/components/AppSkeleton.vue'

describe('AppSkeleton', () => {
  it('应用传入的宽高', () => {
    const w = mount(AppSkeleton, { props: { width: '120px', height: '24px' } })
    expect(w.attributes('style')).toContain('120px')
    expect(w.attributes('style')).toContain('24px')
  })
})
```

- [ ] **Step 2:跑测试确认失败**

Run: `cd web && npm run test:run tests/component`
Expected: FAIL —— 组件不存在

- [ ] **Step 3:实现**

`web/src/components/AppAvatar.vue`:

```vue
<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{ src?: string | null; name?: string; size?: number }>(),
  { src: null, name: '', size: 40 },
)

const initial = computed(() => (props.name ? props.name.trim().charAt(0) : '♥'))
const style = computed(() => ({ width: `${props.size}px`, height: `${props.size}px` }))
</script>

<template>
  <span
    class="app-avatar"
    :class="{ 'app-avatar--fallback': !props.src }"
    :style="style"
  >
    <img v-if="props.src" :src="props.src" alt="" class="app-avatar__img" />
    <template v-else>{{ initial }}</template>
  </span>
</template>

<style scoped>
.app-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  overflow: hidden;
  border-radius: var(--radius-full);
  background: var(--color-bg-page);
  font-size: var(--text-caption);
  font-weight: var(--weight-bold);
}
.app-avatar--fallback {
  background: var(--gradient-heart);
  color: var(--color-bg-card);
  font-size: var(--text-body);
}
.app-avatar__img { width: 100%; height: 100%; object-fit: cover; }
</style>
```

`web/src/components/AppBadge.vue`:

```vue
<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{ count: number; max?: number }>(), { max: 99 })

const label = computed(() => (props.count > props.max ? `${props.max}+` : String(props.count)))
</script>

<template>
  <span v-if="props.count > 0" class="app-badge">{{ label }}</span>
</template>

<style scoped>
.app-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: var(--radius-full);
  background: var(--color-brand);
  color: var(--color-bg-card);
  font-size: var(--text-badge);
  font-weight: var(--weight-bold);
  line-height: 1;
}
</style>
```

`web/src/components/AppSkeleton.vue`:

```vue
<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{ width?: string; height?: string; radius?: string }>(),
  { width: '100%', height: '16px', radius: 'var(--radius-image)' },
)

const style = computed(() => ({
  width: props.width,
  height: props.height,
  borderRadius: props.radius,
}))
</script>

<template>
  <span class="app-skeleton" :style="style" aria-hidden="true" />
</template>

<style scoped>
.app-skeleton {
  display: block;
  background: var(--color-divider);
  animation: app-skeleton-breathe var(--motion-loop) var(--ease-out) infinite;
}
@keyframes app-skeleton-breathe {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.55; }
}
</style>
```

- [ ] **Step 4:跑测试确认通过**

Run: `cd web && npm run test:run tests/component && npm run type-check`
Expected: 17 passed

- [ ] **Step 5:提交**

```bash
git add web/src/components web/tests/component
git commit -m "feat(web): 基础组件 AppAvatar/AppBadge/AppSkeleton"
```

### Task 1.6:状态组件 AppEmpty / AppErrorView

**Files:**
- Create: `web/src/components/AppEmpty.vue`、`AppErrorView.vue`
- Test: `web/tests/component/app-empty.spec.ts`、`app-error-view.spec.ts`

**Interfaces:**
- Produces:
  - `AppEmpty`:props `emoji?: string`(默认 `'💫'`)、`title: string`、`description?: string`
  - `AppErrorView`:props `message?: string`(默认 `'出了点问题'`)、`retryLabel?: string`(默认 `'重试'`);emits `retry`

- [ ] **Step 1:写失败的测试**

`web/tests/component/app-empty.spec.ts`:

```ts
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppEmpty from '@/components/AppEmpty.vue'

describe('AppEmpty', () => {
  it('展示大号 emoji、标题与副文案', () => {
    const w = mount(AppEmpty, { props: { title: '附近还没有人', description: '换个筛选条件试试' } })
    expect(w.find('.app-empty__emoji').text()).toBe('💫')
    expect(w.text()).toContain('附近还没有人')
    expect(w.text()).toContain('换个筛选条件试试')
  })
})
```

`web/tests/component/app-error-view.spec.ts`:

```ts
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppErrorView from '@/components/AppErrorView.vue'

describe('AppErrorView', () => {
  it('展示文案并可重试', async () => {
    const w = mount(AppErrorView, { props: { message: '网络开小差了' } })
    expect(w.text()).toContain('网络开小差了')
    await w.find('button').trigger('click')
    expect(w.emitted('retry')).toHaveLength(1)
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/component`;Expected: FAIL

- [ ] **Step 3:实现**

`web/src/components/AppEmpty.vue`:

```vue
<script setup lang="ts">
withDefaults(defineProps<{ emoji?: string; title: string; description?: string }>(), {
  emoji: '💫',
  description: '',
})
</script>

<template>
  <div class="app-empty">
    <span class="app-empty__emoji">{{ emoji }}</span>
    <p class="app-empty__title">{{ title }}</p>
    <p v-if="description" class="app-empty__desc">{{ description }}</p>
  </div>
</template>

<style scoped>
.app-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-section-gap);
  text-align: center;
}
.app-empty__emoji { font-size: var(--text-emoji); line-height: 1; }
.app-empty__title {
  margin: 0;
  font-size: var(--text-subtitle);
  font-weight: var(--weight-semibold);
  color: var(--color-text1);
}
.app-empty__desc {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-text2);
}
</style>
```

`web/src/components/AppErrorView.vue`:

```vue
<script setup lang="ts">
import AppButton from './AppButton.vue'

const props = withDefaults(defineProps<{ message?: string; retryLabel?: string }>(), {
  message: '出了点问题',
  retryLabel: '重试',
})
const emit = defineEmits<{ retry: [] }>()
</script>

<template>
  <div class="app-error">
    <span class="app-error__emoji">🫧</span>
    <p class="app-error__message">{{ props.message }}</p>
    <AppButton variant="ghost" @click="emit('retry')">{{ props.retryLabel }}</AppButton>
  </div>
</template>

<style scoped>
.app-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-md);
  padding: var(--space-section-gap);
  text-align: center;
}
.app-error__emoji { font-size: var(--text-emoji); line-height: 1; }
.app-error__message {
  margin: 0;
  font-size: var(--text-body);
  color: var(--color-text2);
}
</style>
```

- [ ] **Step 4:跑测试确认通过** → Run: `cd web && npm run test:run tests/component && npm run type-check`;Expected: 19 passed

- [ ] **Step 5:提交**

```bash
git add web/src/components web/tests/component
git commit -m "feat(web): 状态组件 AppEmpty/AppErrorView"
```

### Task 1.7:开发期组件展示页(目检用)

**Files:**
- Create: `web/src/features/dev/ComponentsPage.vue`
- Modify: `web/src/router/index.ts`(加 `/dev/components` 路由,**仅 `import.meta.env.DEV` 时注册**)

**Interfaces:**
- Consumes: Task 1.4–1.6 的 8 个组件。
- Produces: 目检入口 `http://localhost:5173/dev/components`。

- [ ] **Step 1:写组件展示页**

`web/src/features/dev/ComponentsPage.vue`(把 8 个组件按变体铺开,便于肉眼比对「心跳」规则;纯展示,无测试):

```vue
<script setup lang="ts">
import { ref } from 'vue'
import AppAvatar from '@/components/AppAvatar.vue'
import AppBadge from '@/components/AppBadge.vue'
import AppButton from '@/components/AppButton.vue'
import AppCard from '@/components/AppCard.vue'
import AppEmpty from '@/components/AppEmpty.vue'
import AppErrorView from '@/components/AppErrorView.vue'
import AppInput from '@/components/AppInput.vue'
import AppSkeleton from '@/components/AppSkeleton.vue'

const text = ref('')
const phone = ref('13800000001')
</script>

<template>
  <main class="dev">
    <h1 class="dev__h1">心跳组件目检</h1>

    <AppCard padding="lg">
      <h2 class="dev__h2">按钮</h2>
      <div class="dev__row">
        <AppButton>主要</AppButton>
        <AppButton variant="ghost">次要</AppButton>
        <AppButton variant="danger">危险</AppButton>
        <AppButton loading>加载中</AppButton>
        <AppButton disabled>禁用</AppButton>
      </div>
      <AppButton block size="lg">通栏大按钮</AppButton>
    </AppCard>

    <AppCard padding="lg">
      <h2 class="dev__h2">输入</h2>
      <div class="dev__col">
        <AppInput v-model="text" placeholder="说点什么" />
        <AppInput v-model="phone" error="验证码错误,请重试" />
        <AppInput :model-value="''" disabled placeholder="禁用态" />
      </div>
    </AppCard>

    <AppCard padding="lg">
      <h2 class="dev__h2">头像 / 角标 / 骨架</h2>
      <div class="dev__row">
        <AppAvatar name="小雨" :size="48" />
        <AppAvatar name="A" :size="40" />
        <AppAvatar :size="40" />
        <AppBadge :count="3" />
        <AppBadge :count="120" />
      </div>
      <div class="dev__col">
        <AppSkeleton height="20px" />
        <AppSkeleton width="60%" height="14px" />
      </div>
    </AppCard>

    <AppCard padding="lg">
      <h2 class="dev__h2">空态 / 错误态</h2>
      <AppEmpty title="还没有人给你点赞" description="去广场发条动态吧" />
      <AppErrorView message="网络开小差了" @retry="() => {}" />
    </AppCard>
  </main>
</template>

<style scoped>
.dev {
  display: flex;
  flex-direction: column;
  gap: var(--space-card-gap);
  max-width: 900px;
  margin: 0 auto;
  padding: var(--space-section-gap) var(--space-page-h);
}
.dev__h1 { font-size: var(--text-display); font-weight: var(--weight-extrabold); margin: 0; }
.dev__h2 { font-size: var(--text-title); font-weight: var(--weight-bold); margin: 0 0 var(--space-md); }
.dev__row { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-md); }
.dev__col { display: flex; flex-direction: column; gap: var(--space-md); margin-top: var(--space-md); }
</style>
```

- [ ] **Step 2:加开发期路由**

`web/src/router/index.ts` 改为:

```ts
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const devRoutes: RouteRecordRaw[] = import.meta.env.DEV
  ? [
      {
        path: '/dev/components',
        component: () => import('@/features/dev/ComponentsPage.vue'),
      },
    ]
  : []

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: { template: '<div />' } },
    ...devRoutes,
  ],
})
```

- [ ] **Step 3:目检**

Run: `cd web && npm run dev`,浏览器打开 `http://localhost:5173/dev/components`
Expected: 8 个组件全部正常渲染;按钮有渐变与阴影;头像无图时显示首字/♥;骨架有呼吸动效
**用 DevTools 把 `prefers-reduced-motion` 打开复核:动效应当停止。**

- [ ] **Step 4:检查没有裸值**

用 grep 工具(ripgrep)在 `web/src/components` 与 `web/src/features` 下搜 `#[0-9A-Fa-f]{3,6}|font-size:\s*\d+px|padding:\s*\d+px`
Expected: 无命中(或仅命中注释)。**注意**:`AppInput.vue` 的聚焦光晕 `rgb(255 44 85 / 12%)` 是 brand 的透明度派生值;若被命中,把它提升为 tokens.css 的 `--focus-glow` 变量再引用。

- [ ] **Step 5:提交**

```bash
git add web/src/features/dev web/src/router
git commit -m "feat(web): 开发期组件目检页 /dev/components"
```

**▶ 组 T1 检查点**:`npm run type-check && npm run lint && npm run test:run` 全绿;`/dev/components` 目检通过。未过不进 T2。

## 组 T2:网络层与鉴权(6 个任务)

产出:一个能真登录的会话闭环 —— 错误契约解析、401 刷新通道(并发去重)、被顶号全屏提示、登录页、协议页。

### Task 2.1:错误契约解析与令牌存储

**Files:**
- Create: `web/src/api/error.ts`、`web/src/api/token-store.ts`
- Test: `web/tests/unit/api-error.spec.ts`、`web/tests/unit/token-store.spec.ts`

**Interfaces:**
- Produces:
  - `class ApiError extends Error { code: number; requestId?: string; status?: number; retryAfter?: number }`,带只读判定 `isUnauthorized`(401 且非 40101)、`isKickedOffline`(code === 40101)、`isBanned`(403)、`isThrottled`(429);`retryAfter` 取自响应头 `Retry-After`(限流时后端会给,登录页的倒计时要用它)
  - `parseApiError(error: unknown): ApiError` —— 把 axios 异常/原生 Error 统一成 ApiError
  - `tokenStore`:`access` / `refresh` / `userId` 的 getter+setter 与 `clear()`(localStorage 键 `hb.access` / `hb.refresh` / `hb.userId`)
- Consumes: 后端错误契约 `{"code", "message", "request_id"}`(Global Constraints)。

- [ ] **Step 1:写失败的测试**

`web/tests/unit/api-error.spec.ts`:

```ts
import { AxiosError, AxiosHeaders } from 'axios'
import { describe, expect, it } from 'vitest'
import { ApiError, parseApiError } from '@/api/error'

function axiosErrorWith(status: number, data: unknown): AxiosError {
  const config = { headers: new AxiosHeaders() }
  return new AxiosError('failed', 'ERR_BAD_REQUEST', config as never, null, {
    status,
    statusText: '',
    data,
    headers: {},
    config: config as never,
  })
}

describe('parseApiError', () => {
  it('解析后端的错误信封(含 request_id)', () => {
    const e = parseApiError(
      axiosErrorWith(400, { code: 40003, message: '验证码错误', request_id: 'req-1' }),
    )
    expect(e.code).toBe(40003)
    expect(e.message).toBe('验证码错误')
    expect(e.requestId).toBe('req-1')
    expect(e.status).toBe(400)
  })

  it('不是信封形状时降级为服务器异常文案', () => {
    const e = parseApiError(axiosErrorWith(502, '<html>Bad Gateway</html>'))
    expect(e.code).toBe(502)
    expect(e.message).toBe('服务器开小差了,请稍后再试')
  })

  it('无响应(网络/超时)视为网络异常,code 为 0', () => {
    const e = parseApiError(new AxiosError('timeout', 'ECONNABORTED'))
    expect(e.code).toBe(0)
    expect(e.message).toBe('网络连接失败,请检查网络后重试')
  })

  it('401 与 40101 语义区分开', () => {
    const normal = parseApiError(axiosErrorWith(401, { code: 40100, message: '未认证' }))
    const kicked = parseApiError(axiosErrorWith(401, { code: 40101, message: '已在其他设备登录' }))
    expect(normal.isUnauthorized).toBe(true)
    expect(normal.isKickedOffline).toBe(false)
    expect(kicked.isKickedOffline).toBe(true)
    expect(kicked.isUnauthorized).toBe(false)
  })

  it('403 与 429 判定', () => {
    expect(parseApiError(axiosErrorWith(403, { code: 40302, message: '账号已被封禁' })).isBanned).toBe(true)
    expect(parseApiError(axiosErrorWith(429, { code: 42901, message: '发送过于频繁' })).isThrottled).toBe(true)
  })

  it('限流时解析 Retry-After 供倒计时使用', () => {
    const withHeader = axiosErrorWith(429, { code: 42901, message: '发送过于频繁' })
    withHeader.response!.headers['retry-after'] = '45'
    expect(parseApiError(withHeader).retryAfter).toBe(45)
    expect(parseApiError(axiosErrorWith(429, { code: 42901, message: 'x' })).retryAfter).toBeUndefined()
  })
})
```

`web/tests/unit/token-store.spec.ts`:

```ts
import { beforeEach, describe, expect, it } from 'vitest'
import { tokenStore } from '@/api/token-store'

describe('tokenStore', () => {
  beforeEach(() => localStorage.clear())

  it('读写三件套', () => {
    tokenStore.access = 'a'
    tokenStore.refresh = 'r'
    tokenStore.userId = 42
    expect(tokenStore.access).toBe('a')
    expect(tokenStore.refresh).toBe('r')
    expect(tokenStore.userId).toBe(42)
  })

  it('清空后全部为 null', () => {
    tokenStore.access = 'a'
    tokenStore.refresh = 'r'
    tokenStore.userId = 42
    tokenStore.clear()
    expect(tokenStore.access).toBeNull()
    expect(tokenStore.refresh).toBeNull()
    expect(tokenStore.userId).toBeNull()
  })

  it('userId 存的是数字,读回来仍是数字', () => {
    tokenStore.userId = 7
    expect(localStorage.getItem('hb.userId')).toBe('7')
    expect(typeof tokenStore.userId).toBe('number')
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/unit`;Expected: FAIL,找不到 `@/api/error`

- [ ] **Step 3:实现**

`web/src/api/error.ts`:

```ts
import axios from 'axios'

/** 后端统一错误信封解析结果(形状见 CLAUDE.md「错误契约」)。 */
export class ApiError extends Error {
  constructor(
    readonly code: number,
    message: string,
    readonly requestId?: string,
    readonly status?: number,
    /** 限流时后端给的 Retry-After(秒);登录页倒计时用它,不硬编码 60 */
    readonly retryAfter?: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }

  /** 普通未认证:走刷新通道 */
  get isUnauthorized(): boolean {
    return this.status === 401 && this.code !== 40101
  }

  /** 被顶号(单设备登录):清凭证 + 全屏提示,不刷新 */
  get isKickedOffline(): boolean {
    return this.code === 40101
  }

  /** 封禁(banned_light / banned_heavy 均由后端 403 表达) */
  get isBanned(): boolean {
    return this.status === 403
  }

  get isThrottled(): boolean {
    return this.status === 429
  }
}

type Envelope = { code?: unknown; message?: unknown; request_id?: unknown }

function asEnvelope(data: unknown): Envelope | null {
  return data && typeof data === 'object' ? (data as Envelope) : null
}

export function parseApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error

  if (axios.isAxiosError(error)) {
    const response = error.response
    if (!response) return new ApiError(0, '网络连接失败,请检查网络后重试')

    const envelope = asEnvelope(response.data)
    const code = typeof envelope?.code === 'number' ? envelope.code : response.status
    const message =
      typeof envelope?.message === 'string' && envelope.message
        ? envelope.message
        : '服务器开小差了,请稍后再试'
    const requestId = typeof envelope?.request_id === 'string' ? envelope.request_id : undefined
    const retryAfterRaw = response.headers?.['retry-after']
    const retryAfter = Number(retryAfterRaw)
    return new ApiError(
      code,
      message,
      requestId,
      response.status,
      Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : undefined,
    )
  }

  if (error instanceof Error) return new ApiError(0, error.message)
  return new ApiError(0, '未知错误')
}
```

`web/src/api/token-store.ts`:

```ts
/** 令牌与账号 id 的本地存储(与 App 的 SharedPreferences 语义一致,Web 落在 localStorage)。 */
const ACCESS_KEY = 'hb.access'
const REFRESH_KEY = 'hb.refresh'
const USER_ID_KEY = 'hb.userId'

export const tokenStore = {
  get access(): string | null {
    return localStorage.getItem(ACCESS_KEY)
  },
  set access(value: string | null) {
    if (value === null) localStorage.removeItem(ACCESS_KEY)
    else localStorage.setItem(ACCESS_KEY, value)
  },

  get refresh(): string | null {
    return localStorage.getItem(REFRESH_KEY)
  },
  set refresh(value: string | null) {
    if (value === null) localStorage.removeItem(REFRESH_KEY)
    else localStorage.setItem(REFRESH_KEY, value)
  },

  get userId(): number | null {
    const raw = localStorage.getItem(USER_ID_KEY)
    if (raw === null) return null
    const parsed = Number(raw)
    return Number.isNaN(parsed) ? null : parsed
  },
  set userId(value: number | null) {
    if (value === null) localStorage.removeItem(USER_ID_KEY)
    else localStorage.setItem(USER_ID_KEY, String(value))
  },

  clear(): void {
    localStorage.removeItem(ACCESS_KEY)
    localStorage.removeItem(REFRESH_KEY)
    localStorage.removeItem(USER_ID_KEY)
  },
}
```

- [ ] **Step 4:跑测试确认通过** → Run: `cd web && npm run test:run tests/unit && npm run type-check`;Expected: 全绿

- [ ] **Step 5:提交**

```bash
git add web/src/api web/tests/unit
git commit -m "feat(web): 错误契约解析与令牌存储"
```

### Task 2.2:axios 实例与 401 刷新通道

**Files:**
- Create: `web/src/api/http.ts`、`web/src/api/session-events.ts`、`web/.env.test`、`web/tests/support/server.ts`
- Test: `web/tests/unit/http-refresh.spec.ts`

**Interfaces:**
- Consumes: `ApiError` / `parseApiError` / `tokenStore`(Task 2.1)。
- Produces:
  - `http`(axios 实例,`baseURL = import.meta.env.VITE_API_BASE`,超时 15s)
  - `sessionEvents`:`onKickedOffline(cb)`、`onSessionExpired(cb)`、`emitKickedOffline()`、`emitSessionExpired()`(回调注册用,避免 `http` 反向依赖 Pinia)
  - 刷新语义:同一时刻**只刷一次**;刷新成功重放原请求;刷新失败清空 `tokenStore` 并 `emitSessionExpired`

- [ ] **Step 1:补 `.env.test`(vitest 的 mode 是 `test`,不读 `.env.development`)**

`web/.env.test`:

```
VITE_API_BASE=/api/v1
```

`web/tests/support/server.ts`(MSW 测试服务器,后面所有组件测试复用):

```ts
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll } from 'vitest'

export const server = setupServer()

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  server.resetHandlers()
  localStorage.clear()
})
afterAll(() => server.close())
```

- [ ] **Step 2:写失败的测试**

`web/tests/unit/http-refresh.spec.ts`:

```ts
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { http } from '@/api/http'
import { sessionEvents } from '@/api/session-events'
import { tokenStore } from '@/api/token-store'
import { server } from '../support/server'

const unauthorized = () =>
  HttpResponse.json({ code: 40100, message: '未认证', request_id: 'r' }, { status: 401 })

/** 只在带新令牌时才放行的受保护接口 */
function guardedMe() {
  return mswHttp.get('/api/v1/users/me', ({ request }) =>
    request.headers.get('Authorization') === 'Bearer new-access'
      ? HttpResponse.json({ id: 1, nickname: '小雨' })
      : unauthorized(),
  )
}

describe('401 刷新通道', () => {
  beforeEach(() => {
    // 每个用例的监听器互相隔离(store 也会注册,但此文件不创建 store)
    sessionEvents._reset()
    tokenStore.access = 'expired'
    tokenStore.refresh = 'refresh-1'
  })

  it('刷新成功后重放原请求,并轮换两个令牌', async () => {
    let refreshCalls = 0
    server.use(
      guardedMe(),
      mswHttp.post('/api/v1/auth/token/refresh', () => {
        refreshCalls += 1
        return HttpResponse.json({ access: 'new-access', refresh: 'refresh-2' })
      }),
    )

    const res = await http.get('/users/me')

    expect(res.data).toEqual({ id: 1, nickname: '小雨' })
    expect(refreshCalls).toBe(1)
    expect(tokenStore.access).toBe('new-access')
    expect(tokenStore.refresh).toBe('refresh-2')
  })

  it('并发两个 401 只刷新一次', async () => {
    let refreshCalls = 0
    server.use(
      guardedMe(),
      mswHttp.post('/api/v1/auth/token/refresh', async () => {
        refreshCalls += 1
        await new Promise((r) => setTimeout(r, 20)) // 制造并发窗口
        return HttpResponse.json({ access: 'new-access', refresh: 'refresh-2' })
      }),
    )

    const [a, b] = await Promise.all([http.get('/users/me'), http.get('/users/me')])

    expect(a.status).toBe(200)
    expect(b.status).toBe(200)
    expect(refreshCalls).toBe(1)
  })

  it('刷新失败时清空凭证并通知会话过期', async () => {
    const expired = vi.fn()
    sessionEvents.onSessionExpired(expired)
    server.use(
      mswHttp.get('/api/v1/users/me', unauthorized),
      mswHttp.post('/api/v1/auth/token/refresh', unauthorized),
    )

    await expect(http.get('/users/me')).rejects.toMatchObject({ code: 40100 })

    expect(expired).toHaveBeenCalledTimes(1)
    expect(tokenStore.access).toBeNull()
    expect(tokenStore.refresh).toBeNull()
  })

  it('40101 被顶号:不刷新,直接通知被顶下线', async () => {
    const kicked = vi.fn()
    sessionEvents.onKickedOffline(kicked)
    let refreshCalls = 0
    server.use(
      mswHttp.get('/api/v1/users/me', () =>
        HttpResponse.json({ code: 40101, message: '账号已在其他设备登录', request_id: 'r' }, { status: 401 }),
      ),
      mswHttp.post('/api/v1/auth/token/refresh', () => {
        refreshCalls += 1
        return HttpResponse.json({ access: 'x', refresh: 'y' })
      }),
    )

    await expect(http.get('/users/me')).rejects.toMatchObject({ code: 40101 })

    expect(refreshCalls).toBe(0)
    expect(kicked).toHaveBeenCalledTimes(1)
    expect(tokenStore.access).toBeNull()
  })
})
```

- [ ] **Step 3:跑测试确认失败** → Run: `cd web && npm run test:run tests/unit/http-refresh.spec.ts`;Expected: FAIL,找不到 `@/api/http`

- [ ] **Step 4:实现**

`web/src/api/session-events.ts`:

```ts
/** 会话级事件:由 http 层触发,由 UI 层监听(避免 http 反向依赖 Pinia / 路由)。 */
type Handler = () => void

const kickedOfflineHandlers = new Set<Handler>()
const sessionExpiredHandlers = new Set<Handler>()

export const sessionEvents = {
  onKickedOffline(handler: Handler): void {
    kickedOfflineHandlers.add(handler)
  },
  onSessionExpired(handler: Handler): void {
    sessionExpiredHandlers.add(handler)
  },
  emitKickedOffline(): void {
    kickedOfflineHandlers.forEach((h) => h())
  },
  emitSessionExpired(): void {
    sessionExpiredHandlers.forEach((h) => h())
  },
  /** 仅供测试重置 */
  _reset(): void {
    kickedOfflineHandlers.clear()
    sessionExpiredHandlers.clear()
  },
}
```

`web/src/api/http.ts`:

```ts
import axios, { type AxiosError, type AxiosRequestConfig, type InternalAxiosRequestConfig } from 'axios'
import { ApiError, parseApiError } from './error'
import { sessionEvents } from './session-events'
import { tokenStore } from './token-store'

const baseURL = import.meta.env.VITE_API_BASE ?? '/api/v1'

export const http = axios.create({ baseURL, timeout: 15_000 })

/** 裸实例:刷新令牌本身不能走拦截器,否则 401 会递归 */
const bare = axios.create({ baseURL, timeout: 15_000 })

http.interceptors.request.use((config) => {
  const access = tokenStore.access
  if (access) config.headers.Authorization = `Bearer ${access}`
  return config
})

type RetriableConfig = InternalAxiosRequestConfig & { _retried?: boolean }

let refreshing: Promise<string> | null = null

async function refreshAccessToken(): Promise<string> {
  const refresh = tokenStore.refresh
  if (!refresh) throw new ApiError(401, '登录状态已失效,请重新登录')
  const { data } = await bare.post('/auth/token/refresh', { refresh })
  tokenStore.access = data.access
  tokenStore.refresh = data.refresh
  return data.access as string
}

http.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const apiError = parseApiError(error)

    if (apiError.isKickedOffline) {
      tokenStore.clear()
      sessionEvents.emitKickedOffline()
      return Promise.reject(apiError)
    }

    const config = error.config as RetriableConfig | undefined
    if (apiError.isUnauthorized && config && !config._retried) {
      config._retried = true
      // 并发去重:同一时刻只发一次刷新请求
      refreshing ??= refreshAccessToken().finally(() => {
        refreshing = null
      })
      try {
        const access = await refreshing
        config.headers.Authorization = `Bearer ${access}`
        return await http.request(config)
      } catch (refreshError) {
        tokenStore.clear()
        sessionEvents.emitSessionExpired()
        return Promise.reject(parseApiError(refreshError))
      }
    }

    return Promise.reject(apiError)
  },
)

export type { AxiosRequestConfig }
```

- [ ] **Step 5:跑测试确认通过** → Run: `cd web && npm run test:run tests/unit && npm run type-check`;Expected: 全绿(含 Task 2.1 的用例)

- [ ] **Step 6:提交**

```bash
git add web/src/api web/tests/support web/tests/unit web/.env.test
git commit -m "feat(web): axios 实例与 401 刷新通道(并发去重)"
```

### Task 2.3:会话 store(登录 / 登出 / 启动恢复)

**Files:**
- Create: `web/src/stores/session.ts`、`web/src/api/auth.ts`、`web/src/api/types.ts`
- Test: `web/tests/unit/session-store.spec.ts`

**Interfaces:**
- Consumes: `http`、`tokenStore`、`sessionEvents`。
- Produces:
  - `useSessionStore()`:`state` = `{ status: 'loading'|'loggedOut'|'loggedIn', userId: number | null, kicked: boolean }`;`actions` = `sendCode(phone)`、`verify(phone, code)`、`logout()`、`restore()`、`acknowledgeKicked()`
  - `api/auth.ts`:`sendCode(phone): Promise<void>`、`verify(phone, code): Promise<{ access, refresh, isNewUser, userId }>`
- 说明:`status` 三态对应 App 的 `SessionLoading / SessionLoggedOut / SessionLoggedIn`;`kicked` 驱动全屏提示(Task 2.4)。

- [ ] **Step 1:写失败的测试**

`web/tests/unit/session-store.spec.ts`:

```ts
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { useSessionStore } from '@/stores/session'
import { sessionEvents } from '@/api/session-events'
import { tokenStore } from '@/api/token-store'
import { server } from '../support/server'

describe('session store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sessionEvents._reset()
  })

  it('verify 成功后写入令牌与账号 id', async () => {
    server.use(
      mswHttp.post('/api/v1/auth/sms/verify', () =>
        HttpResponse.json({ access: 'a1', refresh: 'r1', is_new_user: true, user_id: 9 }),
      ),
    )
    const store = useSessionStore()

    await store.verify('13800000001', '123456')

    expect(store.status).toBe('loggedIn')
    expect(store.userId).toBe(9)
    expect(tokenStore.access).toBe('a1')
    expect(tokenStore.refresh).toBe('r1')
  })

  it('restore:本地无令牌 → loggedOut', async () => {
    const store = useSessionStore()
    await store.restore()
    expect(store.status).toBe('loggedOut')
  })

  it('restore:有令牌且 /users/me 通 → loggedIn', async () => {
    tokenStore.access = 'a'
    tokenStore.refresh = 'r'
    tokenStore.userId = 5
    server.use(mswHttp.get('/api/v1/users/me', () => HttpResponse.json({ id: 1, nickname: '小雨' })))
    const store = useSessionStore()

    await store.restore()

    expect(store.status).toBe('loggedIn')
    expect(store.userId).toBe(5)
  })

  it('logout 清凭证并回到 loggedOut', async () => {
    tokenStore.access = 'a'
    tokenStore.refresh = 'r'
    tokenStore.userId = 5
    const store = useSessionStore()
    await store.restore()

    store.logout()

    expect(store.status).toBe('loggedOut')
    expect(store.userId).toBeNull()
    expect(tokenStore.access).toBeNull()
  })

  it('被顶号事件把 kicked 置为 true 并清凭证', async () => {
    tokenStore.access = 'a'
    tokenStore.refresh = 'r'
    const store = useSessionStore()
    await store.restore()

    sessionEvents.emitKickedOffline()

    expect(store.kicked).toBe(true)
    expect(store.status).toBe('loggedOut')
    expect(tokenStore.access).toBeNull()
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/unit/session-store.spec.ts`;Expected: FAIL

- [ ] **Step 3:实现**

`web/src/api/types.ts`(本任务只放会话相关,后续任务逐组追加):

```ts
export interface LoginResult {
  access: string
  refresh: string
  isNewUser: boolean
  userId: number
}
```

`web/src/api/auth.ts`:

```ts
import { http } from './http'
import type { LoginResult } from './types'

/** 发送短信验证码;同号 60 秒内重发会被后端拒绝(42901,响应带 Retry-After)。 */
export async function sendCode(phone: string): Promise<void> {
  await http.post('/auth/sms/send', { phone })
}

/** 校验验证码并登录(未注册自动建号)。 */
export async function verify(phone: string, code: string): Promise<LoginResult> {
  const { data } = await http.post('/auth/sms/verify', { phone, code })
  return {
    access: data.access,
    refresh: data.refresh,
    isNewUser: Boolean(data.is_new_user),
    userId: Number(data.user_id),
  }
}
```

`web/src/stores/session.ts`:

```ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as authApi from '@/api/auth'
import { http } from '@/api/http'
import { sessionEvents } from '@/api/session-events'
import { tokenStore } from '@/api/token-store'

export type SessionStatus = 'loading' | 'loggedOut' | 'loggedIn'

export const useSessionStore = defineStore('session', () => {
  const status = ref<SessionStatus>('loading')
  const userId = ref<number | null>(tokenStore.userId)
  const kicked = ref(false)

  /** 被顶号 / 刷新失败:清凭证回登录态。kicked 只在被顶号时为 true。 */
  function resetSession(isKicked: boolean): void {
    tokenStore.clear()
    userId.value = null
    status.value = 'loggedOut'
    if (isKicked) kicked.value = true
  }

  sessionEvents.onKickedOffline(() => resetSession(true))
  sessionEvents.onSessionExpired(() => resetSession(false))

  async function sendCode(phone: string): Promise<void> {
    await authApi.sendCode(phone)
  }

  async function verify(phone: string, code: string): Promise<void> {
    const result = await authApi.verify(phone, code)
    tokenStore.access = result.access
    tokenStore.refresh = result.refresh
    tokenStore.userId = result.userId
    userId.value = result.userId
    status.value = 'loggedIn'
  }

  function logout(): void {
    resetSession(false)
  }

  async function restore(): Promise<void> {
    if (!tokenStore.access || !tokenStore.refresh) {
      status.value = 'loggedOut'
      return
    }
    try {
      await http.get('/users/me')
      userId.value = tokenStore.userId
      status.value = 'loggedIn'
    } catch {
      // 拦截器已按 401/40101 分支清理过凭证;这里兜底成未登录态
      status.value = tokenStore.access ? 'loggedIn' : 'loggedOut'
    }
  }

  function acknowledgeKicked(): void {
    kicked.value = false
  }

  return { status, userId, kicked, sendCode, verify, logout, restore, acknowledgeKicked }
})
```

- [ ] **Step 4:跑测试确认通过** → Run: `cd web && npm run test:run tests/unit && npm run type-check`;Expected: 全绿

- [ ] **Step 5:提交**

```bash
git add web/src/stores web/src/api web/tests/unit
git commit -m "feat(web): 会话 store 与登录/登出/启动恢复"
```

### Task 2.4:被顶号全屏提示

**Files:**
- Create: `web/src/components/AppKickedOverlay.vue`
- Modify: `web/src/App.vue`(挂全局浮层)
- Test: `web/tests/component/app-kicked-overlay.spec.ts`

**Interfaces:**
- Consumes: `useSessionStore().kicked` / `acknowledgeKicked()`。
- Produces:`AppKickedOverlay`(无 props;由 store 驱动显隐) —— **浏览器没有推送渠道,被顶必须全屏可见,不能只闪一个 toast**(spec §9.1)。

- [ ] **Step 1:写失败的测试**

`web/tests/component/app-kicked-overlay.spec.ts`:

```ts
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import AppKickedOverlay from '@/components/AppKickedOverlay.vue'
import { useSessionStore } from '@/stores/session'

describe('AppKickedOverlay', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('未被顶号时不渲染', () => {
    expect(mount(AppKickedOverlay).find('.kicked-overlay').exists()).toBe(false)
  })

  it('被顶号时展示全屏提示与重新登录按钮', async () => {
    const store = useSessionStore()
    store.kicked = true
    const w = mount(AppKickedOverlay)

    expect(w.find('.kicked-overlay').exists()).toBe(true)
    expect(w.text()).toContain('账号已在其他设备登录')

    await w.find('button').trigger('click')
    expect(store.kicked).toBe(false)
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/component/app-kicked-overlay.spec.ts`;Expected: FAIL

- [ ] **Step 3:实现**

`web/src/components/AppKickedOverlay.vue`:

```vue
<script setup lang="ts">
import { useSessionStore } from '@/stores/session'
import AppButton from './AppButton.vue'

const session = useSessionStore()
</script>

<template>
  <div v-if="session.kicked" class="kicked-overlay" role="alertdialog" aria-modal="true">
    <div class="kicked-overlay__panel">
      <span class="kicked-overlay__emoji">📵</span>
      <h2 class="kicked-overlay__title">账号已在其他设备登录</h2>
      <p class="kicked-overlay__desc">
        为保障账号安全,同一账号只能在一台设备上使用。当前设备已退出,请重新登录。
      </p>
      <AppButton block size="lg" @click="session.acknowledgeKicked()">重新登录</AppButton>
    </div>
  </div>
</template>

<style scoped>
.kicked-overlay {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgb(22 24 29 / 55%);
}
.kicked-overlay__panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
  width: calc(var(--form-card-max) * 0.8);
  padding: var(--space-xxl);
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-floating-bar);
  text-align: center;
}
.kicked-overlay__emoji { font-size: var(--text-emoji); line-height: 1; }
.kicked-overlay__title {
  margin: 0;
  font-size: var(--text-title);
  font-weight: var(--weight-bold);
}
.kicked-overlay__desc {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-text2);
}
</style>
```

`web/src/App.vue` 改为:

```vue
<script setup lang="ts">
import AppKickedOverlay from '@/components/AppKickedOverlay.vue'
</script>

<template>
  <RouterView />
  <AppKickedOverlay />
</template>
```

- [ ] **Step 4:跑测试确认通过** → Run: `cd web && npm run test:run tests/component && npm run type-check`;Expected: 全绿

- [ ] **Step 5:提交**

```bash
git add web/src/components/AppKickedOverlay.vue web/src/App.vue web/tests/component
git commit -m "feat(web): 被顶号全屏提示"
```

### Task 2.5:登录页(验证码倒计时与锁定)

**Files:**
- Create: `web/src/features/auth/LoginPage.vue`、`web/src/features/auth/FormCard.vue`
- Modify: `web/src/router/index.ts`(加 `/login`)
- Test: `web/tests/component/login-page.spec.ts`

**Interfaces:**
- Consumes: `useSessionStore()`、`AppButton` / `AppInput` / `AppCard`、`ApiError`。
- Produces:
  - `FormCard.vue`:props `title: string`、`description?: string`;默认插槽为表单 —— **PC 上所有「一次填完就走」的页面共用这个居中卡片**(宽度 = 窗口宽 × 32%,夹 420–520px)
  - `LoginPage.vue`:路由 `/login`;手机号 11 位校验、发码后 60 秒倒计时、42902 锁定提示、登录成功跳 `/onboarding`(新用户)或 `/home`

- [ ] **Step 1:写失败的测试**

`web/tests/component/login-page.spec.ts`:

```ts
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it } from 'vitest'
import LoginPage from '@/features/auth/LoginPage.vue'
import { tokenStore } from '@/api/token-store'
import { server } from '../support/server'

async function mountLogin() {
  const w = mount(LoginPage, {
    global: { stubs: { RouterLink: true }, plugins: [createPinia()] },
  })
  await flushPromises()
  return w
}

describe('LoginPage', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('手机号格式不合法时不发码并给出提示', async () => {
    const w = await mountLogin()
    await w.find('input[type="tel"]').setValue('138')
    await w.find('.login__send').trigger('click')
    expect(w.text()).toContain('请输入 11 位手机号')
  })

  it('发码成功后进入 60 秒倒计时且按钮禁用', async () => {
    server.use(mswHttp.post('/api/v1/auth/sms/send', () => HttpResponse.json({ status: 'ok' })))
    const w = await mountLogin()
    await w.find('input[type="tel"]').setValue('13800000001')
    await w.find('.login__send').trigger('click')
    await flushPromises()

    expect(w.find('.login__send').text()).toContain('秒后重发')
    expect(w.find('.login__send').attributes('disabled')).toBeDefined()
  })

  it('42901 时按 Retry-After 提示等待', async () => {
    server.use(
      mswHttp.post('/api/v1/auth/sms/send', () =>
        HttpResponse.json(
          { code: 42901, message: '发送过于频繁,请稍后再试', request_id: 'r' },
          { status: 429, headers: { 'Retry-After': '45' } },
        ),
      ),
    )
    const w = await mountLogin()
    await w.find('input[type="tel"]').setValue('13800000001')
    await w.find('.login__send').trigger('click')
    await flushPromises()

    expect(w.text()).toContain('发送过于频繁')
    expect(w.find('.login__send').text()).toContain('45')
  })

  it('验证码错误时展示后端文案', async () => {
    server.use(
      mswHttp.post('/api/v1/auth/sms/verify', () =>
        HttpResponse.json(
          { code: 40003, message: '验证码错误', request_id: 'r' },
          { status: 400 },
        ),
      ),
    )
    const w = await mountLogin()
    await w.find('input[type="tel"]').setValue('13800000001')
    await w.find('input[inputmode="numeric"]').setValue('000000')
    await w.find('.login__submit').trigger('click')
    await flushPromises()

    expect(w.text()).toContain('验证码错误')
  })

  it('登录成功写入令牌并跳转 /home', async () => {
    server.use(
      mswHttp.post('/api/v1/auth/sms/verify', () =>
        HttpResponse.json({ access: 'a1', refresh: 'r1', is_new_user: false, user_id: 9 }),
      ),
    )
    // 用真实路由(memory history),断言真的发生了跳转 —— 不用 mock 的 $router
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: { template: '<div/>' } },
        { path: '/home', name: 'home', component: { template: '<div/>' } },
      ],
    })
    await router.push('/')
    await router.isReady()

    const w = mount(LoginPage, {
      global: { stubs: { RouterLink: true }, plugins: [createPinia(), router] },
    })
    await w.find('input[type="tel"]').setValue('13800000001')
    await w.find('input[inputmode="numeric"]').setValue('123456')
    await w.find('.login__submit').trigger('click')
    await flushPromises()

    expect(tokenStore.access).toBe('a1')
    expect(router.currentRoute.value.path).toBe('/home')
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/component/login-page.spec.ts`;Expected: FAIL

- [ ] **Step 3:实现 `FormCard.vue`**

```vue
<script setup lang="ts">
defineProps<{ title: string; description?: string }>()
</script>

<template>
  <div class="form-card-wrap">
    <section class="form-card">
      <header class="form-card__head">
        <h1 class="form-card__title">{{ title }}</h1>
        <p v-if="description" class="form-card__desc">{{ description }}</p>
      </header>
      <slot />
    </section>
  </div>
</template>

<style scoped>
.form-card-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: var(--space-section-gap);
  background: var(--color-bg-page);
}
.form-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-xl);
  width: clamp(var(--form-card-min), var(--form-card-ratio), var(--form-card-max));
  padding: var(--space-xxl);
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-card);
}
.form-card__head { display: flex; flex-direction: column; gap: var(--space-xs); }
.form-card__title {
  margin: 0;
  font-size: var(--text-display);
  font-weight: var(--weight-extrabold);
  letter-spacing: -0.02em;
}
.form-card__desc {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-text2);
}
</style>
```

- [ ] **Step 4:实现 `LoginPage.vue`**

```vue
<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { parseApiError } from '@/api/error'
import AppButton from '@/components/AppButton.vue'
import AppInput from '@/components/AppInput.vue'
import { useSessionStore } from '@/stores/session'
import FormCard from './FormCard.vue'

const PHONE_RE = /^\d{11}$/

const router = useRouter()
const session = useSessionStore()

const phone = ref('')
const code = ref('')
const error = ref('')
const sending = ref(false)
const submitting = ref(false)
const countdown = ref(0)
let timer: number | undefined

const canSend = computed(() => countdown.value === 0 && !sending.value)

function startCountdown(seconds: number) {
  countdown.value = seconds
  window.clearInterval(timer)
  timer = window.setInterval(() => {
    countdown.value -= 1
    if (countdown.value <= 0) window.clearInterval(timer)
  }, 1000)
}

onUnmounted(() => window.clearInterval(timer))

async function onSend() {
  error.value = ''
  if (!PHONE_RE.test(phone.value)) {
    error.value = '请输入 11 位手机号'
    return
  }
  sending.value = true
  try {
    await session.sendCode(phone.value)
    startCountdown(60)
  } catch (e) {
    const apiError = parseApiError(e)
    error.value = apiError.message
    // 42901:后端带 Retry-After,按它倒计时,而不是硬编码 60 秒
    if (apiError.isThrottled && apiError.retryAfter) startCountdown(apiError.retryAfter)
  } finally {
    sending.value = false
  }
}

async function onSubmit() {
  error.value = ''
  if (!PHONE_RE.test(phone.value)) {
    error.value = '请输入 11 位手机号'
    return
  }
  if (code.value.length !== 6) {
    error.value = '请输入 6 位验证码'
    return
  }
  submitting.value = true
  try {
    await session.verify(phone.value, code.value)
    await router.push('/home')
  } catch (e) {
    error.value = parseApiError(e).message
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <FormCard title="心跳" description="手机号登录,未注册将自动创建账号">
    <div class="login__field">
      <AppInput
        v-model="phone"
        type="tel"
        placeholder="手机号"
        :maxlength="11"
        :error="error"
        @enter="onSubmit"
      />
      <div class="login__code-row">
        <AppInput v-model="code" inputmode="numeric" placeholder="6 位验证码" :maxlength="6" />
        <AppButton
          class="login__send"
          variant="ghost"
          :disabled="!canSend"
          :loading="sending"
          @click="onSend"
        >
          {{ countdown > 0 ? `${countdown} 秒后重发` : '获取验证码' }}
        </AppButton>
      </div>
    </div>
    <AppButton class="login__submit" block size="lg" :loading="submitting" @click="onSubmit">
      登录
    </AppButton>
  </FormCard>
</template>

<style scoped>
.login__field { display: flex; flex-direction: column; gap: var(--space-md); }
.login__code-row { display: flex; align-items: flex-start; gap: var(--space-sm); }
.login__send { flex: none; white-space: nowrap; }
</style>
```

- [ ] **Step 5:补路由**

`web/src/router/index.ts` 的 `routes` 数组加:

```ts
{ path: '/login', component: () => import('@/features/auth/LoginPage.vue') },
```

- [ ] **Step 6:跑测试确认通过** → Run: `cd web && npm run test:run && npm run type-check`;Expected: 全绿

- [ ] **Step 7:提交**

```bash
git add web/src/features/auth web/src/router web/src/api/error.ts web/tests/component
git commit -m "feat(web): 登录页(验证码倒计时/限流/锁定提示)"
```

### Task 2.6:协议全文页与首启弹窗

**Files:**
- Create: `web/src/features/legal/LegalPage.vue`、`web/src/features/legal/LegalGate.vue`、`web/src/features/legal/agreed.ts`、`web/src/features/legal/agreement.ts`、`web/src/features/legal/privacy.ts`
- Modify: `web/src/router/index.ts`(加 `/legal/agreement`、`/legal/privacy`)
- Test: `web/tests/component/legal-gate.spec.ts`

**Interfaces:**
- Consumes: `AppButton`、`AppCard`。
- Produces:
  - `LegalPage.vue`:props `kind: 'agreement' | 'privacy'`;正文从 `agreement.ts` / `privacy.ts` 导出(**文案必须与 App 内一致**,实现时从 `app/lib/features/legal/` 逐字抄)
  - `LegalGate.vue`:首启弹窗;同意后写 localStorage 键 `hb.legalAgreed = '1'`
  - `agreed.ts`:`isAgreed(): boolean`(路由守卫与弹窗共用)—— **必须独立成模块**:`<script setup>` 不能对外导出函数,写成 SFC 里的 `export function` 是无效的
- 说明:`/legal/*` 未登录也可访问(spec §5.1)。

- [ ] **Step 1:写失败的测试**

`web/tests/component/legal-gate.spec.ts`:

```ts
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'
import LegalGate from '@/features/legal/LegalGate.vue'
import { isAgreed } from '@/features/legal/agreed'

describe('LegalGate', () => {
  beforeEach(() => localStorage.clear())

  it('未同意时展示弹窗,且必须勾选后才能继续', async () => {
    const w = mount(LegalGate, { global: { stubs: { RouterLink: true } } })
    expect(isAgreed()).toBe(false)
    expect(w.find('.legal-gate').exists()).toBe(true)

    await w.find('.legal-gate__submit').trigger('click')
    expect(isAgreed()).toBe(false)
    expect(w.text()).toContain('请先阅读并同意')
  })

  it('勾选后同意 → 落盘并关闭弹窗', async () => {
    const w = mount(LegalGate, { global: { stubs: { RouterLink: true } } })
    await w.find('input[type="checkbox"]').setValue(true)
    await w.find('.legal-gate__submit').trigger('click')

    expect(isAgreed()).toBe(true)
    expect(w.find('.legal-gate').exists()).toBe(false)
  })

  it('已同意时不再展示', () => {
    localStorage.setItem('hb.legalAgreed', '1')
    const w = mount(LegalGate, { global: { stubs: { RouterLink: true } } })
    expect(w.find('.legal-gate').exists()).toBe(false)
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/component/legal-gate.spec.ts`;Expected: FAIL

- [ ] **Step 3:抄协议文案**

从 App 里逐字复制正文:
- `app/lib/features/legal/` 下的协议与隐私政策正文 → `web/src/features/legal/agreement.ts` / `privacy.ts`
- 每个文件导出一个默认字符串 `export const agreementText = \`...\``(保留段落换行)
- **文案必须逐字一致**(商店审核会比对 App 与网页版本,spec §1 硬约束)

- [ ] **Step 4:实现 `LegalPage.vue` 与 `LegalGate.vue`**

`LegalPage.vue`:

```vue
<script setup lang="ts">
import { computed } from 'vue'
import { agreementText } from './agreement'
import { privacyText } from './privacy'

const props = defineProps<{ kind: 'agreement' | 'privacy' }>()

const title = computed(() => (props.kind === 'agreement' ? '用户协议' : '隐私政策'))
const body = computed(() => (props.kind === 'agreement' ? agreementText : privacyText))
</script>

<template>
  <main class="legal">
    <article class="legal__doc">
      <h1 class="legal__title">{{ title }}</h1>
      <pre class="legal__body">{{ body }}</pre>
    </article>
  </main>
</template>

<style scoped>
.legal { display: flex; justify-content: center; padding: var(--space-section-gap) var(--space-page-h); }
.legal__doc {
  width: clamp(var(--form-card-min), 56%, 760px);
  padding: var(--space-xxl);
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-card);
}
.legal__title { margin: 0 0 var(--space-lg); font-size: var(--text-title); font-weight: var(--weight-bold); }
.legal__body {
  margin: 0;
  font-family: var(--font-latin);
  font-size: var(--text-caption);
  line-height: var(--leading-body);
  white-space: pre-wrap;
  color: var(--color-text1);
}
</style>
```

`agreed.ts`(独立模块,守卫与弹窗共用):

```ts
const AGREED_KEY = 'hb.legalAgreed'

/** 是否已同意协议。 */
export function isAgreed(): boolean {
  return localStorage.getItem(AGREED_KEY) === '1'
}

/** 记录已同意。 */
export function markAgreed(): void {
  localStorage.setItem(AGREED_KEY, '1')
}
```

`LegalGate.vue`:

```vue
<script setup lang="ts">
import { ref } from 'vue'
import AppButton from '@/components/AppButton.vue'
import { isAgreed, markAgreed } from './agreed'

const visible = ref(!isAgreed())
const checked = ref(false)
const hint = ref('')

function onAgree() {
  if (!checked.value) {
    hint.value = '请先阅读并同意以下两份文件'
    return
  }
  markAgreed()
  visible.value = false
}
</script>

<template>
  <div v-if="visible" class="legal-gate" role="dialog" aria-modal="true">
    <div class="legal-gate__panel">
      <h2 class="legal-gate__title">欢迎来到心跳</h2>
      <p class="legal-gate__desc">开始之前,请阅读并同意以下文件:</p>
      <ul class="legal-gate__list">
        <li><RouterLink to="/legal/agreement" target="_blank">《用户协议》</RouterLink></li>
        <li><RouterLink to="/legal/privacy" target="_blank">《隐私政策》</RouterLink></li>
      </ul>
      <label class="legal-gate__check">
        <input v-model="checked" type="checkbox" />
        我已阅读并同意上述文件
      </label>
      <p v-if="hint" class="legal-gate__hint">{{ hint }}</p>
      <AppButton class="legal-gate__submit" block size="lg" @click="onAgree">同意并继续</AppButton>
    </div>
  </div>
</template>

<style scoped>
.legal-gate {
  position: fixed;
  inset: 0;
  z-index: 90;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgb(22 24 29 / 55%);
}
.legal-gate__panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
  width: var(--form-card-max);
  padding: var(--space-xxl);
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-floating-bar);
}
.legal-gate__title { margin: 0; font-size: var(--text-title); font-weight: var(--weight-bold); }
.legal-gate__desc { margin: 0; font-size: var(--text-caption); color: var(--color-text2); }
.legal-gate__list { margin: 0; padding-left: var(--space-lg); font-size: var(--text-body); }
.legal-gate__check { display: flex; align-items: center; gap: var(--space-sm); font-size: var(--text-caption); }
.legal-gate__hint { margin: 0; font-size: var(--text-caption); color: var(--color-danger); }
</style>
```

- [ ] **Step 5:挂到 App.vue 与路由**

`web/src/App.vue` 模板加 `<LegalGate />`(放在 `RouterView` 之后、`AppKickedOverlay` 之前);`/legal/*` 路由:

```ts
{
  path: '/legal/agreement',
  component: () => import('@/features/legal/LegalPage.vue'),
  props: { kind: 'agreement' },
},
{
  path: '/legal/privacy',
  component: () => import('@/features/legal/LegalPage.vue'),
  props: { kind: 'privacy' },
},
```

- [ ] **Step 6:目检 + 测试**

Run: `cd web && npm run test:run && npm run type-check && npm run dev`
目检:清空 localStorage 刷新 → 弹窗出现;点协议链接新标签打开全文;勾选同意后弹窗消失且刷新不再出现。

- [ ] **Step 7:提交**

```bash
git add web/src/features/legal web/src/router web/src/App.vue web/tests/component
git commit -m "feat(web): 用户协议/隐私政策页与首启弹窗"
```

**▶ 组 T2 检查点**:`npm run type-check && npm run lint && npm run test:run` 全绿;登录页能对真后端(`python manage.py runserver`)完成一次真实登录,令牌落 localStorage。

## 组 T3:壳层、路由与自适应布局(6 个任务)

产出:PC 壳层(可拖拽侧栏)+ 完整路由表与守卫 + 移动端引导页 + 四个空壳页联通。

### Task 3.1:路由表与守卫

**Files:**
- Create: `web/src/router/index.ts`(整体替换 Task 1.1 的占位,**保留 Task 1.7 的 `/dev/components`**)、`web/src/router/routes.ts`
- Modify: `web/src/main.ts`(启动时先 `restore()` 再挂载)
- Test: `web/tests/unit/router-guard.spec.ts`

**Interfaces:**
- Consumes: `useSessionStore()`(Task 2.3)、`isMobileDevice()`(Task 3.2)、`isAgreed()`(Task 2.6)。
- Produces:路由名与路径(后续任务全部按此跳转):
  `/login` · `/onboarding` · `/home`(子路由 `discovery`(默认)/`square`/`chats`/`mine`)· `/chat/:peerId` · `/users/:id` · `/posts/:id` · `/posts/compose` · `/my-posts` · `/settings` · `/settings/blocks` · `/profile/edit` · `/preference` · `/legal/agreement` · `/legal/privacy` · `/mobile-guard`
  每条路由 `meta`: `{ public?: boolean }`(无需登录,仅 `/login` 与 `/legal/*`)

- [ ] **Step 1:写失败的测试**

`web/tests/unit/router-guard.spec.ts`:

```ts
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createAppRouter } from '@/router'
import { tokenStore } from '@/api/token-store'

// 移动端判定由 Task 3.2 提供;测试里固定为「桌面」
vi.mock('@/composables/useDevice', () => ({ isMobileDevice: () => false }))

describe('路由守卫', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    localStorage.setItem('hb.legalAgreed', '1')
  })

  it('未登录访问 /home 被送到 /login', async () => {
    const router = createAppRouter()
    await router.push('/home')
    expect(router.currentRoute.value.path).toBe('/login')
  })

  it('未登录可以访问协议全文(公开路由)', async () => {
    const router = createAppRouter()
    await router.push('/legal/privacy')
    expect(router.currentRoute.value.path).toBe('/legal/privacy')
  })

  it('已登录访问 /login 被送回首页发现页', async () => {
    tokenStore.access = 'a'
    tokenStore.refresh = 'r'
    const router = createAppRouter()
    await router.push('/login')
    // /home 的默认子路由是 discovery,故最终落地路径是 /home/discovery
    expect(router.currentRoute.value.path).toBe('/home/discovery')
  })

  it('移动端浏览器一律进引导页', async () => {
    vi.resetModules()
    vi.doMock('@/composables/useDevice', () => ({ isMobileDevice: () => true }))
    const { createAppRouter: make } = await import('@/router')
    const router = make()
    await router.push('/home')
    expect(router.currentRoute.value.path).toBe('/mobile-guard')
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/unit/router-guard.spec.ts`;Expected: FAIL,`createAppRouter` 不存在

- [ ] **Step 3:实现路由**

`web/src/router/routes.ts`:

```ts
import type { RouteRecordRaw } from 'vue-router'

/** 页面组件一律懒加载:首屏只加载当前路由需要的代码。 */
export const routes: RouteRecordRaw[] = [
  { path: '/login', name: 'login', component: () => import('@/features/auth/LoginPage.vue'), meta: { public: true } },
  { path: '/legal/agreement', name: 'legal-agreement', component: () => import('@/features/legal/LegalPage.vue'), props: { kind: 'agreement' }, meta: { public: true } },
  { path: '/legal/privacy', name: 'legal-privacy', component: () => import('@/features/legal/LegalPage.vue'), props: { kind: 'privacy' }, meta: { public: true } },
  { path: '/mobile-guard', name: 'mobile-guard', component: () => import('@/layouts/MobileGuard.vue'), meta: { public: true } },
  { path: '/onboarding', name: 'onboarding', component: () => import('@/features/onboarding/OnboardingPage.vue') },
  { path: '/banned', name: 'banned', component: () => import('@/features/shell/BannedPage.vue'), meta: { public: true } },
  {
    path: '/home',
    component: () => import('@/layouts/DesktopShell.vue'),
    children: [
      { path: '', redirect: { name: 'discovery' } },
      { path: 'discovery', name: 'discovery', component: () => import('@/features/discovery/DiscoveryPage.vue') },
      { path: 'square', name: 'square', component: () => import('@/features/square/SquarePage.vue') },
      { path: 'chats', name: 'chats', component: () => import('@/features/chat/ChatsPage.vue') },
      { path: 'mine', name: 'mine', component: () => import('@/features/profile/MyProfilePage.vue') },
    ],
  },
  { path: '/chat/:peerId', name: 'chat', component: () => import('@/features/chat/ChatPage.vue'), props: true },
  { path: '/users/:id', name: 'user-profile', component: () => import('@/features/profile/UserProfilePage.vue'), props: true },
  { path: '/posts/compose', name: 'post-compose', component: () => import('@/features/square/PostComposePage.vue') },
  { path: '/my-posts', name: 'my-posts', component: () => import('@/features/square/MyPostsPage.vue') },
  { path: '/posts/:id', name: 'post-detail', component: () => import('@/features/square/PostDetailPage.vue'), props: true },
  { path: '/settings', name: 'settings', component: () => import('@/features/settings/SettingsPage.vue') },
  { path: '/settings/blocks', name: 'settings-blocks', component: () => import('@/features/settings/BlockedUsersPage.vue') },
  { path: '/profile/edit', name: 'profile-edit', component: () => import('@/features/profile/ProfileEditPage.vue') },
  { path: '/preference', name: 'preference', component: () => import('@/features/profile/PreferencePage.vue') },
]
```

`web/src/router/index.ts`:

```ts
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { isMobileDevice } from '@/composables/useDevice'
import { useSessionStore } from '@/stores/session'
import { routes } from './routes'

function devRoutes(): RouteRecordRaw[] {
  return import.meta.env.DEV
    ? [{ path: '/dev/components', component: () => import('@/features/dev/ComponentsPage.vue') }]
    : []
}

export function createAppRouter() {
  const router = createRouter({
    history: createWebHistory(),
    routes: [...routes, ...devRoutes()],
  })

  router.beforeEach(async (to) => {
    // 1) 移动端浏览器:一律引导页(spec §6.1,按设备判定,不看窗口宽度)
    if (isMobileDevice() && to.name !== 'mobile-guard') {
      return { name: 'mobile-guard' }
    }

    // 2) 会话态:首次进入先恢复
    const session = useSessionStore()
    if (session.status === 'loading') await session.restore()

    // 3) 公开路由直接放行(协议全文未登录也要能看)
    if (to.meta.public) {
      // 已登录还停在登录页 → 回家。
      // ⚠️ 这里**不能**把 mobile-guard 也重定向:否则会死循环
      //    (移动端 → 引导页 → 已登录 → 首页 → 移动端 → 引导页 → …)
      if (session.status === 'loggedIn' && to.name === 'login') {
        return { name: 'discovery' }
      }
      return true
    }

    if (session.status !== 'loggedIn') return { name: 'login' }
    return true
  })

  return router
}

export const router = createAppRouter()
```

- [ ] **Step 4:跑测试确认通过** → Run: `cd web && npm run test:run tests/unit/router-guard.spec.ts && npm run type-check`
Expected: 4 passed。此时尚未创建的页面组件会在**运行**时报错(懒加载),不影响单测;Task 3.6 会把它们补齐。

- [ ] **Step 5:提交**

```bash
git add web/src/router web/tests/unit
git commit -m "feat(web): 路由表与守卫(会话态/移动端/公开路由)"
```

### Task 3.2:设备判定与移动端引导页

**Files:**
- Create: `web/src/composables/useDevice.ts`、`web/src/layouts/MobileGuard.vue`
- Test: `web/tests/unit/use-device.spec.ts`、`web/tests/component/mobile-guard.spec.ts`

**Interfaces:**
- Produces:`isMobileDevice(): boolean` —— 读 `navigator.platform` + UA + `maxTouchPoints`(**不读窗口宽度**;iPad 伪装成 Mac 时按 `maxTouchPoints > 2` 判为移动端,与 Flutter 同判据)
- `MobileGuard.vue`:居中引导页;下载按钮按 `DOWNLOADS_ENABLED` 决定可用或「敬请期待」禁用态

- [ ] **Step 1:写失败的测试**

`web/tests/unit/use-device.spec.ts`:

```ts
import { describe, expect, it, vi } from 'vitest'
import { isMobileDevice } from '@/composables/useDevice'

function fakeNavigator(platform: string, userAgent: string, maxTouchPoints = 0) {
  Object.defineProperty(window, 'navigator', {
    configurable: true,
    value: { platform, userAgent, maxTouchPoints },
  })
}

describe('isMobileDevice', () => {
  it('iPhone 判为移动端', () => {
    fakeNavigator('iPhone', 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)')
    expect(isMobileDevice()).toBe(true)
  })

  it('Android 判为移动端', () => {
    fakeNavigator('Linux armv8l', 'Mozilla/5.0 (Linux; Android 14; Pixel 8)')
    expect(isMobileDevice()).toBe(true)
  })

  it('Windows 桌面判为桌面端', () => {
    fakeNavigator('Win32', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/140.0')
    expect(isMobileDevice()).toBe(false)
  })

  it('iPad 伪装成 Mac(多点触控)仍判为移动端', () => {
    fakeNavigator('MacIntel', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)', 5)
    expect(isMobileDevice()).toBe(true)
  })

  it('真 Mac 判为桌面端', () => {
    fakeNavigator('MacIntel', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)', 0)
    expect(isMobileDevice()).toBe(false)
  })

  it('窗口很窄不影响判定(不是像素断点)', () => {
    fakeNavigator('Win32', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)')
    window.innerWidth = 500
    expect(isMobileDevice()).toBe(false)
  })
})
```

`web/tests/component/mobile-guard.spec.ts`:

```ts
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import MobileGuard from '@/layouts/MobileGuard.vue'

describe('MobileGuard', () => {
  it('提示去电脑打开、手机用 App', () => {
    const w = mount(MobileGuard)
    expect(w.text()).toContain('请在电脑上打开网页版')
    expect(w.text()).toContain('手机上请使用「心跳」App')
  })

  it('商店未上架时下载按钮为「敬请期待」且不可点', () => {
    const w = mount(MobileGuard)
    const btn = w.find('button')
    expect(btn.text()).toContain('敬请期待')
    expect(btn.attributes('disabled')).toBeDefined()
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/unit/use-device.spec.ts`;Expected: FAIL

- [ ] **Step 3:实现**

`web/src/composables/useDevice.ts`:

```ts
/**
 * 是否移动端浏览器。
 * 判据与 Flutter 的 ui_web.browser 一致:platform + UA + maxTouchPoints,
 * **不使用窗口宽度**(spec §6.1:窗口拖窄仍是 PC 壳层)。
 */
export function isMobileDevice(): boolean {
  if (typeof navigator === 'undefined') return false

  const platform = navigator.platform ?? ''
  const ua = navigator.userAgent ?? ''
  const maxTouchPoints = navigator.maxTouchPoints ?? 0

  // iPad 请求「桌面版网站」时 platform 会是 MacIntel,靠多点触控识别
  if (platform.startsWith('Mac')) return maxTouchPoints > 2

  if (/iphone|ipad|ipod/i.test(platform)) return true
  if (/Android/i.test(ua)) return true

  return false
}
```

`web/src/layouts/MobileGuard.vue`:

```vue
<script setup lang="ts">
import AppButton from '@/components/AppButton.vue'
import { APP_NAME, DOWNLOADS_ENABLED } from '@/constants'
</script>

<template>
  <main class="guard">
    <section class="guard__panel">
      <span class="guard__logo">♥ {{ APP_NAME }}</span>
      <h1 class="guard__title">请在电脑上打开网页版</h1>
      <p class="guard__desc">手机上请使用「{{ APP_NAME }}」App,体验更完整。</p>
      <AppButton block size="lg" :disabled="!DOWNLOADS_ENABLED">
        {{ DOWNLOADS_ENABLED ? '下载 App' : '下载 App · 敬请期待' }}
      </AppButton>
    </section>
  </main>
</template>

<style scoped>
.guard {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: var(--space-section-gap);
  background: var(--color-bg-page);
}
.guard__panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
  width: clamp(280px, 82%, var(--form-card-max));
  padding: var(--space-xxl);
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-card);
  text-align: center;
}
.guard__logo { font-size: var(--text-title); font-weight: var(--weight-bold); color: var(--color-brand); }
.guard__title { margin: 0; font-size: var(--text-title); font-weight: var(--weight-bold); }
.guard__desc { margin: 0; font-size: var(--text-caption); color: var(--color-text2); }
</style>
```

- [ ] **Step 4:跑测试确认通过** → Run: `cd web && npm run test:run && npm run type-check`;Expected: 全绿

- [ ] **Step 5:提交**

```bash
git add web/src/composables web/src/layouts web/tests
git commit -m "feat(web): 设备判定与移动端引导页"
```

### Task 3.3:侧栏几何(拖拽 / 阈值 / 记忆)与一致性测试

**Files:**
- Create: `web/src/layout.ts`、`web/src/composables/useSidebar.ts`
- Test: `web/tests/unit/layout-consistency.spec.ts`、`web/tests/unit/use-sidebar.spec.ts`

**Interfaces:**
- Produces:
  - `layout.ts`:`SIDEBAR` 常量对象(`{ ratio: 0.16, min: 208, max: 264, dragMin: 72, dragMax: 360, iconThreshold: 176, defaultWidth(viewportWidth: number): number }`)
  - `useSidebar()`:返回 `{ width, isIconOnly, isDragging, beginDrag(event), resetToDefault() }`;宽度持久化到 localStorage 键 `hb.sidebarWidth`
- **两个真相源的问题与解法**:CSS 需要这些数值做样式,JS 需要它们做拖拽数学。`tokens.css` 与 `layout.ts` 各存一份,由 `layout-consistency.spec.ts` 断言两边一致(与 Dart↔CSS 的 token 测试同一套纪律)。

- [ ] **Step 1:写失败的一致性测试**

`web/tests/unit/layout-consistency.spec.ts`:

```ts
import { readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'
import { describe, expect, it } from 'vitest'
import { layout } from '@/layout'

const css = readFileSync(fileURLToPath(new URL('../../src/styles/tokens.css', import.meta.url)), 'utf8')

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
})
```

`web/tests/unit/use-sidebar.spec.ts`:

```ts
import { beforeEach, describe, expect, it } from 'vitest'
import { layout, useSidebar } from '@/layout'

function setViewport(width: number) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: width })
}

describe('useSidebar', () => {
  beforeEach(() => localStorage.clear())

  it('默认宽度 = 窗口宽 × 16%,并夹在 208–264', () => {
    setViewport(1280)
    expect(useSidebar().width.value).toBe(208) // 1280 * 0.16 = 204.8 → 夹到 208
    setViewport(1920)
    expect(useSidebar().width.value).toBeCloseTo(264, 0) // 307.2 → 夹到 264
  })

  it('宽度低于阈值时切图标态', () => {
    const s = useSidebar()
    s.width.value = layout.sidebar.iconThreshold - 1
    expect(s.isIconOnly.value).toBe(true)
    s.width.value = layout.sidebar.iconThreshold
    expect(s.isIconOnly.value).toBe(false)
  })

  it('拖拽被夹在 72–360', () => {
    setViewport(1280)
    const s = useSidebar()
    s.setWidthForTest(10)
    expect(s.width.value).toBe(layout.sidebar.dragMin)
    s.setWidthForTest(9999)
    expect(s.width.value).toBe(layout.sidebar.dragMax)
  })

  it('宽度写入 localStorage,重新创建时沿用', () => {
    setViewport(1280)
    const s = useSidebar()
    s.setWidthForTest(300)
    expect(localStorage.getItem('hb.sidebarWidth')).toBe('300')
    expect(useSidebar().width.value).toBe(300)
  })

  it('双击复位到默认宽度', () => {
    setViewport(1280)
    const s = useSidebar()
    s.setWidthForTest(320)
    s.resetToDefault()
    expect(s.width.value).toBe(208)
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/unit/use-sidebar.spec.ts`;Expected: FAIL

- [ ] **Step 3:实现 `layout.ts`(行为参数与 useSidebar 同文件,便于测试)**

`web/src/layout.ts`:

```ts
import { computed, ref, type Ref } from 'vue'

/**
 * 自适应布局的行为参数(拖拽数学需要数字,故 JS 也要一份)。
 * ⚠️ 与 src/styles/tokens.css 的 --sidebar-* 必须一致,由 tests/unit/layout-consistency.spec.ts 兜底。
 */
export const layout = {
  sidebar: {
    ratio: 0.16,
    min: 208,
    max: 264,
    dragMin: 72,
    dragMax: 360,
    iconThreshold: 176,
  },
  chatList: { ratio: 0.22, min: 264, max: 360 },
  bubbleMaxRatio: 0.72,
} as const

const STORAGE_KEY = 'hb.sidebarWidth'

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
}

function defaultWidth(viewportWidth: number): number {
  const { ratio, min, max } = layout.sidebar
  return Math.round(clamp(viewportWidth * ratio, min, max))
}

function readStoredWidth(): number | null {
  const raw = localStorage.getItem(STORAGE_KEY)
  if (raw === null) return null
  const parsed = Number(raw)
  return Number.isNaN(parsed) ? null : parsed
}

export interface SidebarState {
  width: Ref<number>
  isIconOnly: Ref<boolean>
  isDragging: Ref<boolean>
  beginDrag: (event: PointerEvent) => void
  resetToDefault: () => void
  /** 仅供测试:直接设定宽度(仍走夹取与持久化) */
  setWidthForTest: (value: number) => void
}

export function useSidebar(): SidebarState {
  const { dragMin, dragMax, iconThreshold } = layout.sidebar
  const width = ref(readStoredWidth() ?? defaultWidth(window.innerWidth))
  const isDragging = ref(false)

  function setWidth(value: number) {
    width.value = Math.round(clamp(value, dragMin, dragMax))
    localStorage.setItem(STORAGE_KEY, String(width.value))
  }

  function beginDrag(event: PointerEvent) {
    event.preventDefault()
    isDragging.value = true
    const startX = event.clientX
    const startWidth = width.value

    const onMove = (e: PointerEvent) => setWidth(startWidth + (e.clientX - startX))
    const onUp = () => {
      isDragging.value = false
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }

    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }

  return {
    width,
    isIconOnly: computed(() => width.value < iconThreshold),
    isDragging,
    beginDrag,
    resetToDefault: () => setWidth(defaultWidth(window.innerWidth)),
    setWidthForTest: setWidth,
  }
}
```

- [ ] **Step 4:跑测试确认通过** → Run: `cd web && npm run test:run tests/unit && npm run type-check`
Expected: 全绿

- [ ] **Step 5:提交**

```bash
git add web/src/layout.ts web/tests/unit
git commit -m "feat(web): 侧栏几何(拖拽/阈值/记忆)与 JS-CSS 一致性测试"
```

### Task 3.4:DesktopShell 与可拖拽侧栏

**Files:**
- Create: `web/src/layouts/DesktopShell.vue`、`web/src/components/AppSidebar.vue`
- Test: `web/tests/component/app-sidebar.spec.ts`

**Interfaces:**
- Consumes: `useSidebar()`、`AppAvatar` / `AppBadge`、`useSessionStore()`。
- Produces:
  - `AppSidebar.vue`:props `{ width: number; iconOnly: boolean }`;emits `resize-start`、`resize-reset`
  - `DesktopShell.vue`:左栏 + 右内容区(`<RouterView />`);侧栏选中项由**当前路由名**驱动
- 导航四项:`discovery` 发现 / `chats` 消息(带未读角标)/ `square` 广场 / `mine` 我的;底部 `settings` 设置 + 当前用户头像昵称

- [ ] **Step 1:写失败的测试**

`web/tests/component/app-sidebar.spec.ts`:

```ts
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import AppSidebar from '@/components/AppSidebar.vue'
import { layout } from '@/layout'

function mountSidebar(width = 240) {
  return mount(AppSidebar, {
    props: { width, iconOnly: width < layout.sidebar.iconThreshold },
    global: {
      plugins: [createPinia()],
      stubs: { RouterLink: { template: '<a><slot /></a>' } },
    },
  })
}

describe('AppSidebar', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('宽态展示图标与文字', () => {
    const w = mountSidebar(240)
    expect(w.text()).toContain('发现')
    expect(w.text()).toContain('广场')
    expect(w.classes()).not.toContain('app-sidebar--icon-only')
  })

  it('窄态只显示图标,并给出 tooltip', () => {
    const w = mountSidebar(120)
    expect(w.classes()).toContain('app-sidebar--icon-only')
    expect(w.find('[title="发现"]').exists()).toBe(true)
  })

  it('拖拽手柄按下时派发 resize-start', async () => {
    const w = mountSidebar(240)
    await w.find('.app-sidebar__handle').trigger('pointerdown')
    expect(w.emitted('resize-start')).toHaveLength(1)
  })

  it('双击手柄复位', async () => {
    const w = mountSidebar(240)
    await w.find('.app-sidebar__handle').trigger('dblclick')
    expect(w.emitted('resize-reset')).toHaveLength(1)
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/component/app-sidebar.spec.ts`;Expected: FAIL

- [ ] **Step 3:实现 `AppSidebar.vue`**

```vue
<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AppAvatar from './AppAvatar.vue'
import AppBadge from './AppBadge.vue'
import { useSessionStore } from '@/stores/session'

const props = defineProps<{ width: number; iconOnly: boolean; unreadTotal?: number }>()
const emit = defineEmits<{ 'resize-start': [PointerEvent]; 'resize-reset': [] }>()

const route = useRoute()
const session = useSessionStore()

const navItems = [
  { name: 'discovery', label: '发现', icon: '❤️' },
  { name: 'chats', label: '消息', icon: '💬', badge: true },
  { name: 'square', label: '广场', icon: '🌟' },
  { name: 'mine', label: '我的', icon: '🙂' },
] as const

/** 当前子路由名(用于选中态);详情页时高亮其所属一级页 */
const currentSection = computed(() => {
  const name = String(route.name ?? '')
  if (name === 'chat') return 'chats'
  if (name === 'post-detail' || name === 'post-compose' || name === 'my-posts') return 'square'
  if (name === 'user-profile' || name === 'profile-edit' || name === 'preference') return 'mine'
  return name
})
</script>

<template>
  <aside
    class="app-sidebar"
    :class="{ 'app-sidebar--icon-only': props.iconOnly }"
    :style="{ width: `${props.width}px` }"
  >
    <div class="app-sidebar__brand">♥<span v-if="!props.iconOnly"> 心跳</span></div>

    <nav class="app-sidebar__nav">
      <RouterLink
        v-for="item in navItems"
        :key="item.name"
        class="app-sidebar__item"
        :class="{ 'app-sidebar__item--active': currentSection === item.name }"
        :to="{ name: item.name }"
        :title="props.iconOnly ? item.label : undefined"
      >
        <span class="app-sidebar__icon">{{ item.icon }}</span>
        <span v-if="!props.iconOnly" class="app-sidebar__label">{{ item.label }}</span>
        <AppBadge v-if="item.badge && !props.iconOnly" :count="props.unreadTotal ?? 0" />
      </RouterLink>
    </nav>

    <div class="app-sidebar__foot">
      <RouterLink class="app-sidebar__item" :to="{ name: 'settings' }" title="设置">
        <span class="app-sidebar__icon">⚙️</span>
        <span v-if="!props.iconOnly" class="app-sidebar__label">设置</span>
      </RouterLink>
      <RouterLink class="app-sidebar__me" :to="{ name: 'mine' }">
        <AppAvatar :size="28" />
        <span v-if="!props.iconOnly" class="app-sidebar__label">我的资料</span>
      </RouterLink>
    </div>

    <!-- 拖拽手柄:悬停变 resizeLeftRight 指针;双击复位默认宽度 -->
    <div
      class="app-sidebar__handle"
      role="separator"
      aria-orientation="vertical"
      @pointerdown="emit('resize-start', $event)"
      @dblclick="emit('resize-reset')"
    />
  </aside>
</template>

<style scoped>
.app-sidebar {
  position: relative;
  display: flex;
  flex-direction: column;
  flex: none;
  height: 100vh;
  padding: var(--space-lg) var(--space-md);
  background: var(--color-bg-card);
  border-right: 1px solid var(--color-divider);
}
.app-sidebar__brand {
  padding: 0 var(--space-sm) var(--space-lg);
  font-size: var(--text-subtitle);
  font-weight: var(--weight-bold);
  color: var(--color-brand);
}
.app-sidebar__nav { display: flex; flex: 1; flex-direction: column; gap: var(--space-xs); }
.app-sidebar__item {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  height: 44px;
  padding: 0 var(--space-sm);
  border-radius: var(--radius-chip);
  color: var(--color-text1);
  transition: background var(--motion-fast) var(--ease-out);
}
.app-sidebar__item:hover { background: var(--hover-overlay); }
/* 选中态:本屏唯一高音(spec §6.2) */
.app-sidebar__item--active {
  background: rgb(255 44 85 / 8%);
  color: var(--color-brand);
  font-weight: var(--weight-semibold);
}
.app-sidebar__icon { font-size: var(--text-body); }
.app-sidebar__label { flex: 1; font-size: var(--text-body); }
.app-sidebar__foot { display: flex; flex-direction: column; gap: var(--space-xs); }
.app-sidebar__me { display: flex; align-items: center; gap: var(--space-sm); padding: var(--space-sm); }
.app-sidebar--icon-only .app-sidebar__item,
.app-sidebar--icon-only .app-sidebar__me { justify-content: center; padding: 0; }

.app-sidebar__handle {
  position: absolute;
  top: 0;
  right: -3px;
  width: 6px;
  height: 100%;
  cursor: col-resize; /* 左右拖拽指针(CSS 里没有 resize-left-right 这个值) */
}
.app-sidebar__handle:hover { background: var(--hover-overlay-strong); }
</style>
```

- [ ] **Step 4:实现 `DesktopShell.vue`**

```vue
<script setup lang="ts">
import AppSidebar from '@/components/AppSidebar.vue'
import { useSidebar } from '@/layout'
import { useChatStore } from '@/stores/chat'

const sidebar = useSidebar()
const chat = useChatStore()
</script>

<template>
  <div class="shell" :class="{ 'shell--dragging': sidebar.isDragging.value }">
    <AppSidebar
      :width="sidebar.width.value"
      :icon-only="sidebar.isIconOnly.value"
      :unread-total="chat.unreadTotal"
      @resize-start="sidebar.beginDrag"
      @resize-reset="sidebar.resetToDefault"
    />
    <main class="shell__content">
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.shell { display: flex; height: 100vh; overflow: hidden; }
.shell--dragging { user-select: none; }
/* 内容区吃满剩余空间(spec §6.3),不居中留白 */
.shell__content { flex: 1; min-width: 0; overflow-y: auto; }
</style>
```

> `useChatStore` 的 `unreadTotal` 在 **Task 6.4** 创建。在 T3 阶段先建立最小 store 占位:

`web/src/stores/chat.ts`(T3 占位版,Task 6.4 会替换为完整实现):

```ts
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export const useChatStore = defineStore('chat', () => {
  const conversations = ref<{ unreadCount: number }[]>([])
  const unreadTotal = computed(() =>
    conversations.value.reduce((sum, c) => sum + c.unreadCount, 0),
  )
  return { conversations, unreadTotal }
})
```

- [ ] **Step 5:跑测试确认通过** → Run: `cd web && npm run test:run && npm run type-check`;Expected: 全绿

- [ ] **Step 6:提交**

```bash
git add web/src/layouts web/src/components/AppSidebar.vue web/src/stores/chat.ts web/tests/component
git commit -m "feat(web): DesktopShell 与可拖拽侧栏"
```

### Task 3.5:四个一级页空壳(打通壳层)

**Files:**
- Create: `web/src/features/discovery/DiscoveryPage.vue`、`web/src/features/square/SquarePage.vue`、`web/src/features/chat/ChatsPage.vue`、`web/src/features/profile/MyProfilePage.vue`、`web/src/features/settings/SettingsPage.vue`、`web/src/features/settings/BlockedUsersPage.vue`、`web/src/features/profile/ProfileEditPage.vue`、`web/src/features/profile/PreferencePage.vue`、`web/src/features/profile/UserProfilePage.vue`、`web/src/features/square/PostComposePage.vue`、`web/src/features/square/PostDetailPage.vue`、`web/src/features/square/MyPostsPage.vue`、`web/src/features/chat/ChatPage.vue`、`web/src/features/onboarding/OnboardingPage.vue`、`web/src/features/shell/BannedPage.vue`
- Test: `web/tests/unit/routes-resolve.spec.ts`

**Interfaces:**
- Produces:每个文件一个最小页面(标题 + 一句占位说明),后续组逐个替换为真实实现。**目的是让路由全表可跳转**,先把壳层跑起来。

- [ ] **Step 1:写失败的路由可解析测试**

`web/tests/unit/routes-resolve.spec.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { routes } from '@/router/routes'

/** 递归收集所有懒加载组件,逐个 import 以确保文件真实存在(防止拼错路径)。 */
function collect(records: readonly any[]): { name: string; load: () => Promise<unknown> }[] {
  const out: { name: string; load: () => Promise<unknown> }[] = []
  for (const r of records) {
    const name = r.name ?? r.path
    if (typeof r.component === 'function') out.push({ name, load: r.component })
    if (r.children) out.push(...collect(r.children))
  }
  return out
}

describe('路由表', () => {
  const entries = collect(routes)

  it('覆盖 spec §5.1 要求的全部页面', () => {
    const names = entries.map((e) => e.name)
    for (const required of [
      'login', 'onboarding', 'discovery', 'square', 'chats', 'mine',
      'chat', 'user-profile', 'post-detail', 'post-compose', 'my-posts',
      'settings', 'settings-blocks', 'profile-edit', 'preference',
      'legal-agreement', 'legal-privacy', 'mobile-guard', 'banned',
    ]) {
      expect(names, `缺少路由 ${required}`).toContain(required)
    }
  })

  it('每个懒加载组件都能真实加载(路径没写错)', async () => {
    for (const entry of entries) {
      await expect(entry.load(), `${entry.name} 加载失败`).resolves.toBeTruthy()
    }
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/unit/routes-resolve.spec.ts`;Expected: FAIL(多个文件不存在)

- [ ] **Step 3:批量创建空壳页**

每个页面用同一套最小结构(以 `DiscoveryPage.vue` 为例,其余照此替换标题):

```vue
<script setup lang="ts"></script>

<template>
  <section class="page">
    <h1 class="page__title">发现</h1>
    <p class="page__hint">待实现(T5)</p>
  </section>
</template>

<style scoped>
.page { padding: var(--space-section-gap); }
.page__title { margin: 0 0 var(--space-xs); font-size: var(--text-display); font-weight: var(--weight-extrabold); }
.page__hint { margin: 0; font-size: var(--text-caption); color: var(--color-text2); }
</style>
```

各文件标题与提示:发现(T5)/ 广场(T7)/ 消息(T6)/ 我的(T4)/ 设置(T8)/ 黑名单(T8)/ 编辑资料(T4)/ 择偶偏好(T4)/ 用户资料(T5)/ 发布动态(T7)/ 动态详情(T7)/ 我的动态(T7)/ 聊天(T6)/ 完善资料(T4)/ 账号已被封禁(T3)。

`BannedPage.vue` 文案固定(与 App 语义一致):

```vue
<template>
  <section class="page">
    <h1 class="page__title">账号已被封禁</h1>
    <p class="page__hint">你的账号因违反社区规范已被限制使用。如有疑问请联系客服。</p>
  </section>
</template>
```

- [ ] **Step 4:跑测试确认通过** → Run: `cd web && npm run test:run && npm run type-check`;Expected: 全绿

- [ ] **Step 5:端到端目检(壳层通)**

Run: `cd chatapp && python manage.py runserver`(另开一个终端)+ `cd web && npm run dev`
浏览器:
1. 打开 `http://localhost:5173/home/discovery` → 被送到 `/login`
2. 登录后 → 进壳层,左侧四项可点,URL 随之变化
3. 拖动侧栏边缘 → 变宽变窄;**拖到 176px 以下 → 只剩图标**;双击边缘复位
4. 刷新页面 → 侧栏宽度仍是刚才拖的
5. 用 DevTools 把设备切到 iPhone → 刷新 → 进引导页

- [ ] **Step 6:提交**

```bash
git add web/src/features web/src/layouts web/tests
git commit -m "feat(web): 全部路由空壳与壳层目检"
```

**▶ 组 T3 检查点**:门禁全绿 + 上面 5 项目检全过。此时代码已能「登录 → 在 PC 壳层里浏览骨架」。

---

## 后续分组(T4–T10):任务清单与接口边界

T1–T3 已写到「可直接照着敲」的粒度。T4 起**暂不预先写死代码**,原因很具体:

> T4–T10 的组件代码要用到 T1–T3 建出来的**真实接口**(`useSessionStore` 的实际返回、`http` 的调用形态、`layout` 常量的名字、壳层的插槽结构)。如果现在凭空写出 43 个任务的完整代码,等 T1–T3 落地时必然大面积对不上,反而制造返工。**项目自身已有先例**:M1 拆成 m1a/m1b、M2 拆成 m2a/m2b/m2c 三个计划文件就是这个道理。

因此:**每进入下一组之前,先把该组展开成本文件 T1–T3 同等粒度的完整步骤**(写成 `docs/superpowers/plans/2026-10-05-web-features.md`、`-web-chat.md` 等)。这不改变交付节奏 —— 仍然是一次连续推进、不分批交付,只是让计划里的代码始终对着已经存在的接口写。

**全计划共 55 个任务**:T1–T3 已在下方展开为 18 个;T4–T10 的 37 个见后续分组表。

下面每组的**任务、文件、接口、测试、验收**都已定死,展开时不得增删范围。

### T4 引导与资料(6 个任务)

| # | 任务 | 文件 | 测试要点 |
|---|---|---|---|
| 4.1 | `api/users.ts` + `stores/profile.ts`(GET/PATCH `/users/me`、`/users/tags`、`/users/me/preference`) | `src/api/users.ts`、`src/stores/profile.ts` | 资料加载;写操作后失效重取;`missing_fields` 透传 |
| 4.2 | 编辑资料页(昵称/性别/生日/城市/简介) | `src/features/profile/ProfileEditPage.vue` | 必填校验;未满 18 岁 400 文案展示;保存后 store 更新 |
| 4.3 | 标签选择(12 个标签池) | `src/features/profile/TagPicker.vue` | 选中/取消;提交 `tag_ids`;超出后端限制时的错误展示 |
| 4.4 | 照片网格(上传/删除/审核状态) | `src/features/profile/PhotoGrid.vue` | ≤5MB 与 ≤6 张前端拦截;multipart 字段名 `file`;审核中徽标 |
| 4.5 | 择偶偏好页(目标性别可空=不限/年龄区间/城市) | `src/features/profile/PreferencePage.vue` | 空性别提交;年龄区间反向时报错 |
| 4.6 | 我的页 + 完善资料页 + **封禁守卫** | `MyProfilePage.vue`、`OnboardingPage.vue`、`router/index.ts` | `status==='banned_heavy'` → `/banned`;`incomplete` → 停 `/onboarding` |

**Interfaces 产出**:`useProfileStore()`(state:`profile`、`tags`、`status`;actions:`load()`、`save(patch)`、`uploadPhoto(file)`、`deletePhoto(id)`)、`ProfileStatus` 类型。

### T5 发现与配对(5 个任务)

| # | 任务 | 文件 | 测试要点 |
|---|---|---|---|
| 5.1 | `api/discovery.ts` + `stores/discovery.ts` | `src/api/discovery.ts`、`src/stores/discovery.ts` | 候选卡拉取;滑卡幂等;幂等重复提交不双发 |
| 5.2 | 候选卡组件(照片全出血 + 底部 scrim 叠字 + 在线光) | `src/features/discovery/CandidateCard.vue` | 叠字可读性;无照片兜底;在线光只在线时出现 |
| 5.3 | 滑卡交互(拖拽 + 键盘 `←`/`→` + 两个圆钮)与配对情感时刻 | `src/features/discovery/SwipeDeck.vue` | 状态机:like/pass/耗尽;**键盘与拖拽走同一处理函数**;配对时触发情感时刻 |
| 5.4 | 配对列表(分页) | `src/features/discovery/MatchesList.vue` | 分页加载;点击进 `/chat/:peerId` |
| 5.5 | 发现页组装 | `src/features/discovery/DiscoveryPage.vue` | 加载/空态/错误重试/429 限流文案;悬停照片出「查看资料」→ `/users/:id` |

### T6 聊天(8 个任务)—— 风险最高的一组

| # | 任务 | 文件 | 测试要点 |
|---|---|---|---|
| 6.1 | **IM 通路验证 spike(不写进仓库正式代码)** | 临时页面 | 浏览器内完成「`login` → 收到一条消息 → 发出一条消息」。**不过就停下来找用户**,不要在坏地基上继续 |
| 6.2 | `im/client.ts`:SDK 初始化、登录、登出、事件总线 | `src/im/client.ts`、`src/im/types.ts` | 事件映射为纯函数的单测(4 类事件) |
| 6.3 | `im/map.ts`:SDK 消息 → `ChatMessage` | `src/im/map.ts` | 纯函数:文本/图片/自定义灰条(`match_notice`/`ban_notice`/`report_handled`/`post_commented`) |
| 6.4 | `stores/chat.ts` 完整版(替换 T3 占位) | `src/stores/chat.ts` | 会话四态;未读聚合;系统通知置顶;`u{user_id}` 解析对端账号 |
| 6.5 | 消息页 | `src/features/chat/ChatsPage.vue` | 会话行/通知行/骨架/空态/错误重试/最近联系人横滑条 |
| 6.6 | 聊天页 | `src/features/chat/ChatPage.vue` | 历史;气泡;时间条(间隔 > 5 分钟);发送;失败重发;进入即清未读 |
| 6.7 | 图片消息与灯箱 | `src/features/chat/MessageImage.vue` | 选图 → blob 预览 → 发送;灯箱按 `Esc`/点遮罩关闭 |
| 6.8 | 表情面板 + 消息菜单(悬停 ⋯ / 右键) | `src/features/chat/EmojiPanel.vue`、`MessageMenu.vue` | 右键与悬停按钮走同一菜单;复制文字;删除本地;重发 |

### T7 广场(6 个任务)

| # | 任务 | 文件 | 测试要点 |
|---|---|---|---|
| 7.1 | `api/feed.ts` + `stores/feed.ts` | `src/api/feed.ts`、`src/stores/feed.ts` | 分页游标;`mine`;详情;点赞;评论;举报 |
| 7.2 | 动态流页(**列数随宽度自适应**,单卡上限 `--feed-card-max`) | `src/features/square/SquarePage.vue` | 1920→3 列 / 1440→2 列 / 窄→1 列;分页到底自动加载;四态 |
| 7.3 | 动态卡片 + 点赞乐观更新 | `src/features/square/PostCard.vue` | 乐观 +1/-1;失败回滚;重复点赞不重复计数 |
| 7.4 | 发布动态(文字 + 多图) | `src/features/square/PostComposePage.vue` | 空内容禁止提交;多图预览与移除;超限提示 |
| 7.5 | 动态详情 + 评论 | `src/features/square/PostDetailPage.vue`、`CommentList.vue` | 评论分页;发表后插入列表;空评论态 |
| 7.6 | 我的动态 + 删除 + 举报动态 | `src/features/square/MyPostsPage.vue` | 删除二次确认;删除后从列表移除;举报弹窗复用 T8.3 |

### T8 设置 / 拉黑 / 举报 / 在线状态(4 个任务)

| # | 任务 | 文件 | 测试要点 |
|---|---|---|---|
| 8.1 | 设置页 + 退出登录(先登出 IM 再清凭证) | `src/features/settings/SettingsPage.vue` | 退出后 localStorage 清空、路由回 `/login` |
| 8.2 | 黑名单(分页 + 解除拉黑) | `src/features/settings/BlockedUsersPage.vue` | 解除后从列表移除;空态 |
| 8.3 | 举报弹窗(用户/动态共用) | `src/features/moderation/ReportDialog.vue` | 必选理由;提交后提示「已收到举报」;**举报后拉黑可选** |
| 8.4 | 在线状态(45 秒心跳 + 可见性规则) | `src/stores/presence.ts`(**轮询即心跳,不拆 `useHeartbeat.ts`;以计划二 Task 8.4 为准**) | 可见时 45s 一次;`document.hidden` 暂停;重新可见立即补一次;在线光接入各列表 |

### T9 测试补齐 / 端到端 / CI(5 个任务)

| # | 任务 | 测试要点 |
|---|---|---|
| 9.1 | 覆盖补齐 + `vitest --coverage` 门槛(阈值先定 70%,可在执行时与用户确认) | 401 通道、token 一致性、侧栏几何、各 store |
| 9.2 | Playwright 配置(`webServer` 起 `vite preview`;真实后端可切换) | 冒烟一条能跑通 |
| 9.3 | 主干场景脚本 | 登录 → 完善资料 → 滑卡 → 互喜配对 → 聊天发文本与图片 → 广场发布与评论 → 拉黑 |
| 9.4 | 边界场景脚本 | 深链直开与 F5;中文渲染自检;窄窗口仍是 PC 壳层;UA 移动端进引导页;被顶号全屏提示;**第二个标签页登录不清掉第一个标签页的登录态**(踢出原因分流) |
| 9.5 | `.github/workflows/web.yml` | `npm ci` + `type-check` + `lint` + `test:run` + `build` |

### T10 部署与文档(3 个任务)

| # | 任务 | 文件 |
|---|---|---|
| 10.1 | 部署手册补网页端章节 + nginx 配置样例 + IP 阶段上线核对单 | 服务器运维手册(本地保留,不入库)、README「部署」 |
| 10.2 | 新建踩坑分册并接导航 | `docs/pitfalls/web.md`、`docs/pitfalls/README.md` |
| 10.3 | 立纪律与更新导航 | `CLAUDE.md`(网页端目录、token 双份纪律、常用命令)、`README.md`(网页端一节) |

---

## Spec 覆盖对照(自检用)

| spec 章节 | 落到哪个任务 |
|---|---|
| §1 范围(11 模块 / 30 接口) | T4–T8 全覆盖 |
| §2 Flutter 否决的实测记录 | 记录性内容;经验沉淀进 T10.2 `docs/pitfalls/web.md` |
| §3 技术选型 / §4 工程结构 | T1.1 |
| §5.1 路由与守卫 | T3.1(封禁分支在 T4.6 补) |
| §5.2 网络层与鉴权 | T2.1 / T2.2 / T2.3 |
| §5.3 单设备登录 | T2.4(被顶号全屏)+ T9.4(多标签不互顶验收) |
| §5.4 IM 接入 | T6.1–T6.8 |
| §6.1 设备判定 | T3.2 |
| §6.2 可拖拽侧栏 | T3.3 / T3.4 |
| §6.3 自适应规则 | T3.4(内容区)/ T7.2(广场列数)/ T6.5(会话列表宽度) |
| §6.4 鼠标键盘升级 | T5.3(键盘滑卡)/ T6.7(灯箱 Esc)/ T6.8(右键菜单) |
| §6.5 移动端引导页 | T3.2 |
| §7 心跳 token 双份纪律 | T1.2(token)+ T1.3(字体)+ T10.3(纪律落条) |
| §8 功能对等清单 | T4–T8 |
| §9 与 App 的行为差异 | T2.4、T3.2、T5.3、T6.7、T6.8、T6.4 |
| §10 测试与门禁 | T9.1–T9.5 + 每组检查点 |
| §11 部署 | T10.1 |
| §12 任务量 | 本计划:**18 个已展开到可执行粒度**(T1 七个 / T2 六个 / T3 五个)+ **37 个已定范围**(T4 六 / T5 五 / T6 八 / T7 六 / T8 四 / T9 五 / T10 三),合计 **55 个任务** |
| §15 非目标 | Global Constraints 末条 |
| §16 验收标准 | 各组检查点 + T9 + T10 |

## 执行记录

> 执行本计划时在此追加实际偏差(项目既有惯例:计划里的执行记录用来沉淀与计划的差异)。

### T1–T3 执行记录(2026-10-05,分支 `feat/web-frontend`)

**环境与版本**

- 依赖装到的版本比计划假设新一个 major:vue 3.5.43 / **vue-router 5.3.1** / **pinia 4.0.3** / vite 8.3.2 / vitest 5.0.3 / **typescript 6.0.3** / eslint 10.12 / vue-tsc 3.3.12。
  已核实计划用到的 API 全部存在(`createRouter`/`createWebHistory`/`createMemoryHistory`/`setActivePinia`/`freshPinia` 依赖的 `setActivePinia`)。
- **TS 6 废弃 `baseUrl`**(直接报 TS5101 错误)→ tsconfig 去掉它,`paths` 用相对路径。
- **TS 6 要求副作用式 CSS import 有类型声明**(TS2882)→ 新增 `src/vite-env.d.ts`(`/// <reference types="vite/client" />` + `ImportMetaEnv`)。

**计划自身的疏漏(执行时修正)**

1. `tests/support/server.ts` 用 `import.meta.url` 定位文件在 vitest+jsdom 下会抛 `The URL must be of scheme file` → 统一改用 `process.cwd()`。
2. token 对照测试的 CSS 数值解析只认 `px`,而动效时长是 `ms` → 解析器同时认两者。
3. 色板断言原为「整体容差 1/255」,**实测会让「改一个色阶」蒙混过关**(把 `#ff2c55` 改成 `#ff2c56` 仍绿)→ 改为 RGB 逐通道精确 + alpha 才给 1/255 容差;并补条数断言(14/9/8/6)防解析失败导致空跑假绿。
4. **Task 3.1 的原注释「页面组件未创建不影响单测」是错的**:vue-router 在导航时会加载懒加载组件以收集组件内守卫,组件文件不存在则导航直接失败 → 因此执行顺序改为 3.2 → 页面骨架 → 3.1。
5. Plan B 的 `tests/support/pinia.ts`(`freshPinia()`)提前到 T2.4 建立:预置 store 状态与 `mount` 必须用同一个 pinia。
6. eslint 的 `vue/flat/recommended` 两条纯排版规则(每属性一行、短标签必须换行)与项目写法冲突且会挡住「零告警」→ 显式放宽并写明理由。

**真环境目检抓到的两个真 bug(单测抓不到)**

1. **登录后跳转失败**:`No match for {"name":"home"}` —— 我给 `/home` 漏起名;且把它起在父级上会触发 Vue Router 正式警告 **R0103**(名字必须给空路径子路由)。已改 `{ path: '', name: 'home', redirect: { name: 'discovery' } }`,并新增「代码里跳转用到的路由名都必须能解析」的防回归用例(组件测试里自建 router 无法覆盖这类问题)。
2. **iPhone UA 被误判为桌面端**:原判定先看 `navigator.platform`、UA 只看 Android;Playwright 只覆写 UA 时 platform 仍是 `Win32`,于是进了登录页而不是引导页。真机 iPhone 的 platform 是 `iPhone` 所以线上不受影响,但内嵌 WebView / platform 被冻结或伪造时会误判 → 判定加固为「platform 与 UA 都看」,并补 3 条用例(不破坏真 Mac 判为桌面端的语义)。

**Redis 环境问题(非代码)**

本机 `chatapp-redis` 容器的端口映射是 `6379→16379`,与 `docker-compose.dev.yml` 和 `chatapp/.env`(均为 6379)不一致,导致后端 `sms/verify` 500(连不上 Redis)。已按 compose 文件重建容器(数据卷 `chatapp_redis-data` 保留),`python manage.py runserver` 起来后登录链路正常。

**已知缺口(不在计划范围,未擅自扩)**

- 未匹配的路径没有 404 兜底,会渲染空白壳(nginx `try_files` 会把未知路径也交给 index.html)。
- 侧栏「我的」区的真实头像/昵称待 T4 的 profile store 就位后接入,目前是首字占位。

**T1–T3 交付状态**:26 个测试文件 / 125 个用例全绿;`vue-tsc` 0 错误;`eslint --max-warnings 0` 零告警;`vite build` 通过(157KB / gzip 60KB,路由级懒加载已生效)。


<!-- PLAN-ANCHOR:文件末尾 -->




