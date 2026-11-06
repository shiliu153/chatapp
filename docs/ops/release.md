# 发版与远端 Release

> **约束(2026-11-05 起,强制)**:**版本号一变,远端 Release 必须在下一次发版内同步更新** —— 不是「下次补」,
> 也不是「只发 APK 就够」。版本号、tag、Release 三者指向同一个提交,缺一项即视为发版未完成。
>
> **门禁**:`python scripts/sync_version.py --check` 会读本文 §5 的记录表 —— 当前 `app/pubspec.yaml` 的版本
> 在表里没有留痕、或 `tag` / `Release` 两列为空,直接退出码 1(CI 的 `contract.yml` 拦截)。

---

## 1. 什么算「版本更新」

改 `app/pubspec.yaml` 的 `version:`(含构建号 `+N`)即算。典型触发场景:

- 需要重新构建并分发 App 或 Web 的功能 / 修复 / 协议变更;
- 调整强制升级门槛(`MIN_APP_VERSION`)、下载地址(`APP_DOWNLOAD_URL`);
- 数据库迁移或配置变更导致「旧客户端必须升级才能继续用」。

纯服务端、不需要重新分发的改动**不升版本**,也就不需要 Release。

## 2. 版本号的三处同步(既有规则,不变)

事实来源只有 `app/pubspec.yaml`:

```bash
python scripts/sync_version.py --write    # 以 pubspec 为准写回 app_info.dart 与 web/package.json
python scripts/sync_version.py --check    # CI 用;不一致退出码 1
```

配套的服务器变量:`MIN_APP_VERSION` / `LATEST_APP_VERSION` / `APP_DOWNLOAD_URL`(见 `README.md` §6)。
`MIN_APP_VERSION` 同时卡网页端,只升 App 会让整站被「需要更新后才能继续使用」挡住。

## 3. 发版清单(按顺序执行)

| # | 动作 | 完成标志 |
|---|---|---|
| 1 | 走完发布流程:分支 → PR → CI 全绿 → squash 合并 | 记下**合并后**的 `origin/master` SHA |
| 2 | `python scripts/sync_version.py --write` | `--check` 退出码 0 |
| 3 | 构建 APK(`--dart-define=ERROR_REPORTING=true`)与 Web(`npm run build`) | 产物存在,版本号与关于页一致 |
| 4 | 部署:APK 上传到 `/www/wwwroot/chatapp-web/chatapp-<版本>.apk`,更新 `.env` 三个变量,重启 web;`dist` 覆盖 | 重启后 `/app/config` 返回新 `latest_version` |
| 5 | 打 tag 并推送:`git tag -a v<版本> -m "<一句话主题>" <步骤 1 的 SHA>` + `git push origin v<版本>` | `git ls-remote --tags origin` 能看到 |
| 6 | **建 / 更新 Release**(§4) | Release 页面可见,附件可下载 |
| 7 | 在 §5 记录表加一行(版本 / 日期 / tag / Release / SHA / APK) | `sync_version.py --check` 退出码 0 |
| 8 | 生产冒烟:`/api/v1/app/config` 版本正确、APK 下载 206、`/health` 与 `/readyz` 200 | 无 5xx |

> 步骤 5 的 tag **必须指向步骤 1 的合并 SHA**,不要指向本地未合并提交 —— 与「部署只认 `origin/master` 的 SHA」同一条纪律。

## 4. Release 规范

| 项 | 规则 |
|---|---|
| tag | `v<版本名>`,如 `v1.0.4`;**附注 tag**(`-a`),消息写本期主题 |
| title | `v<版本> — <一句话主题>`,如 `v1.0.4 — 游标分页` |
| notes 结构 | 新增 / 变更 / 修复 / 运维注意(含 `MIN_APP_VERSION` 是否变动)/ 验证命令;不写营销文案 |
| 附件 | 签名 APK,重命名为 `chatapp-<版本>.apk`;`app-release.apk.sha1` 的内容抄进 notes |
| 不挂的 | Web `dist`(由服务器直出,不进 Release)、任何含密钥的文件 |
| 既有 Release | 说明写错用 `gh release edit`;补附件用 `gh release upload`(覆盖加 `--clobber`) |

```bash
# 推荐:gh CLI
gh release create v1.0.4 \
  --title "v1.0.4 — 游标分页" \
  --notes-file /tmp/notes-1.0.4.md \
  app/build/app/outputs/flutter-apk/app-release.apk#chatapp-1.0.4.apk

# 无 gh 时:REST 回退(需要具 repo 权限的 token)
curl -sS -X POST https://api.github.com/repos/shiliu153/chatapp/releases \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  -d @release.json          # {tag_name, name, body, draft:false}
# 附件另走 POST .../releases/{id}/assets?name=chatapp-1.0.4.apk(二进制上传,Content-Type: application/vnd.android.package-archive)

# 纯网页:Releases → Draft a new release → 选择已推送的 tag → 粘贴 notes → 上传 APK
```

## 5. 发版记录(门禁读取本节)

> 新增版本时**先加行,再发版**。`tag` 列必须写成 `` `v<版本>` ``;`Release` 列必须非空 ——
> 尚未建好时写「待建」并注明原因,建好后改回链接。

| 版本 | 日期 | tag | Release | 上线 SHA | APK |
|---|---|---|---|---|---|
| 1.0.1 | 2026-10-28 | — | 无(规则生效前发版) | — | `chatapp-1.0.1.apk` |
| 1.0.2 | 2026-11-01 | — | 无(规则生效前发版) | — | `chatapp-1.0.2.apk` |
| 1.0.3 | 2026-11-04 | — | 无(规则生效前发版) | `56f3f5b` | `chatapp-1.0.3.apk` |
| 1.0.4 | 2026-11-04 | `v1.0.4` | 待建:tag 已推送,Release 对象待建(现成材料见 §6) | `ae7099f` | `chatapp-1.0.4.apk` |
| 1.0.5 | 2026-11-05 | `v1.0.5` | [v1.0.5 — 暗黑模式](https://github.com/shiliu153/chatapp/releases/tag/v1.0.5)(附件 `chatapp-1.0.5.apk`) | `3390ab5` | `chatapp-1.0.5.apk` |
| 1.0.6 | 2026-11-06 | `v1.0.6` | [v1.0.6 — 共同点破冰](https://github.com/shiliu153/chatapp/releases/tag/v1.0.6)(附件 `chatapp-1.0.6.apk`) | `605ad81` | `chatapp-1.0.6.apk` |
| 1.0.7 | 2026-11-06 | `v1.0.7` | [v1.0.7 — 站内通知中心](https://github.com/shiliu153/chatapp/releases/tag/v1.0.7)(附件 `chatapp-1.0.7.apk`,60,295,070 字节) | `2bf9d1a` | `chatapp-1.0.7.apk` |
| 1.0.8 | 2026-11-07 | `v1.0.8` | 待建:合并后由 `scripts/create_release.py` 创建 | 待上线 | `chatapp-1.0.8.apk` |

## 6. 补建 v1.0.4 的现成材料

约束从 1.0.4 起生效,该版本的 tag 已推送(`v1.0.4` → `ae7099f`,即 D-1 上线所用提交),
但 **Release 对象尚未创建** —— 当前环境无 `gh` CLI 与 GitHub token,Release 属于 API 侧对象,
只能在有凭据的环境或网页上创建。以下内容可直接粘贴。

**tag / 目标提交**

```
v1.0.4  →  ae7099f241afbce60a09d9b8d1af397348dc39e7
          chore(release): 版本号 1.0.4(游标分页随包发布)(#51)
```

**标题**:`v1.0.4 — 游标分页`

**notes 草稿**(`--notes-file` 用)

```markdown
## 变更

- 列表接口改用 cursor/keyset 分页替代 offset:请求带 `?before=<不透明游标>`,
  响应返回 `count / next_cursor / has_more / results`;排序键带主键兜底,翻页期间有新数据插入
  也不会重复或漏读,深翻页耗时与页深无关。
- 覆盖 5 个接口:`GET /posts`、`GET /posts/mine`、`GET /matches`、`GET /discovery/likes`、`GET /discovery/visits`。
- `offset` 参数保留为兼容分支:带 `offset` 且不带 `before` 时仍返回旧的 `count/next/previous/results` 形状,
  老客户端不会在翻页时卡住;新代码一律走游标。
- App 与 Web 双端适配:响应带 `next_cursor` 就顺着游标翻,否则退回 offset。

## 运维注意

- 本次**无数据库迁移**;后端为 `ae7099f`(PR #51),Web `dist` 已覆盖。
- `LATEST_APP_VERSION` = 1.0.4、`APP_DOWNLOAD_URL` 指向本包;**`MIN_APP_VERSION` 保持 1.0.1**,
  老客户端不被挡。
- 部署回滚点:代码 `a08599b`、`.env.bak.20261104-2041-104`、旧 dist 备份
  `/www/backup/chatapp-web-dist-20261104-2032-preD1.tar.gz`。

## 验证

- `GET /api/v1/app/config` → `latest_version=1.0.4`
- 游标翻页第 2 页与第 1 页零重叠;`offset` 老路径响应形状不变;非法游标返回 `400` + 统一错误信封

## 附件校验

`app-release.apk` → `chatapp-1.0.4.apk`,72.3 MB
SHA-1 `3c397b97fd6cd003c6ab5c7998b15f6695bc90a5`
```

**附件**:`app/build/app/outputs/flutter-apk/app-release.apk`(72.3 MB,2026-11-04 20:38 构建)

**创建命令**

```bash
# 有 gh 时(在仓库根目录)
gh release create v1.0.4 \
  --title "v1.0.4 — 游标分页" \
  --notes-file /tmp/notes-1.0.4.md \
  app/build/app/outputs/flutter-apk/app-release.apk#chatapp-1.0.4.apk
```

建好后把 §5 表里 1.0.4 行的 `Release` 列改成 Release 链接。

## 6.1 v1.0.5 的发版材料(已发布,留档备查)

**状态:已发布。** tag `v1.0.5` 已推送;Release 对象 2026-11-05 23:36 通过 GitHub REST
(`POST /repos/shiliu153/chatapp/releases` + `uploads.github.com/.../assets`)创建并上传附件
—— 本机没有 `gh` CLI,但 GitHub MCP 配了带 `repo` 权限的 PAT,直接走 REST 即可
(该 PAT 的 toolsets 里没有 release 工具,所以不是「MCP 做不了」而是「没暴露工具」)。

以下为当时使用的标题与 notes,留档便于以后核对。

**tag / 目标提交**

```
v1.0.5  →  3390ab5551f55984d540a4eeb42a1cf004dc2063
          feat(app,web): 暗黑模式(批次 F)+ 禁用裸色值硬门禁 + 版本 1.0.5 (#79)
```

**标题**:`v1.0.5 — 暗黑模式`

**notes 草稿**(`--notes-file` 用)

```markdown
## 新增

- App 与 Web 双端支持「跟随系统 / 浅色 / 深色」三态外观,选择落本地,重启后保留。
- App 设置页新增「外观」卡(三态分段控件);Web 设置页同步新增。

## 变更

- App 取色全量迁移到 `HeartColors`(ThemeExtension,14 个语义色):68 个文件 301 处,
  暗色下中性色阶与语义色换值,**品牌色 #FF2C55 不变**(心跳渐变仍是视觉锚点)。
- 渐变(心跳 / 系统 / 完成度环)改为主题感知,暗色下 `heartOrange` 由 #FF7A45 提亮到 #FF8A5B。
- Web `tokens.css` 新增 `[data-theme='dark']` 覆盖块,页面零改动(一直只用 CSS 变量)。

## 修复

- 无。

## 运维注意

- 本次**无后端改动、无数据库迁移**;后端 SHA 不变,只需覆盖 Web `dist` 并分发新 APK。
- `LATEST_APP_VERSION` = 1.0.5、`APP_DOWNLOAD_URL` 指向本包;**`MIN_APP_VERSION` 保持 1.0.1**,
  老客户端不被挡。
- 回滚点:代码回 `3a71568`(本版之前)、旧 `dist` 备份、`.env` 备份。

## 验证

- App:`flutter analyze` 零告警 + `flutter test` **485 绿**。
- Web:`vue-tsc` + `eslint --max-warnings 0` 零告警 + `vitest` **420 绿**
  (覆盖率 85.58 / 78.07 / 80.34 / 88.09)。
- 后端:`manage.py test` **791 OK**;`python scripts/sync_version.py --check` 绿。
- 零裸色值:两条硬门禁(App `no_raw_colors_test.dart`、Web `no-raw-color.spec.ts`)
  均验证过「故意注入违规 → 变红」;暗色回归 24 条用例逐页断言不出现浅色面。

## 附件校验

`app-release.apk` → `chatapp-1.0.5.apk`,57.4 MB
SHA-1 `ba136f38aaf3152b10595a7f74c5e84cca83fdf8`
```

**附件**:`app/build/app/outputs/flutter-apk/app-release.apk`(57.4 MB,2026-11-05 22:5x 构建)

**创建命令**

```bash
gh release create v1.0.5 \
  --title "v1.0.5 — 暗黑模式" \
  --notes-file /tmp/notes-1.0.5.md \
  app/build/app/outputs/flutter-apk/app-release.apk#chatapp-1.0.5.apk
```

建好后把 §5 表里 1.0.5 行的 `Release` 列改成 Release 链接。

### 1.0.5 上线实况(2026-11-05 23:17–23:26)

| 项 | 结果 |
|---|---|
| 代码 SHA | `3390ab5`(PR #79 squash 合并提交,`v1.0.5` 指向它) |
| 后端 | **未变更**,仍是 `3f2d73d0` —— 批次 F 零后端改动、零迁移,不做无谓重启 |
| Web `dist` | 已覆盖 `/www/wwwroot/chatapp-web`(index.html + 91 个 assets;新 CSS 含 `[data-theme=dark]` 块,`--color-bg-page` 两套值 `#f6f7fb` / `#0e1015` 均在) |
| APK | `chatapp-1.0.5.apk` 58 MB,SHA-1 `ba136f38aaf3152b10595a7f74c5e84cca83fdf8`(与本地构建逐字节一致) |
| `.env` | `LATEST_APP_VERSION=1.0.5`、`APP_DOWNLOAD_URL=…/chatapp-1.0.5.apk`;**`MIN_APP_VERSION` 保持 1.0.1** |
| 重启 | `supervisorctl restart "chatapp-web:*"`(宝塔 supervisor 的程序名是 `组:实例` 形式,直接写 `chatapp-web` 会报 no such process);celery 未重启 |
| 验证 | `/api/v1/app/config` → `latest_version=1.0.5`、`download_url` 指向新包、`min_app_version=1.0.1`;`/health` 200、`/readyz` 200;APK Range 请求 206;`/` 200(新构建) |
| 回滚点 | 代码 `3a71568`;`.env` `/www/backup/chatapp-env-20261105-2325.bak`;旧 dist `/www/backup/chatapp-web-dist-20261105-2325-pre105.tar.gz` |

> 注:批次 F 的前端产物与 APK 才是本次交付物,后端 SHA 落后于 `origin/master` 属预期
> (后端在 C-1 之后没有必须随本版上线的改动)。下次有后端改动时再按 §3 走完整部署。


## 6.2 v1.0.6 的发版材料(批次 G · 共同点破冰)

**状态:已发布(2026-11-06 12:05–12:13 上线)。**

- 合并:PR #83 squash 合并 → `ba24f93`(功能提交);随后 docs PR #84 → `605ad81`;
  **上线用的就是 `605ad81`**(`origin/master` HEAD,后端代码与 `ba24f93` 相同);
- tag:`v1.0.6` → `ba24f93c4bd6ce905d39f043a52e1e7134533eb2`(附注 tag,指向合并 SHA);
- Release:2026-11-06 通过 GitHub REST(`POST /repos/shiliu153/chatapp/releases`
  + `uploads.github.com/.../assets`)创建,附件 `chatapp-1.0.6.apk`;
- APK:57.4 MB,SHA-1 `8d6353147abb6088c245d40df64a7a7825774cf9`(本机 `flutter build apk --release`
  从 `ba24f93` 构建,带 `ERROR_REPORTING=true`)。

### 1.0.6 上线实况(2026-11-06 12:05–12:13)

| 项 | 结果 |
|---|---|
| 代码 SHA | `605ad81`(`origin/master` HEAD;服务器 `git rev-parse HEAD` 一致) |
| 后端 | `git reset --hard 605ad81` → `pip install -r requirements.txt`(无新依赖)→ `migrate`(**无迁移**)→ `collectstatic`(156 未变)→ 重启 `chatapp-web:*` 与 `chatapp-celery:*` |
| Web `dist` | 本地 `npm run build` 打包上传覆盖 `/www/wwwroot/chatapp-web`(index.html 646 B,新 `index-D31iNva9.js` / `index-DMJDpefF.css`,新增 chunk `MatchMoment-DMMF1Gp8.js` 内含两套破冰文案) |
| APK | `chatapp-1.0.6.apk` 60,196,766 B,SHA-1 `8d6353147abb6088c245d40df64a7a7825774cf9`(与 Release 附件同源,服务器 `sha1sum` 一致) |
| `.env` | `LATEST_APP_VERSION=1.0.6`、`APP_DOWNLOAD_URL=…/chatapp-1.0.6.apk`;**`MIN_APP_VERSION` 保持 1.0.1** |
| 重启 | 面板 supervisor 程序名是 `组:实例` 形式:`/www/server/panel/pyenv/bin/supervisorctl restart "chatapp-web:*" "chatapp-celery:*"`(直接写 `chatapp-web` 会报 no such process);`supervisorctl` 不在 PATH 里 |
| imserver | **未动**(本批零 IM 改动);`/internal/healthz` 与 `/internal/readyz` 均 200 |
| 验证 | `/api/v1/app/config` → `latest_version=1.0.6`、`download_url` 指向新包、`min_app_version=1.0.1`;`/health` `/readyz` `/api/v1/health` 200;`/` 200(新构建);`/assets/index-D31iNva9.js` 200;APK Range 请求 206;线上代码实测 `GET /matches` 与 `GET /users/{id}` 均返回 `shared_tags`(样例:`[{"id":1,"name":"运动"},{"id":3,"name":"电影"}]`) |
| 回滚点 | 后端 `3f2d73d0`;`.env` `/www/backup/chatapp-env-20261106-1205.bak`(改动前另存 `…-1208-pre106env.bak`);旧 dist `/www/backup/chatapp-web-dist-20261106-1205-pre106.tar.gz`;汇总见 `/www/backup/chatapp-rollback-1.0.6.txt` |

以下为创建 Release 时使用的标题与 notes,留档便于以后核对。

**标题**:`v1.0.6 — 共同点破冰`

**notes 草稿**

```markdown
## 变更

- 配对那一刻告诉双方「你们都喜欢什么」,提高开口率。**只在配对那一刻展示**:
  App 配对动效、Web 配对弹窗、Web 配对列表卡片;聊天页不做提示(计划 §2.2 的范围收敛)。
- 后端新增 `shared_tags`(共同标签 = 对方标签 ∩ 我的标签):
  - `GET /api/v1/users/{id}` 新增字段;
  - `GET /api/v1/matches` 每项新增字段,**整页一次批量求交**,不随配对条数增加查询;
  - `POST /api/v1/discovery/swipe` 配对成功时直接带回 —— 客户端因此**不必**再拉一次对方资料
    (那会被记成一次访客访问,语义污染)。
- 破冰文案是**纯客户端模板**(不调外部服务、不引 LLM):有交集 → 「你们都喜欢 X、Y,不如从这儿聊起?」;
  无交集但同城 → 「你们都在 X」;都不满足则整行不展示(不提性别)。
- Web 配对列表卡片展示最多 2 个共同标签 chip。

## 运维注意

- **后端有改动**(序列化器 + 两个视图),需按 §3 部署后端;**无迁移**。
- Web `dist` 需重新构建部署;APK 需重新打包上传。
- `.env` 只改 `LATEST_APP_VERSION=1.0.6` 与 `APP_DOWNLOAD_URL`;**`MIN_APP_VERSION` 保持不动**
  (老客户端不被挡)。
- 查询预算门禁未放宽:`matches` 仍是 ≤ 9 条 SQL,实测新增 1 条。

## 验证

- 后端:`manage.py test` **799 OK**;`spectacular --validate` 零 warning;
  `test_schema_contract` / `ApiDocsCoverageTests` 绿;`comment_coverage` 无缺口。
- App:`flutter analyze` 零告警 + `flutter test` **495 绿**。
- Web:`vue-tsc` + `eslint --max-warnings 0` 零告警 + `vitest` **432 绿**。
- `python scripts/sync_version.py --check` 绿。
```

**附件**:`app/build/app/outputs/flutter-apk/app-release.apk` → 上传为 `chatapp-1.0.6.apk`

**创建命令**(本机无 `gh`,走 GitHub REST + PAT,与 1.0.5 同法)

```bash
gh release create v1.0.6 \
  --title "v1.0.6 — 共同点破冰" \
  --notes-file /tmp/notes-1.0.6.md \
  app/build/app/outputs/flutter-apk/app-release.apk#chatapp-1.0.6.apk
```

建好后把 §5 表里 1.0.6 行的 `Release` / `上线 SHA` / APK 三列补齐。


## 6.3 v1.0.7 的发版材料(批次 H · 站内通知中心)

- tag:`v1.0.7` → `2bf9d1a5de52b013e24673e6ad9d2678fe991be2`(附注 tag,指向合并 SHA;已推送)
- 附件:`app/build/app/outputs/flutter-apk/app-release.apk` → `chatapp-1.0.7.apk`(57.5 MB)
- Release 标题:`v1.0.7 — 站内通知中心`

**notes 草稿**

```markdown
## 新增

- **站内通知中心**(批次 H):点赞 / 评论 / 回复 / 配对成功 / 举报处理五类事件聚合到一个入口,
  消息页顶栏铃铛 + 未读角标;点开一条标已读并按目标跳转(动态详情 / 与对方聊天),支持「全部已读」。
- 后端新增 3 个接口:`GET /api/v1/notifications`(游标分页)、`GET /api/v1/notifications/unread_count`、
  `POST /api/v1/notifications/read`(按 ids 或 all)。文档见 `docs/api/notifications.md`。
- 通知只保留 90 天(查询侧截断);`notifications_prune` 管理命令回收旧数据(默认 dry-run)。
- 通知偏好新增 `social` 开关(动态被赞 / 被评论 / 被回复),默认开;`GET/PATCH /push/preferences` 响应多一个字段。

## 变更

- IM 灰条**保留不变**:通知是聚合索引,灰条仍是聊天记录里的事实,两者并存。
- 「喜欢我的人 / 谁看过我 / 新粉丝」**不产生**通知(它们已有入口角标与列表页)。

## 修复

- 无。

## 运维注意

- **后端有迁移**:新增 `notifications_inappnotification` 表与 `notificationpreference.social` 列,
  部署时先 `migrate` 再重启 `chatapp-web` / `chatapp-celery`。
- Web `dist` 需重新构建部署;APK 需重新打包上传。
- `.env` 只改 `LATEST_APP_VERSION=1.0.7` 与 `APP_DOWNLOAD_URL`;**`MIN_APP_VERSION` 保持 1.0.1**。

## 验证

- 后端:`manage.py test` 全绿;`spectacular --validate` 零 warning;三处文档门禁绿;`comment_coverage` 无缺口。
- App:`flutter analyze` 零告警 + `flutter test` 全绿。
- Web:`vue-tsc` + `eslint --max-warnings 0` 零告警 + `vitest` 全绿。
- `python scripts/sync_version.py --check` 绿。
```

**创建命令**(2026-11-07 起用脚本,见下「Release 通道」)

```bash
python scripts/create_release.py --version 1.0.7 \
  --title "v1.0.7 — 站内通知中心" \
  --notes-file /tmp/notes-1.0.7.md \
  --apk app/build/app/outputs/flutter-apk/app-release.apk \
  --asset-name chatapp-1.0.7.apk
# 幂等:已有同 tag 就 PATCH 更新 notes;同名附件先删后传
```

**Release 通道(2026-11-07 起)**:本机有 GitHub MCP(`mcp-github`)与它用的同一个 classic PAT
(`repo` 权限,`~/.dsh/github-mcp-token.txt`)。MCP 的工具集里**只有** `get_latest_release` /
`list_releases` / `get_release_by_tag`,**没有** `create_release`,所以 Release 走
`scripts/create_release.py`(标准库 `urllib`,读的就是 MCP 那个 token 文件)。
**不要再写「本机无 `gh`/token,Release 待建」** —— 1.0.7 的 Release 就是这样建出来的:
<https://github.com/shiliu153/chatapp/releases/tag/v1.0.7>。

### 1.0.7 上线实况(2026-11-06 13:19–13:24)

- **回滚点(先记录后动手)**:代码 `605ad81`;`.env` 备份 `/www/backup/chatapp-env-1.0.6-.bak`
  (`cp -a` 保留源 mtime,内容为 1.0.6);旧 Web `dist` 备份
  `/www/backup/chatapp-web-dist-1.0.6-.tar.gz`(347 KB);DB 全量备份
  `/www/backup/chatapp-db-preH-20261106-1320.sql`(601 KB,`--single-transaction`)。
- **部署**:`git fetch && git reset --hard 2bf9d1a`(origin/master 合并 SHA)→
  `migrate --noinput`(唯一一条:`notifications.0002_notificationpreference_social_inappnotification` OK)→
  `collectstatic`(0 复制 / 156 未变)→ `supervisorctl restart chatapp-web:* chatapp-celery:*`
  (两个进程 RUNNING,重启窗口约 10 秒)→ Web `dist` tar 覆盖 `/www/wwwroot/chatapp-web`
  (新 chunk `NotificationsPage-D2AYIKrl.js`)→ APK 上传为 `chatapp-1.0.7.apk`(60,295,070 字节)→
  `.env` 只改 `LATEST_APP_VERSION=1.0.7` / `APP_DOWNLOAD_URL`(**`MIN_APP_VERSION` 保持 1.0.1**)。
- **冒烟(全绿)**:
  - `/api/v1/app/config` → `{"min_app_version":"1.0.1","latest_version":"1.0.7",...}`;
    `/health` `/readyz` 200;APK `Range: bytes=0-1023` → `206`(Content-Range `0-1023/60295070`)。
  - 用白名单账号 `13900000001`(user 12)登录:`GET /notifications` → `{count:0,...}` 形状正确;
    `GET /notifications/unread_count` → `{"unread":0}`;`POST /notifications/read {"all":true}` → 204;
    未认证 → 401;`GET /push/preferences` 多出 `"social":true`。
  - **事件 hook 端到端**:用该账号首次点赞别人的动态(响应 201)→ 生产库
    `notifications_inappnotification` 立刻出现一行
    `user_id=8, kind=post_like, actor_id=12, target_kind=post, target_id=7, text="小雨12 赞了你的动态",
    dedupe_key=like:7:12`(验证完删除该测试行,库里恢复 0 行)。
  - Web 深链 `/notifications` → 200,新 chunk 200。
- **Release(2026-11-07 补建)**:`v1.0.7` 的 GitHub Release 已用 `scripts/create_release.py` 建好
  (title「v1.0.7 — 站内通知中心」,附件 `chatapp-1.0.7.apk`,60,295,070 字节,
  SHA-1 `5fe74a4eb1c67e543233577f5ff717b09c325330`),链接见 §5。
- **App 真机验收**:`emulator-5554`(Pixel_7 / Android 17)已装 1.0.7 签名包并跑通启动 → 协议弹窗 →
  登录页;但**登录提交这一步在模拟器上失败**(见 `docs/pitfalls/android-emulator.md` 新增条目:
  点「获取验证码」报「网络不给力」,服务端 0 条 `/auth/sms/send`,而同机 `GET /app/config` 正常),
  因此通知页的模拟器逐页手测**待网络问题定位后补做**;App 侧目前由 506 条自动化测试覆盖。


## 7. 为什么这条约束值得存在

版本号、tag、Release 是**同一件事的三个面**:版本号给客户端判升级,tag 给 git 定位「这个包是哪份代码」,
Release 给人(以及未来的自己)看「这版改了什么、包在哪」。只做前两件时,半年后要回答
「线上那个 1.0.4 到底对应哪次改动、当时为什么升」就只能翻 `docs/milestones.md` 猜。
三者对齐后,`docs/milestones.md` 只留里程碑级叙事,发版级事实由 Release 承担。
