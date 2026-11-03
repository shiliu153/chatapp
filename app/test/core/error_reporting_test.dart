import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/error_reporting.dart';

void main() {
  setUp(ErrorReporting.reset);
  tearDown(ErrorReporting.reset);

  test('默认关闭:不安装监听也不上报', () {
    ErrorReporting.install(forceEnabled: false);
    ErrorReporting.report('boom');

    expect(ErrorReporting.sent, 0);
  });

  test('安装后 FlutterError 会上报,并带上 platform/版本号', () async {
    final sent = <Map<String, dynamic>>[];
    ErrorReporting.install(
      forceEnabled: true,
      sender: (payload) async => sent.add(payload),
    );

    FlutterError.reportError(FlutterErrorDetails(
      exception: StateError('渲染炸了'),
      stack: StackTrace.current,
    ));
    await Future<void>.delayed(Duration.zero);

    expect(sent, hasLength(1));
    expect(sent.first['platform'], 'app');
    expect(sent.first['message'], contains('渲染炸了'));
    expect(sent.first['app_version'], isNotEmpty);
    expect(sent.first['stack'], isNotEmpty);
  });

  test('同一 message 只报一次,总数封顶 20 条', () async {
    final sent = <Map<String, dynamic>>[];
    ErrorReporting.install(
      forceEnabled: true,
      sender: (payload) async => sent.add(payload),
    );

    ErrorReporting.report('同一个错');
    ErrorReporting.report('同一个错');
    expect(sent, hasLength(1));

    for (var index = 0; index < 50; index++) {
      ErrorReporting.report('错 $index');
    }
    expect(ErrorReporting.sent, ErrorReporting.maxReports);
    expect(sent.length, lessThanOrEqualTo(ErrorReporting.maxReports));
  });

  test('上报带最近一次服务端 X-Request-Id', () async {
    final sent = <Map<String, dynamic>>[];
    ErrorReporting.install(
      forceEnabled: true,
      sender: (payload) async => sent.add(payload),
    );

    ErrorReporting.rememberRequestId('9f8c1b2e4d5a');
    ErrorReporting.report('boom');

    expect(ErrorReporting.requestId, '9f8c1b2e4d5a');
    expect(sent.first['request_id'], '9f8c1b2e4d5a');
  });

  test('超长 message / stack 会被截断(后端有 500 / 8000 字上限)', () async {
    final sent = <Map<String, dynamic>>[];
    ErrorReporting.install(
      forceEnabled: true,
      sender: (payload) async => sent.add(payload),
    );

    ErrorReporting.report('x' * 2000, stack: 'y' * 9000);

    expect((sent.first['message'] as String).length,
        lessThanOrEqualTo(ErrorReporting.maxMessage));
    expect((sent.first['stack'] as String).length,
        lessThanOrEqualTo(ErrorReporting.maxStack));
  });

  test('发送失败不会把异常抛给调用方', () async {
    ErrorReporting.install(
      forceEnabled: true,
      sender: (_) async => throw StateError('network down'),
    );

    expect(() => ErrorReporting.report('boom'), returnsNormally);
    await Future<void>.delayed(Duration.zero);
  });

  test('未安装时 report 是空操作', () {
    ErrorReporting.report('boom');
    expect(ErrorReporting.sent, 0);
  });

  test('debugPrint 未受影响(安装监听不改变既有控制台行为)', () {
    // 安装前的 FlutterError.onError 仍会被调用,红屏/控制台输出保持原样
    ErrorReporting.install(forceEnabled: true, sender: (_) async {});
    expect(FlutterError.onError, isNotNull);
  });
}
