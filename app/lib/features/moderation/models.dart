// 他人资料卡与黑名单的数据模型;字段与后端 GET /users/{id}、GET /blocks 一一对应。
import '../profile/models.dart';

class UserProfile {
  const UserProfile({
    required this.userId,
    required this.nickname,
    required this.gender,
    required this.age,
    required this.city,
    required this.bio,
    required this.tags,
    required this.photos,
  });

  factory UserProfile.fromJson(Map<String, dynamic> json) => UserProfile(
        userId: json['user_id'] as int,
        nickname: (json['nickname'] ?? '') as String,
        gender: json['gender'] as String?,
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
  final String? gender;
  final int? age;
  final String city;
  final String bio;
  final List<Tag> tags;
  final List<Photo> photos;
}

class BlockedUser {
  const BlockedUser({required this.userId, required this.nickname, this.avatarUrl, this.blockedAt});

  factory BlockedUser.fromJson(Map<String, dynamic> json) => BlockedUser(
        userId: json['user_id'] as int,
        nickname: (json['nickname'] ?? '') as String,
        avatarUrl: json['avatar_url'] as String?,
        blockedAt:
            json['blocked_at'] == null ? null : DateTime.tryParse(json['blocked_at'] as String),
      );

  final int userId;
  final String nickname;
  final String? avatarUrl;
  final DateTime? blockedAt;
}
