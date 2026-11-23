import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// 「禁止裸值 / 禁止绕过主题」硬门禁(E-2 起扩面)。
///
/// 为什么必须有它:整套设计语言的价值全靠「所有取色都走 token」。E-2 之后色值的
/// 唯一事实来源是 `design/tokens/*.json` → `app/lib/core/theme/tokens.g.dart`,
/// 于是防回退的判据变成下面四条 —— 编译器都不会报错,只有这条测试会红:
///
/// 1. 裸 hex:任何 `Color(0x…)` 字面量(白 / 黑 / 全透明例外:它们在两种主题下
///    语义相同,且没有对应的语义 token);
/// 2. 绕过主题:直接取 `EmberColors.light` / `EmberColors.dark`(只该在
///    `lib/core/theme/` 里出现),页面必须走 `context.ember`;
/// 3. 心跳期常量:`AppColors.` / `AppGradients.heart` 这类浅色静态值;
/// 4. 新组件层(`lib/core/ui/`)不得反向依赖心跳期尺度常量(`AppSpacing` /
///    `AppText` / `AppRadius` / `AppMotion`)——它是 Ember 的地基,一旦回退到旧
///    常量,「改一个值要改两处」的老问题就会从组件层重新长出来。
///
/// 扫描范围:`lib/features/**` + `lib/core/**`,**排除 `lib/core/theme/`**
/// (那里就是色值与 token 本身)。
void main() {
  /// 允许的裸色值:白、黑、全透明。写成完整 8 位 hex 精确匹配。
  const allowedHex = {'0xFFFFFFFF', '0xFF000000', '0x00000000'};

  bool isThemeDir(String path) =>
      path.replaceAll('\\', '/').contains('lib/core/theme/');

  bool isUiDir(String path) =>
      path.replaceAll('\\', '/').contains('lib/core/ui/');

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

  /// 按行扫描并收集命中;`pattern` 命中即算违规(除非在白名单里)。
  List<String> scan(RegExp pattern, {bool Function(String line)? allow}) {
    final hits = <String>[];
    for (final f in files) {
      final lines = f.readAsLinesSync();
      for (var i = 0; i < lines.length; i++) {
        // 只看代码部分:注释里出现规则名(比如讲解禁令本身)不算违规。
        final code = lines[i].split('//').first;
        if (!pattern.hasMatch(code)) continue;
        if (allow != null && allow(code)) continue;
        hits.add('${f.path}:${i + 1}: ${lines[i].trim()}');
      }
    }
    return hits;
  }

  test('扫描范围非空(防止路径写错导致空跑通过)', () {
    expect(files.length, greaterThan(50), reason: '扫到的文件太少,检查 root 路径');
    expect(files.any((f) => isUiDir(f.path)), isTrue, reason: '组件层没被扫到');
  });

  test('不得出现裸 hex Color(0x…)(白/黑/透明除外)', () {
    final hits = <String>[];
    final hexRe = RegExp(r'Color\((0x[0-9A-Fa-f]{8})\)');
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
      reason: '裸色值请加进 design/tokens/*.json 再重跑生成器:\n${hits.join('\n')}',
    );
  });

  test('不得绕过主题直接取 EmberColors.light / .dark(必须走 context.ember)', () {
    final hits = scan(RegExp(r'EmberColors\.(light|dark)\b'));
    expect(
      hits,
      isEmpty,
      reason: '页面要么走 context.ember,要么把整块渲染留给 core/ui:\n${hits.join('\n')}',
    );
  });

  test('不得出现心跳期静态色板 AppColors. / 浅色常量渐变', () {
    final hits = scan(RegExp(r'AppColors\.|AppGradients\.(heart|system|heartSweep)\b'));
    expect(
      hits,
      isEmpty,
      reason: '心跳期常量已删除;取色走 context.ember:\n${hits.join('\n')}',
    );
  });

  test('组件层 core/ui 不得依赖心跳期尺度常量', () {
    final hits = <String>[];
    final legacyRe = RegExp(r'\b(AppSpacing|AppText|AppRadius|AppMotion)\.');
    for (final f in files.where((f) => isUiDir(f.path))) {
      final lines = f.readAsLinesSync();
      for (var i = 0; i < lines.length; i++) {
        if (!legacyRe.hasMatch(lines[i])) continue;
        hits.add('${f.path}:${i + 1}: ${lines[i].trim()}');
      }
    }
    expect(
      hits,
      isEmpty,
      reason: '组件层请直接用 tokens.g.dart 的常量:\n${hits.join('\n')}',
    );
  });
}
