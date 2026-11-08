import 'package:dio/dio.dart';

/// App 端的端类型取值(`X-Client` 头的值)。
///
/// 后端**只在签发令牌时**看这个头(`POST /auth/sms/verify`、`POST /auth/token/refresh`),
/// 决定这次会话属于哪一端;鉴权一律看令牌里的 `ct` claim。缺头按 `app` 兜底,
/// 所以本文件是「把隐式约定显式化」,不是修 bug(批次 K / K-4)。
const String appClientType = 'app';

/// 给**所有**请求统一加 `X-Client: app`。
///
/// 为什么是拦截器而不是逐处调用点手写:业务请求、multipart 上传(资料图 / 广场图 /
/// 聊天图 / 语音)、token 刷新、以及 IM 的 HTTP 调用分散在四五个文件里,逐处写必然漏
/// ——漏一处就等于该请求的端类型靠后端兜底猜。
///
/// 调用方**显式**设了同名头时不覆盖(大小写不敏感):将来联调 / 测试需要冒充 `web`
/// 端时,直接在 `Options(headers: {'X-Client': 'web'})` 里写,不必改生产代码。
class ClientHeaderInterceptor extends Interceptor {
  const ClientHeaderInterceptor();

  /// 头的规范写法;比较时按小写比对,避免 `x-client` 与 `X-Client` 被当成两个键。
  static const String headerName = 'X-Client';

  @override
  void onRequest(RequestOptions options, RequestInterceptorHandler handler) {
    final explicit = options.headers.keys
        .any((key) => key.toLowerCase() == headerName.toLowerCase());
    if (!explicit) options.headers[headerName] = appClientType;
    handler.next(options);
  }
}
