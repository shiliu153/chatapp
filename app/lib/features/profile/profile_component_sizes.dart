/// 资料页那些**规范给了范围、token 里还没有**的尺寸(E-5.4 page spec §3 / 上游
/// §5.2 / §9.4)。
///
/// 为什么集中一处:与 `core/ui/ember_component_sizes.dart` 同一个理由 —— 这些数
/// 有的来自规范一句话(「行高 68–76」「头图可透明化」),有的是规范没覆盖、本单
/// 按现形态保留的(照片比例),散在五个文件里就分不清「哪些是规范给的、哪些是
/// 随手写的」。补 token 属于 flow 栈,本单不改 `design/tokens/*.json`。
abstract final class ProfileComponentSizes {
  /// 信息行行高:§5.2「列表行高 68–76」→ 取中值 72(字号缩放 1.3 时由内容撑开,
  /// 这里是**下限**,不是固定高)。
  static const infoRowHeight = 72.0;

  /// 照片头图比例:**规范未覆盖,保留现形态**(屏宽 × 1.15),封顶 420。
  static const headerRatio = 1.15;

  /// 照片头图封顶高度(同上,保留现形态)。
  static const headerMaxHeight = 420.0;

  /// 头图顶部 scrim 的起始透明度:透明顶栏的白图标压在浅色照片上的可读性兜底
  /// (E-5.4 page spec §2「头图滚动时可透明化」的必要条件)。
  static const topScrimAlpha = 0.45;

  /// 顶栏从「全透明」到「实底 `surface.page`」的滚动距离(§9.4 只给了「可透明化」,
  /// 没给距离;取 120 ≈ 顶栏自身高度的两倍多,滚过一行信息行就收口)。
  static const topBarFadeDistance = 120.0;

  /// 顶栏标题开始淡入的进度阈值(同上,规范未给;过半程再出标题,避免与头图叠字
  /// 撞在一起)。
  static const topBarTitleStart = 0.5;

  /// 语音介绍卡里波形条的高度(规范未覆盖,保留现形态 4)。
  static const voiceWaveHeight = 4.0;

  /// 语音播放键的直径:§8.4 触控 ≥48,图标本体可小 —— 取 48 热区里 40 的可视圆。
  static const voicePlayDiameter = 40.0;
}
