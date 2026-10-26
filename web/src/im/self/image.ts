/**
 * 聊天图片的浏览器侧处理:canvas 压缩 + 上传到 Django。
 *
 * 为什么在客户端压:2C2G 服务器不替客户端转码;长边 1920 / JPEG 0.8
 * 通常比原图小一个数量级,而聊天页只展示缩略图。
 */

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

/** 压缩后上传,返回后端给的 URL 与尺寸。 */
export async function uploadChatImage(file: File): Promise<UploadedImage> {
  const blob = await compressImage(file)
  const form = new FormData()
  form.append('file', blob, 'chat.jpg')
  const response = await http.post('/im/images', form)
  return response.data as UploadedImage
}
