# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概况

交友软件(dating app)全栈项目,计划技术栈:

- **前端**: Flutter(Dart)
- **后端**: Django(Python)
- **聊天**: 腾讯云 IM SDK(即时通讯走腾讯云 IM,业务数据由 Django 后端存储)

**当前处于初始阶段,前后端业务代码均未创建。** 用户以中文交流,回复请使用中文。

## 目录结构现状

| 路径 | 内容 | 说明 |
|---|---|---|
| `flutter/` | **Flutter SDK 3.47.2 stable 源码**(自带独立 `.git`,Dart 3.13.2),从 github.com/flutter/flutter clone 的框架仓库 | 这是 SDK,不是应用代码,**切勿修改**。Windows 下可执行 `flutter/bin/flutter.bat`(工具快照已缓存,可直接运行) |
| `chatapp/` | 计划中的 Django 后端目录 | 目前仅残留 `chatapp/chatapp/flutter.create`(`{"template":"app"}`,一次被中断的 `flutter create` 留下的标记),无任何代码,该残留可删除 |
| `.remember/` | Claude Code 会话记忆日志目录(内部机制,.gitignore 忽略一切) | 勿改动、勿提交 |

项目根目录尚未 `git init`;`flutter/` 内部是独立的 git 仓库(根目录 init 时注意嵌套仓库问题)。

## 运行环境

- Windows 11,shell 为 bash(MSYS 风格),路径使用正斜杠。
- 本机 Flutter SDK 即仓库内 `flutter/` 目录,命令行调用: `flutter/bin/flutter.bat <命令>`(如 `flutter.bat --version`);若已将其他 Flutter 加入 PATH,二者可能版本不同,需留意。
- 常用 flutter 命令(应用创建后): `flutter create` / `flutter run` / `flutter analyze` / `flutter test`。
- Django 命令在项目搭建后为: `python manage.py runserver` / `makemigrations` / `migrate`(尚无 manage.py)。

## 规划中的技术要点(聊天功能)

- 腾讯云 IM 标准接入流程: 注册/登录打通(Flutter 端用 IM SDK 登录,`tim_plus_flutter` 是官方 Flutter IM SDK 包)、**userSig 必须由 Django 后端签发**(服务端持有 SDKAppID 与密钥),Flutter 端只持 SDKAppID 和临时 userSig。
- 单聊用 IM C2C 会话;业务数据(个人资料、喜欢/匹配关系、动态等)存 Django 数据库,与 IM 用户体系通过 IM userID 关联。
- 需要的腾讯云凭据: SDKAppID、密钥等,尚未在仓库中配置,勿把密钥写进代码/提交。

## 下一步建议

1. 创建 Flutter 应用项目 —— 放在独立目录(如根目录下新建 `app/`),**不要**放进 `flutter/`(SDK)或沿用残留标记的 `chatapp/`。
2. 在 `chatapp/` 下初始化 Django 项目与依赖(requirements.txt / venv)。
3. 在腾讯云控制台开通 IM 服务、拿到 SDKAppID 与密钥后,再编写 userSig 签发接口。
