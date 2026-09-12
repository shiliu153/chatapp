// 资料相关的数据模型;字段与后端 GET /users/me 的响应一一对应。

class Tag {
  const Tag({required this.id, required this.name, this.icon = ''});

  factory Tag.fromJson(Map<String, dynamic> json) => Tag(
        id: json['id'] as int,
        name: json['name'] as String,
        icon: (json['icon'] ?? '') as String,
      );

  final int id;
  final String name;
  final String icon;
}

class Photo {
  const Photo({required this.id, required this.url, required this.status});

  factory Photo.fromJson(Map<String, dynamic> json) => Photo(
        id: json['id'] as int,
        url: json['url'] as String,
        status: json['status'] as String,
      );

  final int id;
  final String url;
  final String status;

  bool get isApproved => status == 'approved';
}

class Preference {
  const Preference({this.targetGender, this.ageMin = 18, this.ageMax = 99, this.city = ''});

  factory Preference.fromJson(Map<String, dynamic>? json) => json == null
      ? const Preference()
      : Preference(
          targetGender: json['target_gender'] as String?,
          ageMin: json['age_min'] as int,
          ageMax: json['age_max'] as int,
          city: (json['city'] ?? '') as String,
        );

  final String? targetGender;
  final int ageMin;
  final int ageMax;
  final String city;
}

class Profile {
  const Profile({
    required this.id,
    required this.userId,
    required this.nickname,
    required this.gender,
    required this.birthday,
    required this.age,
    required this.city,
    required this.bio,
    required this.status,
    required this.missingFields,
    required this.tags,
    required this.photos,
    required this.preference,
    this.banReason = '',
  });

  factory Profile.fromJson(Map<String, dynamic> json) => Profile(
        id: json['id'] as int,
        userId: json['user_id'] as int,
        nickname: (json['nickname'] ?? '') as String,
        gender: json['gender'] as String?,
        birthday: json['birthday'] as String?,
        age: json['age'] as int?,
        city: (json['city'] ?? '') as String,
        bio: (json['bio'] ?? '') as String,
        status: json['status'] as String,
        banReason: (json['ban_reason'] ?? '') as String,
        missingFields:
            ((json['missing_fields'] ?? const []) as List<dynamic>).cast<String>(),
        tags: ((json['tags'] ?? const []) as List<dynamic>)
            .map((item) => Tag.fromJson(item as Map<String, dynamic>))
            .toList(),
        photos: ((json['photos'] ?? const []) as List<dynamic>)
            .map((item) => Photo.fromJson(item as Map<String, dynamic>))
            .toList(),
        preference: Preference.fromJson(json['preference'] as Map<String, dynamic>?),
      );

  /// profile 表主键(仅内部用;对外标识一律 userId)
  final int id;

  /// 账号 ID,与公开资料卡 user_id 同源
  final int userId;
  final String nickname;
  final String? gender;
  final String? birthday;
  final int? age;
  final String city;
  final String bio;
  final String status;
  final String banReason;
  final List<String> missingFields;
  final List<Tag> tags;
  final List<Photo> photos;
  final Preference preference;

  bool get isComplete => missingFields.isEmpty;

  Photo? get avatar {
    for (final photo in photos) {
      if (photo.isApproved) return photo;
    }
    return null;
  }
}

String missingFieldLabel(String field) => const {
      'nickname': '昵称',
      'gender': '性别',
      'birthday': '生日',
      'city': '城市',
      'bio': '简介',
      'photos': '照片',
    }[field] ??
    field;

bool isAtLeast18(DateTime birthday, {DateTime? today}) {
  final now = today ?? DateTime.now();
  var age = now.year - birthday.year;
  if (now.month < birthday.month || (now.month == birthday.month && now.day < birthday.day)) {
    age -= 1;
  }
  return age >= 18;
}
