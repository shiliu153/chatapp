// 「我的数据」页面用到的数据模型;字段与后端 `GET /api/v1/stats/me` 的响应一一对应
// (契约见 `docs/api/stats.md`)。

/// 统计周期:周 / 月 / 年。
///
/// [query] 是接口的 `period` 参数值(只允许这三个),`label` 是分段控件上的中文。
/// 顺序即控件的显示顺序,默认取第一个([StatsPeriod.week])。
enum StatsPeriod {
  week('week', '周'),
  month('month', '月'),
  year('year', '年');

  const StatsPeriod(this.query, this.label);

  /// 接口参数值(`week` / `month` / `year`)。
  final String query;

  /// 控件上的中文标签。
  final String label;
}

/// 一个自然周期内的七项数字。
///
/// 口径是「区间内发生的事件」而不是存量(契约 §1.1):配对数含事后已解除的、
/// 访客数是「来看过我的人」(一人一行,不重复计点击)。本页只负责展示,
/// 不做任何二次计算 —— 数字算错的地方都在服务端,一眼能对上。
class StatsReport {
  const StatsReport({
    required this.period,
    required this.start,
    required this.end,
    required this.matches,
    required this.likesGiven,
    required this.likesReceived,
    required this.visits,
    required this.posts,
    required this.postLikes,
    required this.newFollowers,
  });

  /// 宽松解析:七个计数缺字段时按 0 处理。「0」本来就是合法展示(新用户各项都是 0),
  /// 不能因为一个字段缺失就整页报错;日期缺字段则退化成空串,区间行自然不显示内容。
  factory StatsReport.fromJson(Map<String, dynamic> json) => StatsReport(
        period: (json['period'] ?? '') as String,
        start: (json['start'] ?? '') as String,
        end: (json['end'] ?? '') as String,
        matches: _count(json['matches']),
        likesGiven: _count(json['likes_given']),
        likesReceived: _count(json['likes_received']),
        visits: _count(json['visits']),
        posts: _count(json['posts']),
        postLikes: _count(json['post_likes']),
        newFollowers: _count(json['new_followers']),
      );

  /// 实际生效的周期,由服务端回显(缺省时是 `week`)。
  final String period;

  /// 区间起始日期(含),`YYYY-MM-DD`。
  final String start;

  /// 区间结束日期(含),`YYYY-MM-DD`。
  final String end;

  /// 区间内新产生的配对(我参与的,含事后已解除的)。
  final int matches;

  /// 区间内我发出的「喜欢」数。
  final int likesGiven;

  /// 区间内别人给我的「喜欢」数。
  final int likesReceived;

  /// 区间内看过我资料的人数(一人一行,按最近访问时间)。
  final int visits;

  /// 区间内我发布的动态数。
  final int posts;

  /// 区间内我的动态收到的赞数。
  final int postLikes;

  /// 区间内新增的关注我的人数。
  final int newFollowers;

  static int _count(Object? value) => value is int ? value : 0;
}
