# 聊天图片签名 URL 与容量清理设计

日期:2026-10-26 · 前置:`docs/superpowers/specs/2026-10-26-im-image-messages-design.md`
状态:设计已确认(用户 2026-10-26 选择「签名 URL + 保留 30 天清理」),待写实施计划

## 1. 背景与问题

图片二期把聊天图片落到了 Django 的 `MEDIA_ROOT/chat/<年>/<月>/`,由宿主机 nginx
`location ^~ /media/ { alias ...; expires 7d; }` **直出**。当前留下两个口子:

1. **URL 公开且永久有效**:文件名随机不可枚举,但链接一旦被转发(截图工具、复制到浏览器、
   第三方抓取),任何人拿到都能**无限期**看这张私聊图,且不受拉黑/解除配对影响;
2. **只增不减**:上传即落盘,运营删除与注销会删文件,但「上传了却没发出去」的孤儿文件、
   以及正常聊天图片会一直堆着。2C2G 轻量服务器磁盘有限,没有清理机制和用量视图。

本设计交付:**限时签名 URL** + **30 天保留期清理** + **运维用量报表**。

## 2. 目标与非目标

**目标**

- 聊天图片(原图与缩略图)必须带签名才能访问,签名有有效期;
- 历史消息里的图片在有效期内始终可看(不能因为签名写死在库里而过期);
- 超过保留期(默认 30 天)的图片文件被清理,聊天记录显示占位而不是报错;
- 运维能一键看到磁盘占用,并能安全地手动清理孤儿文件。

**非目标(YAGNI)**

- 机器审核(独立的上线阻断项,见图片二期设计 D2);
- CDN / 对象存储 / 多区域;
- 用户侧「图片已过期」的显式文案(复用现有加载失败占位即可);
- 按会话或按用户删除图片;
- 对**用户头像、广场图片**做同样的签名(它们同属 `/media/`,本轮不动,见 §10)。

## 3. 关键决策

| # | 决策 | 取舍理由 |
|---|---|---|
| D1 | 签名**校验**走 nginx `auth_request` → Django 内部验签接口 | **实测**:生产 nginx 编译参数有 `--with-http_auth_request_module`、**没有** `--with-http_secure_link_module`。重编译生产 nginx 风险高;`auth_request` 只多一次内部 HTTP(Django gthread 2 进程 × 4 线程,单次 <5ms) |
| D2 | 签名**生成**分两处:Django 上传响应 + imserver 读时 | URL 由 imserver 落库并对外推送/返回历史;读时现签才能保证历史不过期。两端共用同一算法与密钥,靠同一组测试向量锁死 |
| D3 | 落库存**规范 URL**(去掉 query),读时加签名 | 写时存签名会让历史在 24h 后永久 403;规范形还能让「同一张图」在库里只有一种写法 |
| D4 | 过期时间**按小时对齐** + TTL 24h | 若每次响应都算 `now+24h`,URL 每秒都变,浏览器缓存全废、历史每刷一次重下所有图。对齐到整点后同一小时内 URL 稳定,实际有效期 24–25h |
| D5 | 保留期 **30 天**(用户选定),行保留、状态 `expired` | 2C2G 小盘优先保可用;删文件不删行,运营仍可追溯「谁在什么时候发过图」 |
| D6 | 清理命令**默认 dry-run**,`--apply` 才删 | 删文件不可逆;默认安全,定时任务显式带 `--apply` |
| D7 | 不引入 Celery beat,用宝塔计划任务 | 项目当前没有 beat 进程;为一条日更任务多养一个常驻进程不划算 |
| D8 | `IM_MEDIA_SIGN_SECRET` 为空 = 不签名(仅本地开发) | 本地 runserver 直接出 `/media/`,没有 nginx 验签;生产必须配,见 §9 核对单 |

## 4. 签名协议(两端逐字节一致)

### 4.1 URL 形态

```
https://<host>/media/chat/2026/10/12-3f2a....jpg?e=1761782400&s=9f2c...e1
```

- `e`:过期时间,Unix 秒(十进制);
- `s`:签名,小写 hex(HMAC-SHA256,64 字符)。

### 4.2 签名串与计算

```
signing_string = path + "\n" + str(exp)      # path 含前导 "/",如 /media/chat/2026/10/12-x.jpg
sig            = hmac_sha256(secret, signing_string).hexdigest()
exp            = (now - now % 3600) + ttl     # 按小时对齐;ttl 默认 86400
```

- `path` 是**规范化路径**:去掉 scheme/host,去掉 query;
- 密钥 `IM_MEDIA_SIGN_SECRET` 建议 ≥32 字节随机串,两端必须完全一致;
- 常量时间比较(两边都用各自语言的 `compare_digest` / `CRYPTO_memcmp`)。

**为什么把 exp 放进签名串**:防止改 `e` 延长有效期;签名与过期时间绑定。

### 4.3 共享测试向量(两端测试必须断言同一结果)

实现时用下面这组固定输入产出期望值,Python 与 C++ 两侧测试都断言它,防止两端
算法漂移(例如 hex 大小写、换行符、是否含前导 `/`):

```
secret = "test-media-secret"
path   = "/media/chat/2026/10/12-abc.jpg"
exp    = 1761782400
sig    = 2b46b854b31a88877e318e3d12cb743fe76fccb2977e2d7ced879d7b3547d419
```

## 5. 数据流

```
① 上传
   App/Web ──POST /api/v1/im/images──▶ Django
                                        ├ 落盘 media/chat/...
                                        ├ 建 ChatImage 行
                                        └ 返回 url/thumb_url(**已签名**)

② 发消息
   客户端把 ① 的 url 塞进 WS send{kind:image,image:{url,thumb_url,...}}
   imserver: 校验前缀 → **去掉 query 存规范 URL** → 落库 → ack

③ 推送 / 历史 / 会话列表
   imserver: 读 body → 对 image.url / image.thumb_url **现签** → 下发

④ 看图
   浏览器/App ──GET /media/chat/...?e=&s=──▶ nginx
                                             └ auth_request(内部)
                                                 └ GET /api/v1/im/images/auth
                                                     X-Original-URI: /media/chat/...?e=&s=
                                                     204 → 放行;403 → 拒绝
```

### 5.1 为什么 imserver 要参与签名

图片 URL 存在 `im_message.body` 里,由 imserver 推送和返回历史。若只让 Django 签,
要么把签名写死在库里(D3 已否),要么让客户端拿消息后再回调 Django 换 URL(多一跳、
两端都要改协议)。imserver 持有同一份密钥,读时现签是最小改动。

### 5.2 为什么校验放在 Django

imserver 可以被停掉(回退腾讯、故障止血),但聊天图片属于「已发生的历史」,
不应随 IM 后端一起不可用。Django 是唯一常驻且一定在的服务,所以验签归它。

## 6. Django 侧设计

### 6.1 新模块 `chatapp/im/media_sign.py`

对外三个函数(纯函数,无 IO,便于测试):

```python
def sign_query(path: str, *, now: int | None = None) -> str:
    """返回 "e=<exp>&s=<sig>";secret 为空时返回空串(不签名)。"""

def sign_url(url: str, *, now: int | None = None) -> str:
    """把绝对或相对 URL 规范化后加上签名 query;已有 query 会被替换。"""

def verify(path: str, expires: str, signature: str, *, now: int | None = None) -> bool:
    """校验签名与有效期;secret 为空时恒 True(本地开发)。"""
```

要点:

- `path` 必须以 `/` 开头,且必须以 `/media/chat/` 开头(验签接口只放行聊天图);
- `expires` 必须能转 int,且 `now < exp`,否则 False;
- 签名比较用 `hmac.compare_digest`;
- secret 为空时 `sign_url` 原样返回、`verify` 恒 True —— 本地开发没有 nginx,
  不能让 `runserver` 下的图片全部 403。生产由核对单保证配置(§9)。

### 6.2 配置(`config/settings.py`)

| 键 | 默认 | 说明 |
|---|---|---|
| `IM_MEDIA_SIGN_SECRET` | `""` | 与 imserver 同名变量一致;生产必填 |
| `IM_MEDIA_SIGN_TTL` | `86400` | 签名有效期(秒),两端一致 |
| `CHAT_IMAGE_RETENTION_DAYS` | `30` | 保留期;`0` 表示不清理(只清孤儿/残留) |

`.env.example` 同步补三项(带注释)。

### 6.3 模型(`im/models.py`)

```python
class ChatImageStatus(models.TextChoices):
    VISIBLE = "visible", "正常"
    DELETED = "deleted", "已删除"
    EXPIRED = "expired", "已过期清理"     # 新增

class ChatImage(models.Model):
    ...
    expired_at = models.DateTimeField(null=True, blank=True)   # 新增

    @property
    def signed_file_url(self) -> str:   # MEDIA_BASE_URL + 签名
    @property
    def signed_thumb_url(self) -> str:
```

迁移:一个 `AddField(expired_at)` + `AlterField(status)`(choices 变更)。

### 6.4 接口

**改**:`POST /api/v1/im/images` 响应里的 `url` / `thumb_url` 改为签名 URL,
其余字段不变。客户端不需要改代码。

**新增**:`GET /api/v1/im/images/auth`(nginx 子请求专用,无 JWT)

| 项 | 约定 |
|---|---|
| 鉴权 | 无(nginx 内部子请求不带 Authorization);`AllowAny` + 空认证类 |
| 入参 | 请求头 `X-Original-URI`(nginx `proxy_set_header` 传入),形如 `/media/chat/...?e=&s=` |
| 通过 | `204 No Content` |
| 拒绝 | `403` + `{"code":403,"message":"图片链接已失效"}` |
| 限流 | 不限流(每次都是一次 HMAC 计算;加限流反而会让 nginx 把正常看图打成 503) |

`X-Original-URI` 缺失或路径不在 `/media/chat/` 下 → 403。**不接受 query 里的
`path` 参数**:避免该接口被当成「任意路径验签器」使用。

### 6.5 运营台

`ops/views.py::chat_images` 与模板里的 `<img src>` 改用 `image.signed_thumb_url` /
`image.signed_file_url`,否则运营抽审页的图会 403。

### 6.6 管理命令

**`im_media_cleanup`**(默认 dry-run)

| 参数 | 默认 | 作用 |
|---|---|---|
| `--apply` | 关 | 不带就只打印将要删除的内容 |
| `--retention-days N` | `settings.CHAT_IMAGE_RETENTION_DAYS` | 保留期;`0` 跳过保留期清理 |
| `--orphan-hours N` | `24` | 磁盘上无对应行、且 mtime 早于 N 小时的文件;`0` 跳过 |
| `--batch-size N` | `200` | 每次处理的数据库行数 |

三类动作:

1. **保留期**:`status=visible AND created_at < now - N 天` → 删 `file`/`thumb` 文件,
   行改 `status=expired, expired_at=now`;
2. **孤儿文件**:遍历 `MEDIA_ROOT/chat/**`,文件名不在 `ChatImage.file/thumb` 集合中,
   且 mtime 早于 N 小时 → 删文件(不动数据库);
3. **删除残留**:`status=deleted` 但文件仍存在 → 补删(上次 `default_storage.delete`
   失败的情况)。

输出:每类一行汇总 + 总释放字节;异常逐条 warning,不中断整批。

**`im_media_stats`**

输出:各状态行数与字节数、`media/chat` 磁盘占用、所在分区剩余空间、Top 5 发送者
(按字节)、磁盘文件数与行数对比(差值即孤儿数量)。只读,无参数。

### 6.7 调度

宝塔计划任务每天 04:00:

```bash
cd /www/wwwroot/chatapp/chatapp && /www/wwwroot/chatapp-venv/bin/python manage.py im_media_cleanup --apply
```

## 7. imserver 侧设计

### 7.1 配置(`src/config.h`)

| 键 | 默认 | 说明 |
|---|---|---|
| `IM_MEDIA_SIGN_SECRET` | `""` | 与 Django 同名变量一致;为空 = 不签名(打一条 warning) |
| `IM_MEDIA_SIGN_TTL` | `86400` | 秒,与 Django 一致 |

`media_path_prefix`:从 `IM_MEDIA_PREFIX` 解析出路径部分(如 `/media/chat/`),
用于「从绝对 URL 里取 path」和「写时校验 URL 属于本服务」。

### 7.2 新模块 `src/util/media_sign.{h,cpp}`

```cpp
class MediaSigner {
 public:
  MediaSigner(std::string secret, int ttl, std::string path_prefix);
  bool enabled() const;
  // 给 image 对象里的 url/thumb_url 加 ?e=&s=(已是签名形态的先去掉旧 query)
  void sign_image(nlohmann::json& image) const;
  // 规范化:去掉 query,并校验属于 media_path_prefix;失败返回 nullopt
  static std::optional<std::string> canonicalize(const std::string& url,
                                                 const std::string& path_prefix);
 private:
  std::string secret_, path_prefix_;
  int ttl_;
};
```

- 复用现有 `hmac_sha256_hex`(`util/hmac.h`)—— 它已经是小写 hex,与 Python
  `hmac.hexdigest()` 一致;
- 时间:取 `system_clock` 秒,按 3600 对齐;单测允许注入 `now`(重载带 `now` 参数)。

### 7.3 三处签名 + 一处规范化

| 位置 | 改动 |
|---|---|
| `src/net/frames.h::build_message_frame` | 增加 `const MediaSigner&` 参数,`kind=3` 时 `sign_image(data["image"])` |
| `src/net/http_api.cpp::message_json` | 增加 signer 参数,历史与会话 `last_message` 都走它 |
| `src/net/http_api.cpp` `/internal/send` | 复用 `build_message_frame`(自动带上) |
| `src/service/message_service.cpp::send`(kind=3) | 落库前 `canonicalize` 两个 URL,失败 42201 |

`MessageService` 持有 `MediaSigner`(`const MediaSigner& signer()`),`WsServer` /
`HttpApi` 通过 `messages_` 取用,避免新增构造参数穿透。

### 7.4 兼容

- 未配置 secret 时 `sign_image` 空操作 → 行为与现在完全一致(测试环境友好);
- 老库里已带 query 的图片 URL:读时先剥 query 再签,不会双重签名;
- 老客户端:协议不变,只是 URL 多了 query。

## 8. 清理后的产品表现

文件被清掉后,消息体里的 URL 仍然存在 → 请求得到 404 → 客户端加载失败占位:

- App:`MessageBubble` 的 `errorBuilder`(已有);
- Web:`MessageImage` 的 `@error`(已有)。

不新增「图片已过期」文案,避免为一条边缘状态改三端 UI(YAGNI)。

## 9. 部署与核对单

1. **密钥**:Django `.env` 与 imserver 容器环境各加 `IM_MEDIA_SIGN_SECRET=<32+ 字节随机>`,
   `IM_MEDIA_SIGN_TTL=86400`;两边必须一致(不一致的表现:全部图片 403);
2. **nginx**(站点 `server{}` 内,必须在 `location ^~ /media/` **之前**):

```nginx
# 聊天图片:带签名才能访问(secure_link 模块未编译,用 auth_request)
location ^~ /media/chat/ {
    auth_request /_im_media_auth;
    alias /www/wwwroot/chatapp/chatapp/media/;
    expires 1h;
    add_header Cache-Control "private, max-age=3600";
}

location = /_im_media_auth {
    internal;
    proxy_pass http://127.0.0.1:8000/api/v1/im/images/auth;
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";
    proxy_set_header X-Original-URI $request_uri;
}
```

3. **cron**:见 §6.7;
4. **验证**:上传→发图→右键复制图片地址→去掉 `?e=&s=` 打开应 403;带上应 200;
   把 `e` 改小(已过期)应 403;
5. **回退**:删掉 `location ^~ /media/chat/` 一段并 reload nginx 即恢复公开直出
   (Django/imserver 的签名逻辑保留不生效,因为没人验签)。

## 10. 未覆盖的范围

- 用户头像、广场图片仍是 `/media/` 公开直出(同一个 alias)。它们本来就展示给所有人,
  签名收益低;真要统一,后续把 `location ^~ /media/` 拆成 `photos/ posts/ chat/` 再逐类收口;
- 已删除/过期图片的**消息侧**标记(例如把消息体改成「图片已清理」):需要 imserver
  回调 Django 或反查,收益低,不做;
- 图片机器审核(独立立项,上线阻断项)。

## 11. 测试矩阵

| 层 | 用例 |
|---|---|
| Django 单元 | 签名确定性;共享测试向量;`e` 被篡改/过期/路径越界 → False;secret 为空 → 放行 |
| Django 接口 | 上传响应 URL 带 `e&s` 且可验;`GET /im/images/auth` 204/403/缺头;重封禁用户也能看图(AllowAny) |
| Django 命令 | 保留期删文件+改状态;`--apply` 缺省不删;孤儿文件按 mtime 过滤;删除残留补删;`im_media_stats` 输出 |
| Django 运营台 | 抽审页 `<img src>` 是签名 URL |
| imserver 单元 | `MediaSigner` 共享向量;`canonicalize` 去 query / 拒绝外链;未配置时不签名 |
| imserver 集成 | 历史与会话 `last_message` 的 image URL 带 `e&s` 且签名正确;发消息落库 body 无 query |
| 全量 | 后端 `manage.py test` 绿;imserver docker 测试绿;`ApiDocsCoverageTests` 绿 |

## 12. 风险与应对

| 风险 | 应对 |
|---|---|
| 两端签名算法漂移 | 共享测试向量写进两侧测试;任何一侧改算法先红 |
| 密钥不一致 → 全站图片 403 | 部署核对单第一步就验;`im_media_stats`/日志不打印密钥 |
| 30 天清理误删 | 默认 dry-run;先手动跑一次看汇总;`expired` 行保留可追溯 |
| auth_request 拖慢看图 | 单次 HMAC + 无 DB 查询;若压测出现瓶颈,退路是把验签结果按 (path,e) 放 Redis 缓存 60s |
| 图片 URL 在客户端缓存超过 25h | 聊天页每次进入都拉历史,URL 会刷新;旧图已解码在内存,不影响当前会话 |
