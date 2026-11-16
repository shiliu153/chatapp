/**
 * 聊天图片的浏览器侧处理:canvas 压缩 + 上传到 Django。
 *
 * 为什么在客户端压:2C2G 服务器不替客户端转码;长边 1920 / JPEG 0.8
 * 通常比原图小一个数量级,而聊天页只展示缩略图。
 *
 * **失败重试的口径与语音一致**(参考语音那条:PR 406 的 `voice-status.ts` / `voice.ts`;410 号单
 * 把图片对齐过来):
 * - **网络抖动 / 429 / 5xx 自己退避重试**,不该让用户手动点「重发」;
 * - **`409` + `40901` 也是可重试**(同一个 `Idempotency-Key` 的上一次上传还在处理中):
 *   退避 1–2 秒后用**同一个 key** 再打一次,拿回的就是首次的结果,不能当终态失败报给用户;
 * - `401 / 403 / 404` 这类「再问也一样」的错误**立刻冒泡**(令牌失效、被封禁、对端或资源
 *   不在了),4xx 里的校验类错误(400 像素超限、413 存储配额满)同理 —— 重复上传只会再错
 *   一次,早点把服务端的中文原因交给用户比多转两圈有用。
 *
 * **一次上传一个幂等键**(`docs/api/conventions.md` §幂等键):`uploadChatImage` 进来时生成
 * 一个 key,这次上传的所有自动重试都复用它;换一张图再走一次才会换 key。请求体每次重试都
 * 重新构造(`FormData` 已被发过就标脏),口径与生成都放在 `src/api/idempotency.ts`。
 *
 * 学习点(写在代码里,`docs/**` 是另一条栈):
 * 「点了没反应」几乎都是**把异常吞成了 `return`**。重试路径必须能说出「为什么不行」,
 * 所以本地文件失效时抛 `Error(CHAT_IMAGE_LOCAL_GONE_TEXT)` 而不是静默返回。
 */

import {
  newIdempotencyKey,
  type UploadRetryOptions,
  withUploadRetries,
} from '@/api/idempotency'
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

/**
 * 上传参数(单测注入点:不必真等,也不必真压缩)。
 *
 * 字段与另外两个上传入口同一份(`UploadRetryOptions`);图片的缺省值见上面三个
 * `CHAT_IMAGE_UPLOAD_*` 常量。
 */
export type ImageUploadOptions = UploadRetryOptions

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

/**
 * 构造一次 multipart 请求体。
 *
 * **每次尝试都要新建**:`FormData` 一旦发出去就被浏览器标脏,重试复用同一个对象会丢文件。
 * 单测据此断言「第二次请求的 body 里文件还在」。
 */
function chatImageForm(blob: Blob): FormData {
  const form = new FormData()
  form.append('file', blob, 'chat.jpg')
  return form
}

/** 把压缩后的图 POST 上去,返回后端给的 URL 与尺寸(单次尝试,不含重试)。 */
async function postChatImage(blob: Blob, idempotencyKey: string): Promise<UploadedImage> {
  const response = await http.post('/im/images', chatImageForm(blob), {
    headers: { 'Idempotency-Key': idempotencyKey },
    // 401 刷新后重放同一次上传时也重建请求体(见 `src/api/http.ts` 的 `rebuildBody`)
    rebuildBody: () => chatImageForm(blob),
  })
  return response.data as UploadedImage
}

/**
 * 压缩后上传,返回后端给的 URL 与尺寸;**抖动 / 限流 / `40901` / 5xx 自己退避重试**。
 *
 * 「先压再重试」是刻意的:该重试的是**网络那一段**,本地坏图重压一遍还是坏,
 * 别把 CPU 花在重试上(压缩失败直接抛)。
 *
 * **幂等键在压缩之后、第一次请求之前生成**:本次调用的所有重试(含 401 刷新后的重放)
 * 都用同一个 key,服务端因此不会为重试多落一份文件;换一张图才会换 key。
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
  const blob = await compressImage(file)
  const idempotencyKey = newIdempotencyKey()
  return withUploadRetries(() => postChatImage(blob, idempotencyKey), {
    attempts: options.attempts ?? CHAT_IMAGE_UPLOAD_ATTEMPTS,
    sleep: options.sleep,
    baseDelayMs: options.baseDelayMs ?? CHAT_IMAGE_UPLOAD_BASE_DELAY_MS,
    maxDelayMs: options.maxDelayMs ?? CHAT_IMAGE_UPLOAD_MAX_DELAY_MS,
  })
}
