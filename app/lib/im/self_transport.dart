import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:web_socket_channel/io.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../core/client_header.dart';
import '../core/pinned_tls.dart';

/// 自建 IM 的 WebSocket 传输抽象:测试注入假实现。
abstract class SelfTransport {
  Stream<String> get frames;
  Future<void> connect(Uri uri);
  void send(String frame);
  Future<void> close();
}

class WebSocketTransport implements SelfTransport {
  final _frames = StreamController<String>.broadcast();
  WebSocketChannel? _channel;

  @override
  Stream<String> get frames => _frames.stream;

  @override
  Future<void> connect(Uri uri) async {
    // 证书绑定同时覆盖 WSS:自定义 HttpClient 只信任内置根证书
    final pinned = PinnedTls.wsClient();
    final channel = pinned == null
        ? WebSocketChannel.connect(uri)
        : IOWebSocketChannel.connect(uri, customClient: pinned);
    await channel.ready;
    _channel = channel;
    channel.stream.listen(
      (data) => _frames.add(data as String),
      onError: _frames.addError,
      onDone: _frames.close,
    );
  }

  @override
  void send(String frame) => _channel?.sink.add(frame);

  @override
  Future<void> close() async {
    await _channel?.sink.close();
    await _frames.close();
  }
}

/// 自建 IM 的 HTTP 抽象(历史/会话列表),与 WS 共用 IM token。
abstract class SelfHttpClient {
  Future<Map<String, dynamic>> get(String path, Map<String, String> query);
}

class DioSelfHttpClient implements SelfHttpClient {
  DioSelfHttpClient(String baseUrl, String token)
      : _dio = Dio(BaseOptions(
          baseUrl: baseUrl,
          headers: {'Authorization': 'Bearer $token'},
          connectTimeout: const Duration(seconds: 5),
          receiveTimeout: const Duration(seconds: 5),
        ))
          ..httpClientAdapter = PinnedTls.adapter()
          // 与业务请求同口径:IM 的 HTTP 调用也走 App 端身份(批次 K / K-4)
          ..interceptors.add(const ClientHeaderInterceptor());

  final Dio _dio;

  /// 测试用:换掉底层适配器,以便断言真正发出的请求头。
  @visibleForTesting
  Dio get dio => _dio;

  @override
  Future<Map<String, dynamic>> get(String path, Map<String, String> query) async {
    final response = await _dio.get<Map<String, dynamic>>(path, queryParameters: query);
    return response.data ?? const {};
  }
}
