# 个人使用报告

> 本分册记录「我的使用报告」接口:按自然周期汇总当前用户的七项数字。
> 它是**只读聚合**,不产生任何写入;所有数字都来自 Django 自己的库。

---

## 1. 使用报告

### 1.1 我的使用报告

> `GET` `/api/v1/stats/me` · 需要鉴权 · 无额外限流

**接口描述**

返回当前用户在某个自然周期内的七项数字,用于「我的数据」页面的周/月/年报告。

- **周期口径**:`week` = 自然周(周一起,到周日止)、`month` = 自然月、`year` = 自然年,
  全部按 `Asia/Shanghai` 计算;响应的 `start` / `end` 是**含首含尾**的日期字符串;
- **只统计我自己**:所有数字都以当前令牌对应的账号为主体,不返回任何他人数据;
- **口径是「区间内发生的事件」**,不是「当前存量」:
  - `matches` 按配对创建时间计,**事后被解除的配对也算过**;
  - `visits` 按访客的最近访问时间计,访客表是「一人一行」(重复访问只刷新时间),
    因此这里数的是「区间内来看过我的人」,不是点击次数;
  - `new_followers` 按关注关系创建时间计(关注是有向关系,只算「关注我」的一方);
- **不含消息条数**:聊天消息存在 imserver 的库里(`chatapp_im`),Django 侧读不到,
  本接口刻意不做跨库聚合;
- 一次请求固定 7 个计数,单次请求的 SQL 条数由 `config/test_query_budget.py` 的
  `stats` 条目守住上限 8 条;
- 重封禁账号返回 `403`(与其余业务接口一致);轻封禁不影响本接口。

**请求参数**(Query)

| 参数名称 | 必填 | 类型 | 描述 |
|---|---|---|---|
| period | 否 | String | 统计周期:`week` 自然周(周一起)/ `month` 自然月 / `year` 自然年;缺省 `week` |

**响应参数**

| 参数名称 | 类型 | 描述 |
|---|---|---|
| period | String | 实际生效的周期(缺省时回显 `week`) |
| start | String | 区间起始日期(含),`YYYY-MM-DD` |
| end | String | 区间结束日期(含),`YYYY-MM-DD` |
| matches | Integer | 区间内新产生的配对(我参与的,含事后已解除的) |
| likes_given | Integer | 区间内我发出的「喜欢」数 |
| likes_received | Integer | 区间内别人给我的「喜欢」数 |
| visits | Integer | 区间内看过我资料的人数(一人一行,按最近访问时间) |
| posts | Integer | 区间内我发布的动态数 |
| post_likes | Integer | 区间内我的动态收到的赞数 |
| new_followers | Integer | 区间内新增的关注我的人数 |

**请求示例**

```bash
curl "http://<域名>/api/v1/stats/me?period=week" \
  -H "Authorization: Bearer <access>"
```

**响应示例**(成功)

```json
{
  "period": "week",
  "start": "2026-11-09",
  "end": "2026-11-15",
  "matches": 2,
  "likes_given": 14,
  "likes_received": 9,
  "visits": 6,
  "posts": 3,
  "post_likes": 11,
  "new_followers": 1
}
```

**响应示例**(典型失败)

```json
{
  "code": 40001,
  "message": "统计周期只能是 week / month / year",
  "request_id": "9f8c1b2e4d5a"
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|---|---|---|---|
| 40001 | 400 | `period` 不在 `week` / `month` / `year` 之内 | 客户端只应传这三个取值;不传即按 `week` |
| 401 | 401 | 未认证或令牌失效(被顶号时带 `40101`) | 重新登录或刷新令牌 |
| 403 | 403 | 账号已被封禁(重封禁) | 提示用户账号受限 |
