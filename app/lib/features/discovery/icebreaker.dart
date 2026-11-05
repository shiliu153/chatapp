/// 配对那一刻的破冰文案(纯客户端模板)。
///
/// 计划 §2.2 的收敛口径:共同点**只在配对那一刻**展示 —— 聊天页不提示,也不为了提示
/// 去拉 `GET /users/{id}`(那会把这次查看记成一次访客访问,语义污染)。
///
/// 文案规则(改文案 = 发版,个人项目可接受):
///   1. 有共同标签 → 「你们都喜欢 X、Y,不如从这儿聊起?」(最多列 2 个);
///   2. 没有共同标签 → 「你们都在 {城市}」,**仅当双方城市都非空且相同**;
///   3. 两条都不满足 → 返回 `null`,调用方整行不展示(不提性别,避免刻板印象)。
library;

/// 有共同标签时的文案前缀与后缀。
const _sharedPrefix = '你们都喜欢 ';
const _sharedSuffix = ',不如从这儿聊起?';

/// 无共同标签、同城时的文案模板(`{city}` 由调用方替换)。
const sameCityTemplate = '你们都在 {city}';

/// 最多列出几个共同标签(超出部分不展示,避免一行挤爆)。
const maxIcebreakerTags = 2;

/// 生成配对破冰文案。
///
/// Args:
///   sharedTagNames: 共同标签的名字列表(顺序即展示顺序,来自后端 `shared_tags`)。
///   myCity: 我的城市;空字符串表示未填。
///   peerCity: 对方的城市;空字符串表示未填。
///
/// Returns:
///   可直接渲染的一行文案;没有可说的内容时返回 `null`。
String? matchIcebreaker({
  required List<String> sharedTagNames,
  String myCity = '',
  String peerCity = '',
}) {
  final names = sharedTagNames
      .map((name) => name.trim())
      .where((name) => name.isNotEmpty)
      .take(maxIcebreakerTags)
      .toList();
  if (names.isNotEmpty) {
    return '$_sharedPrefix${names.join('、')}$_sharedSuffix';
  }
  final city = peerCity.trim();
  // 只提「双方都在这座城市」—— 单方面知道对方城市时不能替用户断言,更不展示性别。
  if (city.isEmpty || city != myCity.trim()) return null;
  return sameCityTemplate.replaceFirst('{city}', city);
}
