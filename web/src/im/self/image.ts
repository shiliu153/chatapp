/**
 * 聊天图片的浏览器侧处理:canvas 压缩 + 上传到 Django。
 *
 * 为什么在客户端压:2C2G 服务器不替客户端转码;长边 1920 / JPEG 0.8
 * 通常比原图小一个数量级,而聊天页只展示缩略图。
 *
 * **失败重试的口径与语音一致**(参考语音那条:PR 406 的 `voice-status.ts` / `voice.ts`;410 号单
 * 把图片对齐过来):
 * - 上传的幂等度足够(最坏留下一条没人引用的图,由 30 天过期回收),所以
 *   **网络抖动 / 429 / 5xx 自己退避重试**,不该让用户手动点「重发」;
 * - `401 / 403 / 404` 这类「再问也一样」的错误**立刻冒泡**(令牌失效、被封禁、对端或资源
 *   不在了),4xx 里的校验类错误(400 像素超限、413 存储配额满)同理 —— 重复上传只会再错
 *   一次,早点把服务端的中文原因交给用户比多转两圈有用。
 *
 * 学习点(写在代码里,`docs/**` 是另一条栈):
 * 「点了没反应」几乎都是**把异常吞成了 `return`**。重试路径必须能说出「为什么不行」,
 * 所以本地文件失效时抛 `Error(CHAT_IMAGE_LOCAL_GONE_TEXT)` 而不是静默返回。
 */

import { isLocalError, parseApiError } from '@/api/error'
import { http } from '@/api/http'

export interface UploadedImage {
  id: number
  url: string
  thumb_url: string
  width: number
  height: number
  size: number
}

export const CHAT_IMAGE_MAX_SIDE = 1920
export const CHAT_IMAGE_QUALITY = 0.8

/**
 * 「重发」时本地待发文件已经不在了的提示(刷新页面 / 切走会话 / 浏览器回收内存)。
 *
 * 图片和语音一样**不能拿服务端那份地址重发**:消息里只有带签名的 `url`,24 小时后过期,
 * 重发它等于重发一个快过期的链接。没有本地 `File` 就只能请用户重新选图 —— 这句话是
 * **给用户看的**:store 抛出来、ChatPage 原样 toast、气泡上也写同一句。
 */
export const CHAT_IMAGE_LOCAL_GONE_TEXT = '图片已失效，请重新选择'

/** 一次上传最多试几次(含第一次)。3 次足够扛过抖动,再多只会让用户干等。 */
export const CHAT_IMAGE_UPLOAD_ATTEMPTS = 3
/** 首次退避(毫秒),之后翻倍;429 带 `Retry-After` 时以它为准。 */
export const CHAT_IMAGE_UPLOAD_BASE_DELAY_MS = 500
/** 退避上限:图片上传本来就是百毫秒级,退太久不如让用户重选。 */
export const CHAT_IMAGE_UPLOAD_MAX_DELAY_MS = 4000

/** 上传参数(单测注入点:不必真等,也不必真压缩)。 */
export interface ImageUploadOptions {
  /** 最多试几次,缺省 `CHAT_IMAGE_UPLOAD_ATTEMPTS` */
  attempts?: number
  /** 延时注入点;缺省 `setTimeout`(假定时器能够推进) */
  sleep?: (ms: number) => Promise<void>
}

/** 默认延时:与语音轮询同口径用 `setTimeout`,否则假定时器里永远推进不下去。 */
function defaultSleep(ms: number): Promise<void> {
  return new Promise<void>((resolve) => setTimeout(resolve, ms))
}

/**
 * 这次上传失败值不值得退避重试;值得就返回要等多久(毫秒),不值得返回 `null`。
 *
 * 判据三条,和 `voice-status.ts::pollVoiceStatus` 是同一套:
 * 1. 请求没到服务端(断网 / 超时)→ 退避再试;
 * 2. `429` 限流 → 按服务端 `Retry-After` 等,没给就用退避值;
 * 3. `5xx` → 退避再试(服务端重启中,再问一次大概率就好了)。
 * 其余(401 / 403 / 404 / 400 / 413 …)一律不重试,原样上抛。
 *
 * Args:
 *   error: 上一次上传抛出的异常(axios 错误、`ApiError` 或本地错误)。
 *   backoffMs: 本次退避建议值(毫秒),由调用方按尝试次数翻倍。
 *
 * Returns:
 *   要等的毫秒数;`null` 表示「再试也一样,立刻冒泡」。
 */
export function imageUploadRetryDelay(error: unknown, backoffMs: number): number | null {
  const apiError = parseApiError(error)
  if (apiError.status === undefined) {
    // 没有 HTTP 状态码:请求没到服务端(断网/超时)值得退避再试;
    // 本地错误(压缩失败这类)再试一百遍也一样,直接抛
    return isLocalError(error) ? null : backoffMs
  }
  if (apiError.status === 429) {
    return apiError.retryAfter ? apiError.retryAfter * 1000 : backoffMs
  }
  if (apiError.status >= 500) return backoffMs
  // 401 / 403 / 404 是「再问也一样」;其余 4xx 是请求本身不对(像素超限 / 配额满 / 格式不支持)
  return null
}

/** 压到长边 1920 的 JPEG;环境不支持 canvas 时原样返回。 */
export async function compressImage(
  file: File,
  maxSide = CHAT_IMAGE_MAX_SIDE,
  quality = CHAT_IMAGE_QUALITY,
): Promise<Blob> {
  if (typeof document === 'undefined' || typeof createImageBitmap === 'undefined') {
    return file
  }
  const bitmap = await createImageBitmap(file)
  const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height))
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1, Math.round(bitmap.width * scale))
  canvas.height = Math.max(1, Math.round(bitmap.height * scale))
  const context = canvas.getContext('2d')
  if (!context) return file
  context.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
  const blob = await new Promise<Blob | null>((resolve) =>
    canvas.toBlob(resolve, 'image/jpeg', quality))
  return blob ?? file
}

/** 把压缩后的图 POST 上去,返回后端给的 URL 与尺寸(单次尝试,不含重试)。 */
async function postChatImage(blob: Blob): Promise<UploadedImage> {
  const form = new FormData()
  form.append('file', blob, 'chat.jpg')
  const response = await http.post('/im/images', form)
  return response.data as UploadedImage
}

/**
 * 压缩后上传,返回后端给的 URL 与尺寸;**抖动 / 限流 / 5xx 自己退避重试**。
 *
 * 「先压再重试」是刻意的:该重试的是**网络那一段**,本地坏图重压一遍还是坏,
 * 别把 CPU 花在重试上(压缩失败直接抛)。
 *
 * Args:
 *   file: 用户刚选的图片文件。
 *   options: 重试参数,见 `ImageUploadOptions`。
 *
 * Returns:
 *   后端返回的 `{id, url, thumb_url, width, height, size}`。
 *
 * Raises:
 *   ApiError: 401 / 403 / 404 / 其余 4xx(再问也不一样),或重试次数用尽仍失败。
 *   Error: 本地压缩失败(画布不可用之外的异常),不重试。
 */
export async function uploadChatImage(
  file: File,
  options: ImageUploadOptions = {},
): Promise<UploadedImage> {
  const attempts = Math.max(1, options.attempts ?? CHAT_IMAGE_UPLOAD_ATTEMPTS)
  const sleep = options.sleep ?? defaultSleep
  const blob = await compressImage(file)
  let backoffMs = CHAT_IMAGE_UPLOAD_BASE_DELAY_MS
  for (let attempt = 1; ; attempt += 1) {
    try {
      return await postChatImage(blob)
    } catch (error) {
      const delay = attempt < attempts ? imageUploadRetryDelay(error, backoffMs) : null
      if (delay === null) throw error
      await sleep(delay)
      backoffMs = Math.min(CHAT_IMAGE_UPLOAD_MAX_DELAY_MS, backoffMs * 2)
    }
  }
}
