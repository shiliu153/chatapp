import 'package:flutter_riverpod/flutter_riverpod.dart';

/// 发现页读「现在几点」的唯一入口。
///
/// 撤销窗口(30 秒)与额度冷却(429 的 `Retry-After`)都跟墙上时钟有关:直接调
/// `DateTime.now()` 的控制器在测试里推不动时间(踩坑手册「时间来源要可注入」)。
/// 测试 override 成一个可控的假时钟即可。
final discoveryClockProvider = Provider<DateTime Function()>((ref) => DateTime.now);
