/// 后端地址;运行时用 --dart-define=API_BASE=... 覆盖。
/// 模拟器里宿主机回环是 http://10.0.2.2:8000/api/v1。
const String apiBase = String.fromEnvironment('API_BASE',
    defaultValue: 'http://127.0.0.1:8000/api/v1');

/// 极光 AppKey;Android 原生以 `key.properties` 注入的 manifest placeholder 为准,
/// 这里给 Dart 侧 `setup()` 用,两处填同一个值。
const String jpushAppKey = String.fromEnvironment('JPUSH_APP_KEY');
