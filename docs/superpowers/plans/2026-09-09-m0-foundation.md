# M0 地基实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭起可运行的前后端地基 —— Django(MySQL)能跑、Flutter 应用能跑、两端 HTTP 连通,腾讯云 IM 账号就绪。此计划对应 spec 的 M0 里程碑。

**Architecture:** 单体 Django(5 个业务 app 骨架 + 自定义 User 模型)+ Flutter app 的 dio 网络层;两端先以 `/api/v1/health` 握手。业务代码(账号/资料/滑卡/IM)全部留到 M1/M2 的独立计划,本计划**不写任何业务接口**。

**Tech Stack:** Python 3.10(anaconda 环境 `Django`)、Django 5.2 LTS、DRF、SimpleJWT、django-cors-headers、PyMySQL、python-dotenv、MySQL 8(本机)、Flutter 3.47.2(仓库内 `flutter/`)、Dart 3.13.2、dio、http。

## Global Constraints

- 所有 shell 命令在 Windows Git Bash 里跑;路径一律正斜杠;`python` 指 anaconda 的 `Django` 环境(已验证 3.10.19)
- 仓库根 `D:\pycharmproject\chat_app` 已是 git 仓库;**严禁改动 `flutter/` 目录**(它是 SDK 源码,自带独立 git)
- 每个 Task 结束时必须提交一次 git,消息格式按模板
- 密钥/口令一律只进 `.env`(已 gitignore),禁止写入代码或提交
- MySQL 库一律 utf8mb4;`.env` 里 DB 口令由用户自己填真实值
- Django 项目目录结构: `chatapp/` 下 `config/`(项目包)与 5 个 app: `accounts users discovery im moderation`
- 本计划无任何业务模型/接口 —— 自定义 User 模型除外(必须在首次 migrate 前定稿,否则返工)
- 用户是 Django/Flutter 新手:每步给命令与预期输出,失败就往下一步前的「卡点速查」看

---

### Task 1: 建 MySQL 库并生成 Django 项目骨架(先定 AUTH_USER_MODEL 之前的空壳)

**Files:**
- Create: `chatapp/db_setup.sql`
- Create: `chatapp/requirements.txt`
- Create: `chatapp/.env`(内容含占位口令,用户改真实值)
- Create: `chatapp/.env.example`(提交用)
- Create: `chatapp/config/`(由 startproject 生成)

**Interfaces:**
- Consumes: 无(本仓库第一份代码)
- Produces: `chatapp/config/settings.py`(读 `.env` 的 MySQL 配置)、可用的 `python manage.py` 入口。后续 Task 2 在此上加自定义 User。

**为什么:** Django 的认证用户模型(AUTH_USER_MODEL)必须在**第一次 migrate 之前**设定,否则要删库重来 —— 所以顺序必须是:先建项目壳 → 立刻建 accounts 的自定义 User → 然后才 migrate。

- [ ] **Step 1:写建库 SQL 文件**

`db_setup.sql` 内容(你只需在任意 MySQL 客户端里执行它,命令行没配 `mysql` 也不怕):

```sql
CREATE DATABASE IF NOT EXISTS chatapp_dev
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'chatapp'@'localhost' IDENTIFIED BY '<YOUR_DB_PASSWORD>';
GRANT ALL PRIVILEGES ON chatapp_dev.* TO 'chatapp'@'localhost';
FLUSH PRIVILEGES;
```

- [ ] **Step 2:用户在 MySQL 客户端执行该 SQL**

打开你的 MySQL 图形工具(或任意方式)以管理员执行 `chatapp/db_setup.sql`。口令 `<YOUR_DB_PASSWORD>` 是开发用口令,之后写进 `.env`(不入库不提交)。

卡点速查:连不上 = MySQL 服务没启动(Windows 服务里找 MySQL 启动);执行报权限错 = 用了非管理员账号。

- [ ] **Step 3:写 requirements.txt 并安装**

```text
Django>=5.2,<5.3
djangorestframework>=3.15
djangorestframework-simplejwt>=5.3
django-cors-headers>=4.4
PyMySQL>=1.1
cryptography>=42.0
python-dotenv>=1.0
```

```bash
cd "D:\pycharmproject\chat_app\chatapp" && python -m pip install -r requirements.txt
```

预期:成功结束;`python -c "import django; print(django.get_version())"` 输出 5.2.x。
PyMySQL 是纯 Python 驱动(免编译),配 `cryptography` 才能连 MySQL 8 默认加密插件 —— 两个都要装。

- [ ] **Step 4:生成项目骨架**

```bash
cd "D:\pycharmproject\chat_app\chatapp" && python -m django startproject config .
python manage.py startapp accounts
python manage.py startapp users
python manage.py startapp discovery
python manage.py startapp im
python manage.py startapp moderation
```

预期:目录变成 spec §4 的样子(`chatapp/config/`、五个 `accounts/...moderation/` 包、`manage.py`)。**先不 migrate**。

- [ ] **Step 5:配置 settings.py(MySQL + .env)**

编辑 `chatapp/config/__init__.py`,整文件替换为:

```python
import pymysql

pymysql.install_as_MySQLdb()
```

编辑 `chatapp/config/settings.py`:

顶部加(import os 之后):

```python
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv(BASE_DIR / ".env")
```

把 `SECRET_KEY` 行替换为:

```python
SECRET_KEY = os.getenv("SECRET_KEY", "dev-insecure-change-me")
DEBUG = os.getenv("DEBUG", "1") == "1"
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
```

`INSTALLED_APPS` 改为:

```python
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]
```

`DATABASES` 整体替换为:

```python
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.getenv("DB_NAME", "chatapp_dev"),
        "USER": os.getenv("DB_USER", "chatapp"),
        "PASSWORD": os.getenv("DB_PASSWORD", "<YOUR_DB_PASSWORD>"),
        "HOST": os.getenv("DB_HOST", "127.0.0.1"),
        "PORT": os.getenv("DB_PORT", "3306"),
        "OPTIONS": {"charset": "utf8mb4"},
    }
}
```

(注意:先别在 INSTALLED_APPS 注册五个新 app —— Task 2 里和自定义 User 一起注册。)

- [ ] **Step 6:生成 .env 与 .env.example**

```bash
cd "D:\pycharmproject\chat_app\chatapp"
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"   # 复制输出
```

写 `chatapp/.env`:

```env
SECRET_KEY=<上一步复制的随机串>
DEBUG=1
ALLOWED_HOSTS=127.0.0.1,localhost
DB_NAME=chatapp_dev
DB_USER=chatapp
DB_PASSWORD=<YOUR_DB_PASSWORD>
DB_HOST=127.0.0.1
DB_PORT=3306
```

写 `chatapp/.env.example`(同结构,口令用占位 `CHANGE_ME`,提交用)。

- [ ] **Step 7:验证**

```bash
cd "D:\pycharmproject\chat_app\chatapp" && python manage.py check
```

预期:输出 `System check identified no issues (0 silenced).`

- [ ] **Step 8:提交**

```bash
cd "D:\pycharmproject\chat_app" && git add chatapp/.env.example chatapp/requirements.txt chatapp/db_setup.sql chatapp/manage.py chatapp/config && git commit -m "feat: scaffold Django project with MySQL config (M0)"
```

确认 `git status` 里**没有** `.env`(已在 .gitignore)。

---

### Task 2: 自定义 User 模型(手机号登录)+ 首次 migrate

**Files:**
- Create: `chatapp/accounts/models.py`(覆盖模板)、`chatapp/accounts/tests.py`(覆盖模板)
- Modify: `chatapp/config/settings.py`(INSTALLED_APPS、AUTH_USER_MODEL)

**Interfaces:**
- Consumes: Task 1 的 settings(.env/MySQL)。
- Produces: `accounts.User`(`phone` 唯一、`USERNAME_FIELD="phone"`、`create_user(phone)`/`create_superuser(phone,password)`);AUTH_USER_MODEL="accounts.User"。全项目后续所有外键引用此模型(`get_user_model()`)。

- [ ] **Step 1:写失败的测试**

`chatapp/accounts/tests.py` 整体替换:

```python
from django.contrib.auth import get_user_model
from django.test import TestCase

User = get_user_model()


class UserManagerTests(TestCase):
    def test_create_user_requires_phone(self):
        user = User.objects.create_user(phone="13800138000")
        self.assertEqual(user.phone, "13800138000")
        self.assertFalse(user.has_usable_password())  # 验证码登录:无密码

    def test_create_superuser(self):
        admin = User.objects.create_superuser(phone="13900139000", password="admin-pass")
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)
```

- [ ] **Step 2:运行确认失败**

```bash
cd "D:\pycharmproject\chat_app\chatapp" && python manage.py test accounts
```

预期:FAIL / ERROR(accounts.User 还不存在)。

- [ ] **Step 3:写自定义 User 模型**

`chatapp/accounts/models.py` 整体替换:

```python
from django.contrib.auth.models import AbstractUser, UserManager as BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, phone, password=None, **extra_fields):
        if not phone:
            raise ValueError("phone is required")
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        user = self.model(phone=phone, **extra_fields)
        user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, phone, password, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        user = self.model(phone=phone, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user


class User(AbstractUser):
    username = None
    phone = models.CharField("手机号", max_length=20, unique=True)

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        return self.phone
```

`chatapp/config/settings.py` 中 `INSTALLED_APPS` 改为:

```python
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # 业务 app
    "accounts",
    "users",
    "discovery",
    "im",
    "moderation",
]
```

文件末尾追加:

```python
AUTH_USER_MODEL = "accounts.User"
```

注册 admin:`chatapp/accounts/admin.py` 整体替换:

```python
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model = User
    fieldsets = UserAdmin.fieldsets + (("手机号", {"fields": ("phone",)}),)
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("phone", "password1", "password2")}),)
    list_display = ("phone", "is_staff", "is_active")
    search_fields = ("phone",)
    ordering = ("id",)
```

- [ ] **Step 4:生成迁移并 migrate(首次!AUTH_USER_MODEL 定稿的唯一机会)**

```bash
cd "D:\pycharmproject\chat_app\chatapp" && python manage.py makemigrations accounts
python manage.py migrate
```

预期:migrate 输出一串 `OK`,包含 `auth`、`accounts`、`contenttypes`、`sessions`、`admin` 等;无报错即证明 PyMySQL 连上了 MySQL 8。

- [ ] **Step 5:运行测试确认通过**

```bash
python manage.py test accounts
```

预期:2 个用例 PASS。

- [ ] **Step 6:提交**

```bash
cd "D:\pycharmproject\chat_app" && git add chatapp/accounts chatapp/config/settings.py && git commit -m "feat: custom User model keyed by phone + initial migrate (M0)"
```

---

### Task 3: DRF + SimpleJWT + CORS + /api/v1/health(带接口测试)

**Files:**
- Modify: `chatapp/config/settings.py`
- Modify: `chatapp/config/urls.py`
- Create: `chatapp/config/api_urls.py`(业务接口统一挂载点)
- Create: `chatapp/accounts/views.py`、`chatapp/accounts/tests.py`(health 视图与测试放 accounts 是刻意简化,不单开 app)

**Interfaces:**
- Consumes: Task 2 的 `accounts.User`。
- Produces: `GET /api/v1/health` → `{"status": "ok"}`(AllowAny);Flutter 端 Task 5 拿它握手。DRF/SimpleJWT 全局配置为 M1 铺路。

- [ ] **Step 1:写失败的接口测试**

`chatapp/accounts/tests.py` 追加:

```python
from rest_framework.test import APITestCase


class HealthTests(APITestCase):
    def test_health_ok(self):
        resp = self.client.get("/api/v1/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})
```

- [ ] **Step 2:运行确认失败**

```bash
cd "D:\pycharmproject\chat_app\chatapp" && python manage.py test accounts
```

预期:FAIL(404)。

- [ ] **Step 3:配置 DRF/SimpleJWT/CORS 并实现视图**

`chatapp/accounts/views.py` 整体替换:

```python
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    return Response({"status": "ok"})
```

`chatapp/config/urls.py` 整体替换:

```python
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("config.api_urls")),
]
```

新建 `chatapp/config/api_urls.py`:

```python
from django.urls import path

from accounts.views import health

urlpatterns = [
    path("health", health),
]
```

(业务接口统一挂在 `api_urls.py`,保持 config 干净。)

`chatapp/config/settings.py`:`INSTALLED_APPS` 的 `# 业务 app` 上方加:

```python
    # 第三方
    "rest_framework",
    "corsheaders",
```

`MIDDLEWARE` 的 `SessionMiddleware` 之前(靠前)插入:

```python
    "corsheaders.middleware.CorsMiddleware",
```

文件末尾追加:

```python
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
}

CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^http://localhost:\d+$",   # Flutter Web / 调试用
    r"^http://127\.0\.0\.1:\d+$",
]
```

(默认所有接口要求登录 —— health 用 `AllowAny` 单独豁免;这是刻意设计,M1 的接口全自动带上鉴权。)

- [ ] **Step 4:运行测试确认通过**

```bash
python manage.py test accounts
```

预期:3 个用例 PASS(UserManager 2 个 + health 1 个)。

- [ ] **Step 5:手工起服务验证**

```bash
python manage.py runserver
```

另开终端:

```bash
curl http://127.0.0.1:8000/api/v1/health
```

预期:`{"status":"ok"}`。Ctrl+C 停掉 runserver。

- [ ] **Step 6:提交**

```bash
cd "D:\pycharmproject\chat_app" && git add chatapp/config chatapp/accounts && git commit -m "feat: DRF/SimpleJWT/CORS + health endpoint (M0)"
```

---

### Task 4: Flutter 应用创建并跑通 analyze/test

**Files:**
- Create: `app/`(flutter create 生成整棵工程树)

**Interfaces:**
- Consumes: 无。
- Produces: `app/` 工程(包名 `chatapp_app`,org `com.chatapp`)。Task 5 在此加网络层。

**为什么包名这么定:** `flutter create` 的项目名必须是合法 Dart 标识符,`app` 太泛。`com.chatapp.chatapp_app` 是开发期 applicationId,上架前可改。

- [ ] **Step 1:创建工程(首次运行会下载引擎工件,慢属正常)**

```bash
cd "D:\pycharmproject\chat_app" && flutter/bin/flutter.bat create app --project-name chatapp_app --org com.chatapp
```

预期:输出 `All done!`。若提示缺 Android SDK 许可证之类,**不阻塞本任务**(M2 联调真机前再处理),记录提示内容即可。

- [ ] **Step 2:analyze 零告警**

```bash
cd "D:\pycharmproject\chat_app\app" && ../flutter/bin/flutter.bat analyze
```

预期:`No issues found!`

- [ ] **Step 3:默认测试通过**

```bash
../flutter/bin/flutter.bat test
```

预期:默认 counter widget 测试 1 个 PASS(下一任务会替换成我们自己的)。

- [ ] **Step 4:提交(排除 build 产物)**

```bash
cd "D:\pycharmproject\chat_app" && git add app && git commit -m "feat: create Flutter app scaffold (M0)"
```

确认 `git status` 干净;`app/build`、`app/.dart_tool` 已在 .gitignore。

---

### Task 5: App 网络层(dio)+ 健康检查页,前后端握手

**Files:**
- Modify: `app/pubspec.yaml`(加 dio)
- Create: `app/lib/core/api_client.dart`
- Modify: `app/lib/main.dart`(替换默认 counter 页)
- Create: `app/test/fake_adapter.dart`、`app/test/api_client_test.dart`
- Modify: `app/test/widget_test.dart`(替换默认测试)

**Interfaces:**
- Consumes: Task 3 的 `GET /api/v1/health`。
- Produces: `ApiClient`(构造 `ApiClient(baseUrl: ..., {Dio? dio})`,方法 `Future<String> health()` 返回 `"ok"`;错误抛 `ApiException`)。M1 的 Repository 层全部通过它扩展。

- [ ] **Step 1:加依赖**

```bash
cd "D:\pycharmproject\chat_app\app" && ../flutter/bin/flutter.bat pub add dio
```

- [ ] **Step 2:写失败的测试(先写假适配器与单元测试)**

新建 `app/test/fake_adapter.dart`(哑 HTTP 层:不管请求什么,固定返回 200 + `{"status":"ok"}`,让测试完全离线):

```dart
import 'dart:typed_data';

import 'package:dio/dio.dart';

class FakeAdapter implements HttpClientAdapter {
  @override
  Future<ResponseBody> fetch(RequestOptions options, Stream<Uint8List>? requestStream, Future<void>? cancelFuture) async {
    return ResponseBody.fromString('{"status":"ok"}', 200,
        headers: {Headers.contentTypeHeader: [Headers.jsonContentType]});
  }

  @override
  void close({bool force = false}) {}
}
```

新建 `app/test/api_client_test.dart`(此时 `ApiClient` 尚不存在,测试会编译失败 —— 这就是"红"状态):

```dart
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:chatapp_app/core/api_client.dart';

import 'fake_adapter.dart';

void main() {
  test('health returns ok from api', () async {
    final dio = Dio()..httpClientAdapter = FakeAdapter();
    final api = ApiClient(baseUrl: 'http://x/api/v1', dio: dio);
    expect(await api.health(), 'ok');
  });
}
```

跑一次确认失败:

```bash
cd "D:\pycharmproject\chat_app\app" && ../flutter/bin/flutter.bat test test/api_client_test.dart
```

预期:编译错误(找不到 `ApiClient`)。**测试先于实现,错得越响越对。**

- [ ] **Step 3:实现 ApiClient 与页面**

`app/lib/core/api_client.dart`:

```dart
import 'package:dio/dio.dart';

class ApiException implements Exception {
  ApiException(this.message);
  final String message;

  @override
  String toString() => 'ApiException: $message';
}

class ApiClient {
  ApiClient({required this.baseUrl, Dio? dio})
      : _dio = dio ??
            Dio(BaseOptions(
              baseUrl: baseUrl,
              connectTimeout: const Duration(seconds: 10),
              receiveTimeout: const Duration(seconds: 10),
            ));

  final String baseUrl;
  final Dio _dio;

  Future<String> health() async {
    final resp = await _dio.get('/health');
    if (resp.statusCode != 200) {
      throw ApiException('HTTP ${resp.statusCode}');
    }
    return resp.data['status'] as String;
  }
}
```

`app/lib/main.dart` 整体替换:

```dart
import 'package:flutter/material.dart';

import 'core/api_client.dart';

const String apiBase = String.fromEnvironment('API_BASE',
    defaultValue: 'http://127.0.0.1:8000/api/v1');

void main() {
  runApp(const ChatApp());
}

class ChatApp extends StatelessWidget {
  const ChatApp({super.key, this.api});
  final ApiClient? api; // 测试注入用;不传则 HomePage 用真实 ApiClient

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '交友 Chat',
      theme: ThemeData(colorSchemeSeed: Colors.pink, useMaterial3: true),
      home: HomePage(api: api),
    );
  }
}

class HomePage extends StatefulWidget {
  const HomePage({super.key, this.api});
  final ApiClient? api; // 测试注入用

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  late final ApiClient _api = widget.api ?? ApiClient(baseUrl: apiBase);
  late Future<String> _health = _api.health();

  void _retry() {
    setState(() {
      _health = _api.health();
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('交友 Chat — M0 握手')),
      body: Center(
        child: FutureBuilder<String>(
          future: _health,
          builder: (context, snapshot) {
            if (snapshot.connectionState != ConnectionState.done) {
              return const CircularProgressIndicator();
            }
            if (snapshot.hasError) {
              return Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Text('后端连接失败', style: TextStyle(fontSize: 20)),
                  Text('${snapshot.error}', textAlign: TextAlign.center),
                  const SizedBox(height: 12),
                  FilledButton(onPressed: _retry, child: const Text('重试')),
                ],
              );
            }
            return Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.check_circle, color: Colors.green, size: 48),
                const Text('后端连接成功', style: TextStyle(fontSize: 20)),
                Text('status = ${snapshot.data}'),
              ],
            );
          },
        ),
      ),
    );
  }
}
```

**注入设计说明:** `ChatApp`/`HomePage` 都接受可选 `ApiClient? api` 参数 —— 测试注入假 ApiClient(离线),不传则用真实实现。这是最朴素的手工注入,不引入框架;M1 换成 Riverpod 时保留同样的"构造期注入"思路。

替换 `app/test/widget_test.dart`(默认模板里的 counter 测试已用不到)为:

```dart
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:chatapp_app/core/api_client.dart';
import 'package:chatapp_app/main.dart';

import 'fake_adapter.dart';

void main() {
  testWidgets('renders success state after health call', (tester) async {
    final dio = Dio()..httpClientAdapter = FakeAdapter();
    final api = ApiClient(baseUrl: 'http://x/api/v1', dio: dio);
    await tester.pumpWidget(ChatApp(api: api));
    await tester.pumpAndSettle();
    expect(find.text('后端连接成功'), findsOneWidget);
  });
}
```

- [ ] **Step 4:运行测试与 analyze**

```bash
cd "D:\pycharmproject\chat_app\app"
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
```

预期:analyze 零告警;2 个测试 PASS(api_client 1 个 + widget 1 个)。

- [ ] **Step 5:真实握手(可选验证)**

起后端:`cd "D:\pycharmproject\chat_app\chatapp" && python manage.py runserver`
另开终端起 App(任选其一):
- Windows 桌面:`cd "D:\pycharmproject\chat_app\app" && ../flutter/bin/flutter.bat run -d windows`(需 VS C++ 工具链;首次会下载工件)
- Chrome:`cd "D:\pycharmproject\chat_app\app" && ../flutter/bin/flutter.bat run -d chrome`

预期:页面显示绿色"后端连接成功 status = ok"。
**注意:** Android 模拟器里 `127.0.0.1` 指模拟器自身,要用 `--dart-define=API_BASE=http://10.0.2.2:8000/api/v1`(真机用电脑局域网 IP)—— 这是 M2 的事,先记下。

- [ ] **Step 6:提交**

```bash
cd "D:\pycharmproject\chat_app" && git add app && git commit -m "feat: dio api client + health handshake page (M0)"
```

---

### Task 6: 开通腾讯云 IM(用户动手,控制台操作)

**Files:**
- Modify: `chatapp/.env`(追加 IM_SDKAPPID、IM_SECRETKEY)
- Modify: `chatapp/.env.example`(同步占位)

**Interfaces:**
- Consumes: 无代码。
- Produces: `.env` 里可用的 `IM_SDKAPPID`(公开,App 端也要用)与 `IM_SECRETKEY`(只存后端)。M1 的 userSig 签发、account_import、灰条消息全依赖这两个值。

- [ ] **Step 1:注册/登录腾讯云并开通 IM**

浏览器打开 https://console.cloud.tencent.com/im  → 微信扫码/QQ 注册登录 → 「创建应用」,名称随意(如"chatapp-dev")→ 进入应用 → 左侧「基本信息」:记录 **SDKAppID**(数字)。

- [ ] **Step 2:拿到密钥**

「基本信息」页点「密钥」旁的复制(没显示则先「显示密钥」+ 短信/邮箱验证)→ 得到 32 位 **IM_SECRETKEY**。密钥等同密码,只进 `.env`,不入 git。

- [ ] **Step 3:写入 .env 与 .env.example**

`chatapp/.env` 追加:

```env
IM_SDKAPPID=<你的数字 SDKAppID>
IM_SECRETKEY=<你的 32 位密钥>
```

`chatapp/.env.example` 追加(占位):

```env
IM_SDKAPPID=CHANGE_ME
IM_SECRETKEY=CHANGE_ME
```

- [ ] **Step 4:控制台冒烟验证**

IM 控制台左侧「开发辅助工具」→「UserSig 生成」:选本应用、随便填一个 userId(如 `u1`),点生成 → 得到一串 userSig 即证明账号开通成功。
M1 开始后,后端会用同样的密钥自行签发;届时 App 端的 IM SDKAppID 用 `--dart-define=IM_SDKAPPID=<数字>` 传入。

- [ ] **Step 5:提交 .env.example 更新**

```bash
cd "D:\pycharmproject\chat_app" && git add chatapp/.env.example && git commit -m "chore: document IM env vars (M0)"
```

---

## M0 验收清单(全部通过即进入 M1 计划)

- [ ] `cd chatapp && python manage.py check` 无问题;`manage.py migrate` 已跑过
- [ ] `python manage.py test` 全绿(accounts 3 个用例)
- [ ] `curl http://127.0.0.1:8000/api/v1/health` 返回 `{"status":"ok"}`
- [ ] `cd app && ../flutter/bin/flutter.bat analyze` 零告警
- [ ] `flutter test` 全绿(2 个用例)
- [ ] App 页面显示"后端连接成功"(桌面/Chrome 任一路径验证过)
- [ ] 腾讯云 IM 应用已建,`.env` 里 IM_SDKAPPID/IM_SECRETKEY 已填,控制台能生成 userSig
- [ ] `git log --oneline` 至少 6 条 M0 提交,`git status` 干净(仅剩 chatapp/.env 被忽略属正常)

## 遗留事项(留给 M1/M2 计划,不需要现在做)

- Riverpod/go_router/Repository 分层(M1 引入业务页时再做,避免空架构)
- IM SDKAppID 传参封装(app 侧 --dart-define 约定,M1 定)
- Android SDK/真机工具链检查(M2 联调前)
- iOS 打包(M4 决策)
