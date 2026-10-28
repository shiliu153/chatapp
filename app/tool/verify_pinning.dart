import 'dart:convert';
import 'dart:io';

import 'package:chatapp_app/core/pinned_tls_core.dart';

/// 发版前验证:用 App 内置的根证书对真实域名做一次握手 + 请求。
///
/// 用法(在 `app/` 下):
/// ```bash
/// dart run tool/verify_pinning.dart            # 默认 chat.shiliu153.cn
/// dart run tool/verify_pinning.dart <域名>
/// ```
///
/// 退出码 0 表示固定链可用;1 表示握手失败(证书链不符合内置根,发版会全量连不上)。
Future<void> main(List<String> args) async {
  final host = args.isNotEmpty ? args.first : 'chat.shiliu153.cn';
  final appDir = File.fromUri(Platform.script).parent.parent;
  final pems = [
    File('${appDir.path}/assets/certs/isrg-root-x1.pem').readAsStringSync(),
    File('${appDir.path}/assets/certs/isrg-root-x2.pem').readAsStringSync(),
  ];
  stdout.writeln('固定根:ISRG Root X1 + X2(${pems.length} 张)');
  stdout.writeln('目标:$host');

  final client = HttpClient(context: buildPinnedContext(pems));
  try {
    final request = await client.getUrl(Uri.https(host, '/api/v1/app/config'));
    final response = await request.close();
    final body = await response.transform(utf8.decoder).join();
    stdout.writeln('HTTP ${response.statusCode}');
    stdout.writeln(body);
    if (response.statusCode != 200) {
      stderr.writeln('响应异常:期望 200,实际 ${response.statusCode}');
      exitCode = 1;
    }
  } on HandshakeException catch (error) {
    stderr.writeln('握手失败:证书链不在固定根之内 —— $error');
    exitCode = 1;
  } finally {
    client.close(force: true);
  }
}
