import { createPinia, setActivePinia, type Pinia } from 'pinia'

/**
 * 建一个 pinia 并设为 active,返回它本身 —— 测试里既用它预置 store 状态,
 * 又把它作为 `global.plugins: [pinia]` 传给 mount,保证组件与测试操作的是同一个 store。
 *
 * 反面教材:`mount(..., { global: { plugins: [createPinia()] } })` 会新建一个与预置状态
 * 无关的 pinia,组件读到的永远是空 store。
 */
export function freshPinia(): Pinia {
  const pinia = createPinia()
  setActivePinia(pinia)
  return pinia
}
