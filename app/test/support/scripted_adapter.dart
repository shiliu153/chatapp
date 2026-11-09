import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';

typedef Responder = Future<ResponseBody> Function(RequestOptions options);

/// 测试用假网络:按 `"METHOD path"` 铺响应,并记录所有请求(options.path 是相对路径,
/// 例:'POST /auth/sms/verify')。没铺的路由返回 404,方便一眼看出漏铺。
class ScriptedAdapter implements HttpClientAdapter {
  ScriptedAdapter(this.routes);

  final Map<String, Responder> routes;
  final List<RequestOptions> log = [];

  @override
  Future<ResponseBody> fetch(RequestOptions options, Stream<Uint8List>? requestStream,
      Future<void>? cancelFuture) {
    log.add(options);
    final responder = routes['${options.method} ${options.path}'];
    if (responder == null) {
      return ok({'code': 404, 'message': '测试没铺这条路由: ${options.method} ${options.path}'},
          status: 404);
    }
    return responder(options);
  }

  @override
  void close({bool force = false}) {}
}

const Map<String, List<String>> _jsonHeaders = {
  Headers.contentTypeHeader: [Headers.jsonContentType],
};

Future<ResponseBody> ok(Object body, {int status = 200}) async =>
    ResponseBody.fromString(jsonEncode(body), status, headers: _jsonHeaders);

/// 名字别叫 fail:flutter_test 自带一个 fail(),会撞名。
Future<ResponseBody> jsonError(int status, [String message = '出错了']) async =>
    ResponseBody.fromString(jsonEncode({'code': status, 'message': message}), status,
        headers: _jsonHeaders);

/// 业务码与 HTTP 状态码不一致、且要带响应头的错误(429 + `42904` + `Retry-After` 那种)。
///
/// [code] 不传时等于 [status];[headers] 里的每个键值都按单值头塞进去,
/// `content-type` 由这里统一给,别自己再带。
Future<ResponseBody> jsonErrorWithHeaders(
  int status, {
  int? code,
  String message = '出错了',
  Map<String, String> headers = const {},
}) async =>
    ResponseBody.fromString(
      jsonEncode({'code': code ?? status, 'message': message}),
      status,
      headers: {
        ..._jsonHeaders,
        for (final entry in headers.entries) entry.key: [entry.value],
      },
    );

Future<ResponseBody> offline(RequestOptions options) =>
    throw DioException.connectionError(requestOptions: options, reason: 'offline');
