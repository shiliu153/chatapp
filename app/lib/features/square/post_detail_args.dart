import 'models.dart';

/// 整卡 Hero 的跨页载荷(附录 D):经 go_router extra 传入。
/// [seed] 让详情页在 provider 未加载时用列表快照直出真卡 ——
/// Hero 只在 push 后下一帧末扫描一次,目标首帧必须有带相同 tag 的 Hero 才会飞。
class PostDetailArgs {
  const PostDetailArgs({required this.heroTag, required this.seed});

  final String heroTag;
  final Post seed;
}
