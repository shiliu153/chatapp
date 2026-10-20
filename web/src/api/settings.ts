import { http } from './http'

/** 反馈类型,与后端 FeedbackType 一一对应(feedback.md)。 */
export type FeedbackType = 'feature' | 'bug' | 'account' | 'other'

export interface FeedbackPayload {
  type: FeedbackType
  content: string
  contact?: string
}

/** 提交意见反馈;成功时后端返回 201。 */
export async function submitFeedback(payload: FeedbackPayload): Promise<void> {
  await http.post('/feedback', payload)
}
