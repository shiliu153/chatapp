import 'models.dart';

/// 广场 → 动态详情的跨页载荷:经 go_router 的 `extra` 传入。
///
/// [seed] 让详情页在 provider 未加载时用列表快照直出真卡 —— Hero 只在 push 后
/// 下一帧末扫描一次,目标首帧必须有带相同 tag 的 Hero 才会飞。
///
/// 两种 Hero 二选一(E-5.5 page spec §1 第 9 条 + 批次⑤整卡转场):
/// - [heroTag]:整卡 Hero(无图动态),卡 → 详情整卡;
/// - [imageHeroTag]:图片 Hero(有图动态),卡图片 → 详情图片(§9.3 沉浸内容)。
///
/// 两者都只能给一个 —— Hero 不得嵌套(SDK 硬断言),调用方按「有没有图」决定。
/// 深链 / 我的动态 / 收藏进详情时两个都不给,详情页从头加载骨架。
class PostDetailArgs {
  /// 构造载荷。
  const PostDetailArgs({
    required this.seed,
    this.heroTag,
    this.imageHeroTag,
    this.focusComment = false,
  });

  /// 列表快照(详情未加载时直出真卡)。
  final Post seed;

  /// 整卡 Hero tag;null = 无整卡飞行。
  final String? heroTag;

  /// 图片 Hero tag;null = 无图片飞行。
  final String? imageHeroTag;

  /// 是否在进入后把焦点落进评论输入框(点「评论钮」进来的语义,page spec §4)。
  final bool focusComment;
}
