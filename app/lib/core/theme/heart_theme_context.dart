/// 过渡 shim:「心跳」期的文件名与 import 路径保留给存量页面,实现已合并到
/// `ember_theme_context.dart`(`context.heart` 是 `context.ember` 的别名)。
///
/// E-5 逐页迁移把 `context.heart` 换成 `context.ember` 之后,本文件与那条 import
/// 一起删除。
library;

export 'ember_theme_context.dart';
