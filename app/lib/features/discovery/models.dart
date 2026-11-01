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
