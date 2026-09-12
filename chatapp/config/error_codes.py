"""全局业务码目录:前 3 位与 HTTP 状态码一致,后 2 位为序号。"""

SESSION_CONFLICT = 40101          # 单设备登录冲突
SMS_CODE_EXPIRED = 40001          # 验证码过期/不存在
SMS_CODE_WRONG = 40002            # 验证码错误
SMS_SEND_TOO_FREQUENT = 42901     # 重发间隔未到
SMS_TOO_MANY_ATTEMPTS = 42902     # 错误次数过多被锁
SMS_SERVICE_UNAVAILABLE = 50301   # 短信任务入队失败
