import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/api_client.dart';
import 'package:chatapp_app/core/api_exception.dart';
import 'package:chatapp_app/im/self_image_uploader.dart';
import 'package:chatapp_app/im/upload_idempotency.dart';

import '../support/scripted_adapter.dart';

/// `POST /im/images` 的 201 响应(字段与 `docs/api/im.md` §6.2 一致)。
Map<String, dynamic> imageJson({int id = 7}) => {
      'id': id,
      'url': 'http://test/media/chat/a.jpg',
      'thumb_url': 'http://test/media/chat/a_thumb.jpg',
      'width': 1080,
      'height': 1920,
      'size': 123456,
    };

void main() {
  late ScriptedAdapter adapter;
  late Dio dio;
  late Directory tempDir;
  late List<Duration> sleeps;

  /// 依次返回队列里的响应;队列用完后沿用最后一条。
  void queue(String route, List<Future<ResponseBody> Function(RequestOptions)> responses) {
    var index = 0;
    adapter.routes[route] = (options) {
      final responder = responses[index < responses.length ? index : responses.length - 1];
      index++;
      return responder(options);
    };
  }

  ApiImageUploader uploader() => ApiImageUploader(
        ApiClient(dio),
        retry: UploadRetry(sleep: (delay) async => sleeps.add(delay)),
      );

  /// 请求头里带的幂等键,按发出顺序。
  List<String?> sentKeys() =>
      adapter.log.map((options) => options.headers[idempotencyKeyHeader] as String?).toList();

  setUp(() async {
    adapter = ScriptedAdapter({});
    dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    tempDir = await Directory.systemTemp.createTemp('app_image_upload');
    sleeps = <Duration>[];
  });

  tearDown(() async {
    await tempDir.delete(recursive: true);
  });

  Future<String> writeImage(String name) async {
    final file = File('${tempDir.path}/$name');
    await file.writeAsBytes([1, 2, 3, 4]);
    return file.path;
  }

  test('上传成功:带一个合法幂等键,响应解析成 ChatImageUpload', () async {
    queue('POST /im/images', [(options) async => ok(imageJson(), status: 201)]);
    final result = await uploader().upload(await writeImage('a.jpg'));

    expect(result.id, 7);
    expect(result.thumbUrl, 'http://test/media/chat/a_thumb.jpg');
    final key = sentKeys().single;
    expect(key, isNotNull);
    expect(key, matches(RegExp(r'^[A-Za-z0-9._:-]{1,128}$')));
    // multipart 真的带上了文件(重试时 FormData 必须重建,否则会是空文件)
    final form = adapter.log.single.data as FormData;
    expect(form.files.single.key, 'file');
    expect(form.files.single.value.filename, 'a.jpg');
  });

  // 回归(#499):文件名只能取 basename,而且**不能**依赖当前平台的分隔符。
  // Windows 上 `Platform.pathSeparator` 是 `\`,而临时目录 / 部分插件给的路径用 `/` 拼,
  // 按平台分隔符切会切不动,整条路径被当成文件名发给服务端。
  group('文件名只取 basename,两种分隔符都要取到', () {
    for (final separator in ['/', '\\']) {
      test('路径用 `$separator` 分隔', () async {
        queue('POST /im/images', [(options) async => ok(imageJson(), status: 201)]);
        final path = '${tempDir.path}${separator}a.jpg';
        // 把这条路径原样物化成真实文件,让断言与平台无关:POSIX 上反斜杠是合法的文件名
        // 字符(文件直接落在 tempDir 的父目录里,不需要建子目录),Windows 上它就是分隔符。
        final file = File(path);
        addTearDown(() async {
          if (await file.exists()) await file.delete();
        });
        await file.writeAsBytes([1, 2, 3, 4]);

        await uploader().upload(path);

        final form = adapter.log.single.data as FormData;
        expect(form.files.single.value.filename, 'a.jpg',
            reason: '文件名里不该带任何目录,更不能变成整条本地路径');
      });
    }
  });

  test('断网重试:所有重试复用同一个 key,第三次成功', () async {
    queue('POST /im/images', [
      offline,
      offline,
      (options) async => ok(imageJson(), status: 201),
    ]);
    final result = await uploader().upload(await writeImage('a.jpg'));

    expect(result.id, 7);
    final keys = sentKeys();
    expect(keys.length, 3);
    expect(keys.toSet().length, 1, reason: '同一次上传的重试必须复用同一个 key');
    expect(sleeps, [const Duration(milliseconds: 500), const Duration(seconds: 1)]);
  });

  test('409 + 40901 当可重试:退避 1–2 秒后用同一个 key 再打一次', () async {
    queue('POST /im/images', [
      (options) => jsonErrorWithHeaders(409,
          code: idempotencyConflictCode, message: '上一次上传还在处理,请勿重复提交'),
      (options) async => ok(imageJson(), status: 201),
    ]);
    final result = await uploader().upload(await writeImage('a.jpg'));

    expect(result.id, 7);
    final keys = sentKeys();
    expect(keys.length, 2);
    expect(keys.toSet().length, 1, reason: '40901 之后必须用同一个 key 再打,换 key 就变成两次上传');
    expect(sleeps.single, greaterThanOrEqualTo(const Duration(seconds: 1)));
    expect(sleeps.single, lessThanOrEqualTo(const Duration(seconds: 2)));
  });

  test('换一张图才换 key:同一路径复用旧 key', () async {
    queue('POST /im/images', [(options) async => ok(imageJson(), status: 201)]);
    final upload = uploader();
    final first = await writeImage('a.jpg');
    final second = await writeImage('b.jpg');

    await upload.upload(first);
    await upload.upload(second);
    await upload.upload(first); // 重发同一张图(WS 帧没送达的场景)

    final keys = sentKeys();
    expect(keys[1], isNot(keys[0]), reason: '换图要换新 key');
    expect(keys[2], keys[0], reason: '同一张图重发应复用旧 key,服务端才不会多存一份');
  });

  test('400 立刻冒泡:不重试', () async {
    queue('POST /im/images', [
      (options) => jsonError(400, '图片只支持 JPG/PNG/WebP'),
      (options) async => ok(imageJson(), status: 201),
    ]);
    await expectLater(
      uploader().upload(await writeImage('a.txt')),
      throwsA(isA<ApiException>()
          .having((error) => error.message, 'message', '图片只支持 JPG/PNG/WebP')
          .having((error) => error.statusCode, 'statusCode', 400)),
    );
    expect(adapter.log.length, 1);
    expect(sleeps, isEmpty);
  });

  test('413 配额满立刻冒泡:不重试', () async {
    queue('POST /im/images', [
      (options) => jsonErrorWithHeaders(413, code: 41301, message: '存储空间不够了,先删点旧内容'),
    ]);
    await expectLater(
      uploader().upload(await writeImage('a.jpg')),
      throwsA(isA<ApiException>()
          .having((error) => error.code, 'code', 41301)
          .having((error) => error.message, 'message', '存储空间不够了,先删点旧内容')),
    );
    expect(adapter.log.length, 1);
    expect(sleeps, isEmpty);
  });
}
