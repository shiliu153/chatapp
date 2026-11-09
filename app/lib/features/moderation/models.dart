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
    this.isFollowed = false,
    this.followerCount = 0,
    this.followingCount = 0,
    this.voice,
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
        // 批次 I 的关注态:老版本后端没有这三个字段时按「未关注 / 0」兜底
        isFollowed: (json['is_followed'] ?? false) as bool,
        followerCount: (json['follower_count'] ?? 0) as int,
        followingCount: (json['following_count'] ?? 0) as int,
        // 批次 R:语音自我介绍是公开信息,没录过为 null
        voice: VoiceIntro.parse(json['voice']),
      );

  final int userId;
  final String nickname;
  final String? gender;
  final int? age;
  final String city;
  final String bio;
  final List<Tag> tags;
  final List<Photo> photos;

  /// 当前用户是否已关注对方(关注按钮的初始态)。
  final bool isFollowed;

  /// 对方的粉丝数(多少人关注了对方)。
  final int followerCount;

  /// 对方的关注数(对方关注了多少人)。
  final int followingCount;

  /// 对方的语音自我介绍;没录过为 null(整块播放条不渲染)。
  final VoiceIntro? voice;

  /// 乐观更新关注态:只改关注相关的两个字段,其余原样保留。
  UserProfile copyWith({bool? isFollowed, int? followerCount}) => UserProfile(
        userId: userId,
        nickname: nickname,
        gender: gender,
        age: age,
        city: city,
        bio: bio,
        tags: tags,
        photos: photos,
        isFollowed: isFollowed ?? this.isFollowed,
        followerCount: followerCount ?? this.followerCount,
        followingCount: followingCount,
        voice: voice,
      );
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
