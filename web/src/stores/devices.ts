import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as devicesApi from '@/api/devices'
import { sessionEvents } from '@/api/session-events'
import type { LoginDevice } from '@/api/types'

/** 从没在该端刷新过令牌时的文案(auth.md §1.6:`last_active_at` 为 null)。 */
export const LAST_ACTIVE_NEVER = '尚未在此端刷新过'

/** 一行「登录设备」的展示模型:页面只负责摆版,时间文案由 store 统一映射。 */
export interface DeviceRow {
  /** `app` / `web`;下线接口的路径参数 */
  clientType: string
  /** 端展示名(服务端给的 `client_label`) */
  label: string
  /** 是否本次请求所在的端 → 标「本机」,且不给下线按钮 */
  current: boolean
  /** 「首次登录 2026-11-09 10:20」 */
  firstLoginText: string
  /** 「最近活跃 2026-11-09 10:55」,或「尚未在此端刷新过」 */
  lastActiveText: string
  /** 当前端不给下线按钮(踢自己当前端等于注销,入口不放在这里) */
  canLogout: boolean
}

const pad = (value: number): string => String(value).padStart(2, '0')

/**
 * ISO 8601 → 「YYYY-MM-DD HH:mm」(**本地时区**,与聊天时间条同口径)。
 * 解析不出来时原样返回,避免页面上出现 `Invalid Date`。
 */
function formatDateTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    ` ${pad(date.getHours())}:${pad(date.getMinutes())}`
  )
}

/** 接口报文 → 展示模型。 */
function toRow(item: LoginDevice): DeviceRow {
  return {
    clientType: item.client_type,
    label: item.client_label,
    current: item.current,
    firstLoginText: `首次登录 ${formatDateTime(item.created_at)}`,
    lastActiveText:
      item.last_active_at === null
        ? LAST_ACTIVE_NEVER
        : `最近活跃 ${formatDateTime(item.last_active_at)}`,
    canLogout: !item.current,
  }
}

export const useDevicesStore = defineStore('devices', () => {
  const devices = ref<DeviceRow[]>([])
  const loading = ref(false)

  /** 本次请求所在的端;列表里不存在 current 行时(理论上不会)为 null。 */
  const current = computed<DeviceRow | null>(
    () => devices.value.find((item) => item.current) ?? null,
  )

  /**
   * 拉取登录设备列表。
   * 失败**不吞**:错误向上抛,由页面用 `parseApiError` 统一展示。
   */
  async function load(): Promise<void> {
    loading.value = true
    try {
      devices.value = (await devicesApi.fetchDevices()).map(toRow)
    } finally {
      loading.value = false
    }
  }

  /**
   * 下线某一端(幂等)。成功后把该行从列表移除并提示由页面负责。
   *
   * 防御分支:若下线的正是当前端(服务端允许,语义等同注销本端),
   * 本端访问令牌已失效 —— 走既有的 `sessionEvents`「清凭证回登录页」通道,
   * 不在这里直接碰 tokenStore / 路由。
   */
  async function logout(clientType: string): Promise<void> {
    const target = devices.value.find((item) => item.clientType === clientType)
    await devicesApi.logoutDevice(clientType)
    devices.value = devices.value.filter((item) => item.clientType !== clientType)
    if (target?.current) sessionEvents.emitSessionExpired()
  }

  return { devices, loading, current, load, logout }
})
