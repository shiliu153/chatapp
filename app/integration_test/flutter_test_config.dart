// golden 比对的容差配置(批次 W-L3)。
//
// 这个文件会被 flutter_tools 自动发现(`test_config.dart` 从测试文件目录向上找,到
// `app/pubspec.yaml` 为止),并且**两处**都会执行:
//
//   ① 设备侧(模拟器里的 integration_test 进程)—— 这里必须**什么都不做**;
//   ② 宿主侧(`flutter_tester` 里的比对进程)—— 真正要比像素的地方。
//
// 为什么设备侧不能动:`integration_test` 在设备上装的是
// `VmServiceProxyGoldenFileComparator`(`flutter_platform.dart` 注入),它把截到的字节
// 通过 VM service 事件发给宿主。一旦在设备侧换成别的 comparator,事件根本发不出去,
// 表现是「测试卡住」或「基准文件永远不更新」。
//
// 为什么要容差:默认的 `LocalFileComparator` 是**逐像素精确**比对,同一镜像下大概率稳,
// 但一个字形抗锯齿的差异就够红一次 —— 一条会随机红的闸门比没有闸门更糟。这里放宽到
// 「差异像素 ≤ 0.1%」,真实的外观改动(颜色/间距/文案)远不止这个量级。
//
// 注意:**基准图不存在时照样报错**,不能被容差吞掉 —— 「还没生成基准」与「像素变了」
// 是两种完全不同的失败,混在一起会让人以为只是渲染抖动。

import 'dart:async';
import 'dart:io' show File, Platform;

import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';

/// 允许的差异像素占比(0.1%)。
const double kGoldenMaxDiffRatio = 0.001;

Future<void> testExecutable(FutureOr<void> Function() testMain) async {
  if (!kIsWeb && (Platform.isAndroid || Platform.isIOS)) {
    // 设备侧:保持 integration_test 装好的 VmService 代理 comparator
    await testMain();
    return;
  }
  goldenFileComparator = TolerantGoldenFileComparator(goldenFileComparator);
  await testMain();
}

/// 先精确比对,不等再按容差比对;基准缺失时仍然失败。
class TolerantGoldenFileComparator extends GoldenFileComparator {
  /// [inner] 是 flutter_tools 装的 `LocalFileComparator`(负责路径解析与落盘)。
  TolerantGoldenFileComparator(this._inner);

  final GoldenFileComparator _inner;

  @override
  Uri getTestUri(Uri key, int? version) => _inner.getTestUri(key, version);

  /// 把 golden key 解析成基准文件的绝对 URI。
  Uri _resolve(Uri golden) {
    final inner = _inner;
    if (inner is LocalFileComparator) return inner.basedir.resolveUri(golden);
    return golden;
  }

  @override
  Future<void> update(Uri golden, Uint8List imageBytes) =>
      _inner.update(golden, imageBytes);

  @override
  Future<bool> compare(Uint8List imageBytes, Uri golden) async {
    // 注意:`GoldenFileComparator.getTestUri` 在 version == null 时**原样返回 key**
    // (不拼 basedir),所以不能拿它去开文件 —— 必须自己按 LocalFileComparator.basedir
    // 解析,否则会去进程 cwd(flutter_tools 的 app/)下找,永远找不到基准。
    final File goldenFile = File.fromUri(_resolve(golden));
    if (!goldenFile.existsSync()) {
      throw FlutterError(
        '基准图不存在:${goldenFile.path}\n'
        '基准图只能在 CI 生成 —— 用 workflow_dispatch 打开 app-ui 的 update_goldens,'
        '把 artifact 里的 PNG 提交进来(本机 --update-goldens 的产物不能当基准,'
        '见 app/integration_test/golden_test.dart 文件头)。',
      );
    }

    // 直接用 SDK 的纯比对函数(不写盘),自己决定「容差内放过」还是「失败」。
    // 不调 `_inner.compare`:它一旦不等就抛 FlutterError 并把 diff 图写进 failures/,
    // 容差逻辑根本走不到。
    final ComparisonResult result = await GoldenFileComparator.compareLists(
      imageBytes,
      await goldenFile.readAsBytes(),
    );
    final double ratio = result.diffPercent;
    final String detail = result.error ?? '像素不一致';
    final bool passed = result.passed || ratio <= kGoldenMaxDiffRatio;
    result.dispose();

    if (passed) return true;

    throw FlutterError(
      'golden 不一致:${goldenFile.path}\n'
      '$detail\n'
      '差异 ${(ratio * 100).toStringAsFixed(3)}% 超过容差 '
      '${(kGoldenMaxDiffRatio * 100).toStringAsFixed(2)}%。\n'
      '外观改动是预期的 → 在 CI 用 update_goldens 重生成基准;不是预期的 → 查 diff。',
    );
  }
}
