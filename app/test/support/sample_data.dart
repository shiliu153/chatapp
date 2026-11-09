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
  bool visitsHidden = false,
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
      'visits_hidden': visitsHidden,
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
  bool isFollowed = false,
  int followerCount = 0,
  int followingCount = 0,
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
      // 批次 I 的关注态;老后端没有这三个字段,App 侧按「未关注 / 0」兜底
      'is_followed': isFollowed,
      'follower_count': followerCount,
      'following_count': followingCount,
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

/// 造一条站内通知(GET /notifications 里的一条);字段可覆盖。
Map<String, dynamic> notificationJson({
  int id = 1,
  String kind = 'post_like',
  String text = '小明 赞了你的动态',
  bool isRead = false,
  String createdAt = '2026-11-06T12:30:00+08:00',
  int? actorId = 7,
  String actorNickname = '小明',
  String? actorAvatar,
  String targetKind = 'post',
  int? targetId = 9,
}) =>
    {
      'id': id,
      'kind': kind,
      'text': text,
      'is_read': isRead,
      'created_at': createdAt,
      'actor': actorId == null
          ? null
          : {'id': actorId, 'nickname': actorNickname, 'avatar': actorAvatar},
      'target': {'kind': targetKind, 'id': targetId},
    };

/// 造一份 LimitOffset 分页响应;hasNext=true 时给一个非空 next(测跟页用)。
Map<String, dynamic> pageJson(List<dynamic> items, {bool hasNext = false}) => {
      'count': items.length,
      'next': hasNext ? 'http://test/api/v1/next' : null,
      'previous': null,
      'results': items,
    };

/// 造一份游标分页响应(动态流 / 配对 / 喜欢我 / 访客用);
/// hasMore=true 时给一个非空 next_cursor(测「加载更多」用)。
Map<String, dynamic> cursorPageJson(
  List<dynamic> items, {
  bool hasMore = false,
  int? count,
  String cursor = 'cursor-next-page',
}) =>
    {
      'count': count ?? items.length,
      'next_cursor': hasMore ? cursor : null,
      'has_more': hasMore,
      'results': items,
    };

/// 造一条动态(GET /posts 里的一条);字段可覆盖。
Map<String, dynamic> postJson({
  int id = 1,
  int authorId = 9,
  String nickname = 'Alice',
  String? avatarUrl,
  String text = '你好',
  List<String> images = const [],
  int likeCount = 0,
  int commentCount = 0,
  bool likedByMe = false,
  String createdAt = '2026-09-12T20:00:00+08:00',
}) =>
    {
      'id': id,
      'author': {'user_id': authorId, 'nickname': nickname, 'avatar_url': avatarUrl},
      'text': text,
      'images': images,
      'like_count': likeCount,
      'comment_count': commentCount,
      'liked_by_me': likedByMe,
      'created_at': createdAt,
    };

/// 造一条评论/回复;字段可覆盖。
Map<String, dynamic> commentJson({
  int id = 1,
  int authorId = 9,
  String nickname = 'Bob',
  String text = '评论',
  String createdAt = '2026-09-12T20:00:00+08:00',
  int? parentId,
  Map<String, dynamic>? replyTo,
  int replyCount = 0,
  List<Map<String, dynamic>> replies = const [],
}) =>
    {
      'id': id,
      'author': {'user_id': authorId, 'nickname': nickname, 'avatar_url': null},
      'text': text,
      'created_at': createdAt,
      'parent_id': parentId,
      'reply_to': replyTo,
      'reply_count': replyCount,
      'replies': replies,
    };

/// 造一个「被回复者」摘要(评论对象里的 `reply_to`)。
Map<String, dynamic> replyToJson({int userId = 7, String nickname = '阿哲'}) =>
    {'user_id': userId, 'nickname': nickname};

/// 造一份 GET /discovery/likes 里的一条。
Map<String, dynamic> likeReceivedJson({
  int userId = 9,
  String nickname = '小红',
  int? age = 25,
  String city = '上海',
  List<Map<String, dynamic>> tags = const [],
  String likedAt = '2026-10-20T10:00:00+08:00',
}) =>
    {
      ...candidateJson(userId: userId, nickname: nickname, age: age, city: city, tags: tags),
      'liked_at': likedAt,
    };

/// 造一份 GET /discovery/visits 里的一条。
Map<String, dynamic> visitJson({
  int userId = 9,
  String nickname = '小红',
  int? age = 25,
  String city = '上海',
  List<Map<String, dynamic>> tags = const [],
  String visitedAt = '2026-11-01T12:30:00+08:00',
}) =>
    {
      ...candidateJson(userId: userId, nickname: nickname, age: age, city: city, tags: tags),
      'visited_at': visitedAt,
    };

/// 造一份 GET /devices 的 `results[]` 项(一类端一行)。
/// `lastActiveAt` 传 null = 只登录过、还没刷新过令牌(批次 M 之前的会话行)。
Map<String, dynamic> deviceJson({
  String clientType = 'app',
  String clientLabel = 'App',
  bool current = false,
  DateTime? createdAt,
  DateTime? lastActiveAt,
}) =>
    {
      'client_type': clientType,
      'client_label': clientLabel,
      'current': current,
      'created_at': (createdAt ?? DateTime(2026, 11, 9, 10, 20, 31)).toIso8601String(),
      'last_active_at': lastActiveAt?.toIso8601String(),
    };
