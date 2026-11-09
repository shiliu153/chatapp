"""全局业务码目录:前 3 位与 HTTP 状态码一致,后 2 位为序号。

新增码前先在本文件查重:同一段「HTTP 前缀 + 序号」只允许出现一次,
否则客户端按 code 分支时会把两种语义混在一起(如把「撤销失败」显示成「验证码已过期」)。
"""

SESSION_CONFLICT = 40101          # 单设备登录冲突
SMS_CODE_EXPIRED = 40001          # 验证码过期/不存在
SMS_CODE_WRONG = 40002            # 验证码错误
# 批次 O(滑卡增强):撤销滑卡失败。不复用 40001(验证码过期)/ 40002(验证码错误)。
SWIPE_UNDO_UNAVAILABLE = 40003    # 滑卡撤销:没有可撤销的那一次(超时 / 已配对 / 无记录)
# 端类型只能是 app / web(`DELETE /api/v1/devices/{client_type}`)。**一码一义**:
# 不复用 40001(验证码过期)、40002(验证码错误),也不占批次 O 的 40003(无可撤销滑卡)。
INVALID_CLIENT_TYPE = 40004
SMS_SEND_TOO_FREQUENT = 42901     # 重发间隔未到
SMS_TOO_MANY_ATTEMPTS = 42902     # 错误次数过多被锁
SWIPE_LIKE_QUOTA_EXCEEDED = 42904 # 每日喜欢额度已用完
SMS_SERVICE_UNAVAILABLE = 50301   # 短信任务入队失败
PHONE_NOT_ALLOWED = 40301         # 封闭测试:号码不在受邀白名单内
CHAT_VOICE_UNAVAILABLE = 50302    # 服务器缺 ffmpeg/ffprobe,语音上传暂不可用
STORAGE_QUOTA_EXCEEDED = 41301    # 单账号媒体存储配额已满
INVALID_PERIOD = 40005            # 使用报告的 period 取值非法(只允许 week/month/year)
