/** 与后端接口一一对应的出入参类型;字段以 docs/api/ 为准,不臆造。 */

export interface LoginResult {
  access: string
  refresh: string
  isNewUser: boolean
  userId: number
}
