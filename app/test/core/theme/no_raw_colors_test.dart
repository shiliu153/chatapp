import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// 「禁用裸色值」硬门禁(F-2 / spec §2.1「防回退」)。
///
/// 为什么必须有它:暗色模式的价值全靠「所有页面都走 token」。迁移完 301 处之后,
/// 下一个人写新页面时随手写个 `AppColors.text1` 或 `Color(0xFF333333)`,
/// 编译器不会报错、浅色下也看不出问题 —— 只有这条测试会红。
///
/// 扫描范围与白名单(与计划 F-2 一致):
/// - `lib/features/**` 与 `lib/core/**`,**排除 `lib/core/theme/`**(那里就是色值本身);
/// - 禁止 `AppColors.`(浅色静态值,不随主题变);
/// - 禁止 `Color(0x…)` 裸 hex,白 / 黑 / 全透明三个例外(照片遮罩、纯黑背景等
///   在两种主题下语义相同,且没有对应的语义 token);
/// - 附加:禁止直接引用 `AppGradients.heart` / `.system` / `.heartSweep` 三个
///   浅色常量渐变(暗色下 heartOrange 要提亮),必须走 `heartOf` / `systemOf` /
///   `heartSweepOf`。
void main() {
  /// 允许的裸色值:白、黑、全透明。写成完整 8 位 hex 精确匹配。
  const allowedHex = {'0xFFFFFFFF', '0xFF000000', '0x00000000'};

  /// 主题目录本身是色值的唯一事实来源,不参与扫描。
  bool isThemeDir(String path) =>
      path.replaceAll('\\', '/').contains('lib/core/theme/');

  List<File> sources(String root) {
    final dir = Directory(root);
    if (!dir.existsSync()) return const [];
    return dir
        .listSync(recursive: true)
        .whereType<File>()
        .where((f) => f.path.endsWith('.dart'))
        .where((f) => !isThemeDir(f.path))
        .toList();
  }

  final files = [...sources('lib/features'), ...sources('lib/core')];

  test('扫描范围非空(防止路径写错导致空跑通过)', () {
    expect(files.length, greaterThan(50), reason: '扫到的文件太少,检查 root 路径');
  });

  test('lib/features 与 lib/core(除 theme)不得出现 AppColors.', () {
    final hits = <String>[];
    for (final f in files) {
      final lines = f.readAsLinesSync();
      for (var i = 0; i < lines.length; i++) {
        if (lines[i].contains('AppColors.')) {
          hits.add('${f.path}:${i + 1}: ${lines[i].trim()}');
        }
      }
    }
    expect(
      hits,
      isEmpty,
      reason: '取色请用 context.heart(见 core/theme/heart_theme_context.dart):\n'
          '${hits.join('\n')}',
    );
  });

  test('lib/features 与 lib/core(除 theme)不得出现裸 hex Color(0x…)(白/黑/透明除外)', () {
    final hexRe = RegExp(r'Color\((0x[0-9A-Fa-f]{8})\)');
    final hits = <String>[];
    for (final f in files) {
      final lines = f.readAsLinesSync();
      for (var i = 0; i < lines.length; i++) {
        for (final m in hexRe.allMatches(lines[i])) {
          if (allowedHex.contains(m.group(1))) continue;
          hits.add('${f.path}:${i + 1}: ${lines[i].trim()}');
        }
      }
    }
    expect(
      hits,
      isEmpty,
      reason: '裸色值请先加进 HeartColors(浅/深两套),再走 context.heart:\n'
          '${hits.join('\n')}',
    );
  });

  test('不得直接引用浅色常量渐变(AppGradients.heart / .system / .heartSweep)', () {
    final gradRe = RegExp(r'AppGradients\.(heart|system|heartSweep)(?!Of|Sweep)\b');
    final hits = <String>[];
    for (final f in files) {
      final lines = f.readAsLinesSync();
      for (var i = 0; i < lines.length; i++) {
        if (gradRe.hasMatch(lines[i])) {
          hits.add('${f.path}:${i + 1}: ${lines[i].trim()}');
        }
      }
    }
    expect(
      hits,
      isEmpty,
      reason: '渐变要跟着暗色走,请用 AppGradients.heartOf(context.heart) 等:\n'
          '${hits.join('\n')}',
    );
  });
}
