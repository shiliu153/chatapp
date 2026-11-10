// 候选卡片数据;字段与后端 GET /discovery/candidates 的响应一一对应(只取 UI 用得到的)。

import '../profile/models.dart';

class Candidate {
  const Candidate({
    required this.userId,
    required this.nickname,
    required this.age,
    required this.city,
    required this.bio,
    required this.tags,
    required this.photos,
  });

  factory Candidate.fromJson(Map<String, dynamic> json) => Candidate(
        userId: json['user_id'] as int,
        nickname: (json['nickname'] ?? '') as String,
        age: json['age'] as int?,
        city: (json['city'] ?? '') as String,
        bio: (json['bio'] ?? '') as String,
        tags: ((json['tags'] ?? const []) as List<dynamic>)
            .map((item) => Tag.fromJson(item as Map<String, dynamic>))
            .toList(),
        photos: ((json['photos'] ?? const []) as List<dynamic>)
            .map((item) => Photo.fromJson(item as Map<String, dynamic>))
            .toList(),
      );

  final int userId;
  final String nickname;
  final int? age;
  final String city;
  final String bio;
  final List<Tag> tags;
  final List<Photo> photos;
}

/// 「今日精选」的响应(`GET /discovery/daily`,discovery.md §3.11,批次 S)。
///
/// **它是包装对象、不是裸数组** —— 别按 `GET /discovery/candidates` 的形状解析:
/// `{"date": "2026-11-10", "candidates": [候选卡...]}`。[date] 是服务端算种子用的
/// 日期,留给「今天已看过」这类判断用(本期只展示、不持久化)。
class DailyCandidates {
  const DailyCandidates({required this.date, required this.candidates});

  factory DailyCandidates.fromJson(Map<String, dynamic> json) => DailyCandidates(
        date: (json['date'] ?? '') as String,
        candidates: ((json['candidates'] ?? const []) as List<dynamic>)
            .map((item) => Candidate.fromJson(item as Map<String, dynamic>))
            .toList(),
      );

  /// 服务端时区下的日期(`YYYY-MM-DD`)。
  final String date;

  /// 精选卡片,字段与 `GET /discovery/candidates` 的候选卡完全一致。
  final List<Candidate> candidates;
}

/// 发现页的**临时筛选**(批次 S,discovery.md §3.1「请求参数」)。
///
/// 语义是**覆盖**而不是替换:只保存用户**真正改过**的字段,`null` / 空集合 = 该字段
/// 没动过、继续沿用「想找的人」偏好(设置页仍是偏好的唯一持久化入口)。
/// 所以「只填城市」的筛选对象里 `ageMin` / `ageMax` 必须是 `null`,请求里也就不会
/// 出现这两个参数(后端把空串当「没传」,但少发更清楚)。
class DiscoveryFilter {
  const DiscoveryFilter({this.ageMin, this.ageMax, this.city, this.tagIds = const []});

  /// 什么都没筛(默认态):请求与加筛选之前完全一致。
  static const none = DiscoveryFilter();

  /// 年龄下限(含);`null` = 沿用偏好。
  final int? ageMin;

  /// 年龄上限(含);`null` = 沿用偏好。
  final int? ageMax;

  /// 城市;`null` / 空串 = 沿用偏好。
  final String? city;

  /// 标签 ID,**命中其一即可**;空 = 不筛标签。
  final List<int> tagIds;

  /// 一个筛选参数都不用发。
  bool get isEmpty =>
      ageMin == null &&
      ageMax == null &&
      (city == null || city!.isEmpty) &&
      tagIds.isEmpty;

  /// 拼成查询参数;**空字段一个都不出现**(不是发空串)。
  Map<String, dynamic> toQuery() => {
        if (ageMin != null) 'age_min': ageMin,
        if (ageMax != null) 'age_max': ageMax,
        if (city != null && city!.isNotEmpty) 'city': city,
        if (tagIds.isNotEmpty) 'tag_ids': tagIds.join(','),
      };

  @override
  bool operator ==(Object other) =>
      other is DiscoveryFilter &&
      other.ageMin == ageMin &&
      other.ageMax == ageMax &&
      other.city == city &&
      other.tagIds.length == tagIds.length &&
      other.tagIds.every(tagIds.contains);

  @override
  int get hashCode => Object.hash(ageMin, ageMax, city, Object.hashAll(tagIds));
}

/// 每日喜欢额度快照;字段与 `GET /discovery/quota` 一一对应(discovery.md §3.10)。
///
/// `likeLimit == 0` 表示后端没开额度(`likesRemaining` 为 `null`),此时界面
/// **整块不渲染**额度文案 —— 用 [limited] 判断,不要自己拿"剩余是否 0"去推。
class LikeQuota {
  const LikeQuota({
    required this.likeLimit,
    required this.likesUsed,
    required this.likesRemaining,
  });

  factory LikeQuota.fromJson(Map<String, dynamic> json) => LikeQuota(
        likeLimit: (json['like_limit'] ?? 0) as int,
        likesUsed: (json['likes_used'] ?? 0) as int,
        likesRemaining: json['likes_remaining'] as int?,
      );

  /// 每日喜欢上限;`0` = 不限。
  final int likeLimit;

  /// 今天已用掉的喜欢次数(不限时恒为 `0`)。
  final int likesUsed;

  /// 今天还剩多少次;不限时为 `null`。
  final int? likesRemaining;

  /// 后端是否开启了每日额度。
  bool get limited => likeLimit > 0;

  /// 用掉一次喜欢;没开额度或已到 0 时原样返回。
  LikeQuota useOne() {
    final remaining = likesRemaining;
    if (!limited || remaining == null || remaining <= 0) return this;
    return LikeQuota(
      likeLimit: likeLimit,
      likesUsed: likesUsed + 1,
      likesRemaining: remaining - 1,
    );
  }
}

/// 收到的一次喜欢;字段与 GET /discovery/likes 的单项一一对应。
class LikeReceived {
  const LikeReceived({required this.candidate, required this.likedAt});

  factory LikeReceived.fromJson(Map<String, dynamic> json) => LikeReceived(
        candidate: Candidate.fromJson(json),
        likedAt: DateTime.parse(json['liked_at'] as String),
      );

  final Candidate candidate;
  final DateTime likedAt;
}

/// 一次访客记录;字段与 GET /discovery/visits 的单项一一对应。
class Visit {
  const Visit({required this.candidate, required this.visitedAt});

  factory Visit.fromJson(Map<String, dynamic> json) => Visit(
        candidate: Candidate.fromJson(json),
        visitedAt: DateTime.parse(json['visited_at'] as String),
      );

  final Candidate candidate;
  final DateTime visitedAt;
}
