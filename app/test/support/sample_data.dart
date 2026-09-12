/// 造一份 GET /users/me 的响应;各字段可覆盖。
/// id 是 profile 表主键,userId 是账号 ID——真实后端里两者不相等,
/// 要测 ID 行显示就传 userId。
Map<String, dynamic> profileJson({
  int id = 7,
  int? userId,
  String nickname = '小明',
  String? gender = 'male',
  String? birthday = '2000-01-01',
  String city = '上海',
  String bio = '你好',
  List<String> missing = const [],
  List<Map<String, dynamic>> tags = const [],
  List<Map<String, dynamic>> photos = const [],
  Map<String, dynamic>? preference,
  String? status,
  String banReason = '',
}) =>
    {
      'id': id,
      'user_id': userId ?? id,
      'phone': '13800138000',
      'nickname': nickname,
      'gender': gender,
      'birthday': birthday,
      'age': birthday == null ? null : 26,
      'city': city,
      'bio': bio,
      'status': status ?? (missing.isEmpty ? 'complete' : 'incomplete'),
      'ban_reason': banReason,
      'missing_fields': missing,
      'tags': tags,
      'photos': photos,
      'preference': preference ??
          {'target_gender': null, 'age_min': 18, 'age_max': 99, 'city': ''},
    };

Map<String, dynamic> tagJson(int id, String name, {String icon = ''}) =>
    {'id': id, 'name': name, 'icon': icon};

Map<String, dynamic> photoJson(int id, {bool approved = true, int order = 0}) => {
      'id': id,
      'url': 'http://test/media/photos/$id.png',
      'status': approved ? 'approved' : 'pending',
      'order': order,
    };

/// 造一份 GET /discovery/candidates 里的候选;字段可覆盖。
Map<String, dynamic> candidateJson({
  int userId = 9,
  String nickname = '小红',
  int? age = 25,
  String city = '上海',
  String bio = '喜欢爬山',
  List<Map<String, dynamic>> tags = const [],
  List<Map<String, dynamic>>? photos,
}) =>
    {
      'user_id': userId,
      'nickname': nickname,
      'age': age,
      'city': city,
      'bio': bio,
      'tags': tags,
      'photos': photos ?? [photoJson(userId * 100)],
    };

/// 造一份 GET /matches 里的配对;字段可覆盖。
Map<String, dynamic> matchJson({
  int userId = 9,
  String? imUserId,
  String nickname = '小红',
  String? avatarUrl = 'http://test/media/photos/900.png',
}) =>
    {
      'user_id': userId,
      'im_user_id': imUserId ?? 'u$userId',
      'nickname': nickname,
      'avatar_url': avatarUrl,
      'matched_at': '2026-09-10T12:00:00+08:00',
    };

/// 造一份 GET /users/{id} 的公开资料;字段可覆盖。
Map<String, dynamic> publicProfileJson({
  int userId = 9,
  String nickname = '小红',
  String? gender = 'female',
  int? age = 25,
  String city = '上海',
  String bio = '喜欢爬山',
  List<Map<String, dynamic>> tags = const [],
  List<Map<String, dynamic>>? photos,
}) =>
    {
      'user_id': userId,
      'nickname': nickname,
      'gender': gender,
      'age': age,
      'city': city,
      'bio': bio,
      'tags': tags,
      'photos': photos ?? [photoJson(userId * 100)],
    };

/// 造一份 GET /blocks 里的一条。
Map<String, dynamic> blockedUserJson({
  int userId = 9,
  String nickname = '小红',
  String? avatarUrl,
}) =>
    {
      'user_id': userId,
      'nickname': nickname,
      'avatar_url': avatarUrl,
      'blocked_at': '2026-09-11T12:00:00+08:00',
    };

/// 造一份 LimitOffset 分页响应;hasNext=true 时给一个非空 next(测跟页用)。
Map<String, dynamic> pageJson(List<dynamic> items, {bool hasNext = false}) => {
      'count': items.length,
      'next': hasNext ? 'http://test/api/v1/next' : null,
      'previous': null,
      'results': items,
    };
