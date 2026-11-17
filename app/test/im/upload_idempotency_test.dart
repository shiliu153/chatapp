import 'dart:math';

import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/api_exception.dart';
import 'package:chatapp_app/im/upload_idempotency.dart';

/// 服务端白名单(见 `docs/api/conventions.md`「幂等键」):1–128 个字母 / 数字 / `. _ : -`。
final _keyPattern = RegExp(r'^[A-Za-z0-9._:-]{1,128}$');

void main() {
  group('newUploadIdempotencyKey', () {
    test('落在服务端字符白名单内且以 app- 开头', () {
      for (var i = 0; i < 50; i++) {
        final key = newUploadIdempotencyKey();
        expect(key, matches(_keyPattern), reason: '生成的 key 会被服务端 400 拒掉:$key');
        expect(key.startsWith('app-'), isTrue);
      }
    });

    test('同一微秒内连发也不撞(序号兜底)', () {
      // 固定时钟 + 固定随机源 → 只有进程内序号能区分,这是 Windows / 模拟器上
      // `DateTime.now()` 分辨率很粗时最容易踩的那条
      final now = DateTime.fromMicrosecondsSinceEpoch(1758000000123456);
      final random = Random(7);
      final keys = {
        for (var i = 0; i < 100; i++)
          newUploadIdempotencyKey(now: () => now, random: random),
      };
      expect(keys.length, 100);
    });
  });

  group('UploadKeyCache', () {
    test('同一次上传的所有调用复用一个 key,换来源才换 key', () {
      final keys = UploadKeyCache();
      final first = keys.keyFor('im/images', '/tmp/a.jpg');
      expect(keys.keyFor('im/images', '/tmp/a.jpg'), first);
      expect(first, matches(_keyPattern));

      // 换一张图 = 换了一个临时路径 → 新 key
      final second = keys.keyFor('im/images', '/tmp/b.jpg');
      expect(second, isNot(first));

      // 同一个来源换到另一个接口上:各自记一条(服务端也按接口区分作用域)
      final voice = keys.keyFor('im/voices', '/tmp/a.jpg');
      expect(voice, isNot(first));
      expect(keys.length, 3);
    });

    test('LRU:命中即续命,溢出淘汰最久没用的那条', () {
      final keys = UploadKeyCache(maxEntries: 2);
      final a = keys.keyFor('im/images', 'a');
      final b = keys.keyFor('im/images', 'b');
      expect(keys.length, 2);

      // 再摸一次 a → 被淘汰的应该是 b 而不是 a
      expect(keys.keyFor('im/images', 'a'), a);
      keys.keyFor('im/images', 'c');
      expect(keys.length, 2);
      expect(keys.keyFor('im/images', 'a'), a);
      expect(keys.keyFor('im/images', 'b'), isNot(b), reason: 'b 已被淘汰,应换新 key');
      expect(keys.keyFor('im/images', 'c'), isNot(a));
    });
  });

  group('UploadRetry.delayFor', () {
    const backoff = Duration(milliseconds: 500);
    final retry = UploadRetry();

    Duration? delay(ApiException error) => retry.delayFor(error, backoff);

    test('断网 / 超时(没有 HTTP 状态码)按退避值重试', () {
      expect(delay(ApiException('网络不给力,请检查网络后重试')), backoff);
    });

    test('429 按 Retry-After 等;没给就用退避值,超长要封顶', () {
      expect(delay(ApiException('太频繁', statusCode: 429, code: 42901)), backoff);
      expect(
          delay(ApiException('太频繁',
              statusCode: 429, code: 42901, retryAfter: const Duration(seconds: 2))),
          const Duration(seconds: 2));
      // 每日额度那种「Retry-After 到次日 0 点」不该把上传卡在那儿
      expect(
          delay(ApiException('太频繁',
              statusCode: 429, code: 42901, retryAfter: const Duration(hours: 3))),
          retry.maxDelay);
    });

    test('409 + 40901 可重试,等待 1–2 秒(契约口径)', () {
      final conflict = ApiException('上一次上传还在处理,请勿重复提交',
          statusCode: 409, code: idempotencyConflictCode);
      final wait = delay(conflict);
      expect(wait, isNotNull);
      expect(wait!, greaterThanOrEqualTo(const Duration(seconds: 1)));
      expect(wait, lessThanOrEqualTo(const Duration(seconds: 2)));
    });

    test('5xx 退避重试', () {
      expect(delay(ApiException('服务暂时不可用', statusCode: 503, code: 50302)), backoff);
      expect(delay(ApiException('服务出错', statusCode: 500)), backoff);
    });

    test('400 / 413 / 401 / 403 / 404 以及非 40901 的 409 立刻冒泡', () {
      expect(delay(ApiException('图片只支持 JPG/PNG/WebP', statusCode: 400)), isNull);
      expect(delay(ApiException('存储空间不够了', statusCode: 413, code: 41301)), isNull);
      expect(delay(ApiException('登录已过期', statusCode: 401)), isNull);
      expect(delay(ApiException('账号被封禁', statusCode: 403)), isNull);
      expect(delay(ApiException('资源不存在', statusCode: 404)), isNull);
      expect(delay(ApiException('冲突', statusCode: 409, code: 409)), isNull);
    });
  });

  group('UploadRetry.run', () {
    test('值得重试的错误退避后重试,每次拿到的都是同一个 key', () async {
      final sleeps = <Duration>[];
      final seenKeys = <String>[];
      final retry = UploadRetry(sleep: (delay) async => sleeps.add(delay));
      var calls = 0;

      final result = await retry.run('k-1', (key) async {
        seenKeys.add(key);
        calls++;
        if (calls < 3) throw ApiException('服务暂时不可用', statusCode: 503);
        return 'ok';
      });

      expect(result, 'ok');
      expect(calls, 3);
      expect(seenKeys, ['k-1', 'k-1', 'k-1']);
      expect(sleeps, [const Duration(milliseconds: 500), const Duration(seconds: 1)]);
    });

    test('退避翻倍且封顶', () async {
      final sleeps = <Duration>[];
      final retry = UploadRetry(
        attempts: 5,
        sleep: (delay) async => sleeps.add(delay),
      );
      await expectLater(
        retry.run('k', (key) async => throw ApiException('挂了', statusCode: 500)),
        throwsA(isA<ApiException>()),
      );
      // 4 次重试的等待是 500 / 1000 / 2000 / 4000(顶到 maxDelay)
      expect(sleeps, [
        const Duration(milliseconds: 500),
        const Duration(seconds: 1),
        const Duration(seconds: 2),
        const Duration(seconds: 4),
      ]);
    });

    test('不可重试的错误一次就冒泡,不发第二次请求', () async {
      final sleeps = <Duration>[];
      final retry = UploadRetry(sleep: (delay) async => sleeps.add(delay));
      var calls = 0;

      await expectLater(
        retry.run('k', (key) async {
          calls++;
          throw ApiException('只能上传 JPG/PNG/WebP', statusCode: 400);
        }),
        throwsA(isA<ApiException>()
            .having((e) => e.message, 'message', '只能上传 JPG/PNG/WebP')
            .having((e) => e.statusCode, 'statusCode', 400)),
      );
      expect(calls, 1);
      expect(sleeps, isEmpty);
    });

    test('重试用尽后抛出最后一次的错误', () async {
      final retry = UploadRetry(sleep: (delay) async {});
      var calls = 0;
      await expectLater(
        retry.run('k', (key) async {
          calls++;
          throw ApiException('第 $calls 次失败', statusCode: 502);
        }),
        throwsA(isA<ApiException>().having((e) => e.message, 'message', '第 3 次失败')),
      );
      expect(calls, 3);
    });
  });
}
