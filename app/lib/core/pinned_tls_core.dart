import 'dart:convert';
import 'dart:io';

/// 证书绑定的纯 Dart 部分:把若干张根证书 PEM 变成只信它们的 `SecurityContext`。
///
/// 单独拆出来是为了让 `tool/verify_pinning.dart` 能用 `dart run` 直接跑
/// (它不能 import Flutter 的 `services.dart`,那里没有资源加载能力)。
///
/// 关联文档:
/// - 设计:docs/superpowers/specs/2026-10-28-token-hardening-design.md
SecurityContext buildPinnedContext(Iterable<String> pems) {
  final context = SecurityContext(withTrustedRoots: false);
  var count = 0;
  for (final pem in pems) {
    context.setTrustedCertificatesBytes(utf8.encode(pem));
    count++;
  }
  if (count == 0) {
    throw StateError('没有可用的根证书:证书绑定会拒绝所有连接');
  }
  return context;
}
