/// <reference types="vite/client" />

/** 本项目用到的环境变量(见 .env.development / .env.production / .env.test)。 */
interface ImportMetaEnv {
  readonly VITE_API_BASE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

/** 构建期注入的应用版本(来源:web/package.json)。 */
declare const __APP_VERSION__: string
