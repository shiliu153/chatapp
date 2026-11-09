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
