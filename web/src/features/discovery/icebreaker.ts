/**
 * 配对那一刻的破冰文案(纯客户端模板,计划 §2.2)。
 *
 * 收敛口径:共同点**只在配对那一刻**展示 —— 聊天页不提示,也不为了提示去拉
 * `GET /users/{id}`(那会把这次查看记成一次访客访问,语义污染)。
 *
 * 规则(与 App 的 `icebreaker.dart` 逐字一致,改文案要两端同改):
 *   1. 有共同标签 → 「你们都喜欢 X、Y,不如从这儿聊起?」(最多列 2 个);
 *   2. 没有共同标签 → 「你们都在 {城市}」,**仅当双方城市都非空且相同**;
 *   3. 两条都不满足 → 返回 null,调用方整行不展示(不提性别,避免刻板印象)。
 */

/** 最多列出几个共同标签(超出部分不展示,避免一行挤爆)。 */
export const maxIcebreakerTags = 2

export interface IcebreakerInput {
  /** 共同标签的名字列表(顺序即展示顺序,来自后端 `shared_tags`) */
  sharedTagNames: string[]
  /** 我的城市;空字符串表示未填 */
  myCity?: string
  /** 对方的城市;空字符串表示未填 */
  peerCity?: string
}

/**
 * 生成配对破冰文案。
 *
 * @param input 共同标签名、我的城市、对方城市
 * @returns 可直接渲染的一行文案;没有可说的内容时返回 `null`
 */
export function matchIcebreaker(input: IcebreakerInput): string | null {
  const names = input.sharedTagNames
    .map((name) => name.trim())
    .filter((name) => name.length > 0)
    .slice(0, maxIcebreakerTags)
  if (names.length > 0) return `你们都喜欢 ${names.join('、')},不如从这儿聊起?`

  const city = (input.peerCity ?? '').trim()
  // 只提「双方都在这座城市」—— 单方面知道对方城市时不能替用户断言,更不展示性别。
  if (city.length === 0 || city !== (input.myCity ?? '').trim()) return null
  return `你们都在 ${city}`
}
