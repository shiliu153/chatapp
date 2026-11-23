import { readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

const pkg = JSON.parse(
  readFileSync(fileURLToPath(new URL('./package.json', import.meta.url)), 'utf-8'),
) as { version: string }

export default defineConfig({
  // tailwindcss():把 `src/styles/tailwind.css` 里的 `@theme inline` 编译成语义工具类。
  // 它只处理 @import/@theme/@utility 这些指令,不做别的 —— preflight 也没引(见该文件头)。
  plugins: [vue(), tailwindcss()],
  define: { __APP_VERSION__: JSON.stringify(pkg.version) },
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
  // 注意:vite preview 不会继承 server.proxy,端到端测试要用自己的那份(Task 9.2 会补)
  preview: {
    port: 4173,
    proxy: {
      '/api/v1': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/media': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
