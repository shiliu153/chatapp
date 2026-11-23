/// spec §8.3 里那些**组件级尺寸**:token 只覆盖到字体 / 间距 / 圆角 / 控件高度 /
/// 图标档,剩下这些(角标最小 18、头像档位、在线点直径、sheet 拖把……)还没有
/// `design/tokens/scale.json` 的对应项。
///
/// 为什么集中放一处:散进 9 个组件各写一个裸数字,下次改口径就要翻 9 个文件,
/// 而且「哪些数是规范给的、哪些是随手编的」就分不清了。集中之后:
/// 1. 每个值都标了它来自规范哪一句,评审可以逐格对照;
/// 2. 补 token(flow 栈)时只改这里一处,组件不用动。
///
/// 已记入 PR「遗留」的 token 缺口:角标 min 18 / dot 8、头像六档 28–96、
/// 在线点 11 与 8、sheet 拖把 36×4、空态插画 72–96、按压缩放 .97/.98。
abstract final class EmberComponentSizes {
  /// 角标最小边长(spec §8.3「min 18×18」)。
  static const badgeMin = 18.0;

  /// 纯圆点角标的直径(spec §8.3 未给,取角标最小边的一半,视觉上与数字角标等高)。
  static const badgeDot = 8.0;

  /// 角标左右内边距(spec §8.3 未给;数字角标要能容下两位数字)。
  static const badgePadding = 4.0;

  /// 头像尺寸档(spec §8.2「尺寸 28/32/40/48/56/96」)。
  static const avatarXs = 28.0;

  /// 头像 32 档。
  static const avatarSm = 32.0;

  /// 头像 40 档(列表默认)。
  static const avatarMd = 40.0;

  /// 头像 48 档。
  static const avatarLg = 48.0;

  /// 头像 56 档。
  static const avatarXl = 56.0;

  /// 头像 96 档(资料页大头像)。
  static const avatarHero = 96.0;

  /// 在线点直径,常规场景(spec §8.3「直径 11(小场景 8)」)。
  static const onlineDot = 11.0;

  /// 在线点直径,小场景(32 及以下头像)。
  static const onlineDotSmall = 8.0;

  /// 在线点外描边宽度(§8.3「2px 背景色描边」)。
  static const onlineDotStroke = 2.0;

  /// 「新配对」头像环宽度(spec §8.3「`emberGlow` 环 2.5px」)。
  static const newMatchRing = 2.5;

  /// 底部弹层拖把宽度(spec §8.3「顶部拖把 36×4」)。
  static const sheetHandleWidth = 36.0;

  /// 底部弹层拖把高度。
  static const sheetHandleHeight = 4.0;

  /// 可点卡片按压缩放(spec §8.3「pressed: scale .98」)。
  static const cardPressedScale = 0.98;

  /// 空态插画下沿(spec §8.3「插画 72–96」)。
  static const illustrationMin = 72.0;

  /// 空态插画上沿。
  static const illustrationMax = 96.0;

  /// Toast 距底栏上方的距离(spec §8.3「底栏上方 12」)。
  static const toastBottomInset = 12.0;

  /// 悬浮底栏高度 + 底距(spec §8.2「高 64,左右外距 12、底距 10」的常数部分;
  /// 高度本身用 token `size.nav.height`)。
  static const navBottomInset = 10.0;

  /// Toast 淡入时的上移距离(spec §8.2「淡入 + 上移 8」)。
  static const toastRise = 8.0;

  /// Toast 自动消失时长(spec §8.2「2s 自动消失」)。
  static const toastDurationMs = 2000;

  /// 输入框聚焦时的外扩光晕宽度(spec §8.3「2px 外扩 `brand.default` @12%」)。
  static const fieldFocusHalo = 2.0;
}
