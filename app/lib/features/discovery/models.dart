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
