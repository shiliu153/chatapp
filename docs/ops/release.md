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

## 7. 为什么这条约束值得存在

版本号、tag、Release 是**同一件事的三个面**:版本号给客户端判升级,tag 给 git 定位「这个包是哪份代码」,
Release 给人(以及未来的自己)看「这版改了什么、包在哪」。只做前两件时,半年后要回答
「线上那个 1.0.4 到底对应哪次改动、当时为什么升」就只能翻 `docs/milestones.md` 猜。
三者对齐后,`docs/milestones.md` 只留里程碑级叙事,发版级事实由 Release 承担。
