/// 后端地址;运行时用 --dart-define=API_BASE=... 覆盖。
/// 模拟器里宿主机回环是 http://10.0.2.2:8000/api/v1。
const String apiBase = String.fromEnvironment('API_BASE',
    defaultValue: 'http://127.0.0.1:8000/api/v1');
