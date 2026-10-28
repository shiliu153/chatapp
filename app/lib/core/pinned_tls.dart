import 'dart:io';

import 'package:dio/dio.dart';
import 'package:dio/io.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import 'pinned_tls_core.dart';

/// 证书绑定:HTTPS 与 WSS 都只信任内置的根证书。
///
/// 设计要点:
/// 1. 固定的是**根证书**(ISRG Root X1 + X2),不是叶子证书 —— Let's Encrypt
///    90 天换一次证,固定叶子会让每次续期后全量 App 连不上;
/// 2. `withTrustedRoots: false` 表示只信内置这两张:用户安装的企业根、杀软根、
///    被攻陷的公共 CA 一律握手失败,中间人无法解密;
/// 3. 编译期开关 `--dart-define=CERT_PINNING=off|enforce`,默认 release 开、
///    debug 关 —— 保证 `flutter test` 与本地开发不受影响。
///
/// 关联文档:
/// - 设计:docs/superpowers/specs/2026-10-28-token-hardening-design.md
/// - 发版前验证:`dart run tool/verify_pinning.dart`
class PinnedTls {
  PinnedTls._();

  static const _roots = [
    'assets/certs/isrg-root-x1.pem',
    'assets/certs/isrg-root-x2.pem',
  ];

  /// 是否强制绑定。release 包默认开,可用 `--dart-define=CERT_PINNING=off` 关掉。
  static const bool enforced =
      bool.fromEnvironment('CERT_PINNING', defaultValue: kReleaseMode);

  static SecurityContext? _context;

  /// 读取内置根证书并构造上下文。
  ///
  /// 单独暴露出来是为了让单测能直接验证资源与证书可用性。
  @visibleForTesting
  static Future<SecurityContext> buildContext() async {
    final pems = <String>[];
    for (final asset in _roots) {
      pems.add(await rootBundle.loadString(asset));
    }
    return buildPinnedContext(pems);
  }

  /// 预热:必须在 `runApp` 之前调用(读资源是异步的,而 Dio 构造是同步的)。
  static Future<void> warmUp() async {
    if (!enforced || _context != null) return;
    _context = await buildContext();
  }

  /// 给 Dio 用的适配器;未启用绑定或未预热时退回系统默认信任链。
  static HttpClientAdapter adapter() {
    final context = _context;
    if (!enforced || context == null) return IOHttpClientAdapter();
    return IOHttpClientAdapter(createHttpClient: () => HttpClient(context: context));
  }

  /// 给 WSS 用的客户端(`IOWebSocketChannel.connect` 的 `customClient`)。
  /// 返回 `null` 表示走默认实现。
  static HttpClient? wsClient() {
    final context = _context;
    if (!enforced || context == null) return null;
    return HttpClient(context: context);
  }
}
