/// 造一份 GET /users/me 的响应;各字段可覆盖。
Map<String, dynamic> profileJson({
  int id = 7,
  String nickname = '小明',
  String? gender = 'male',
  String? birthday = '2000-01-01',
  String city = '上海',
  String bio = '你好',
  List<String> missing = const [],
  List<Map<String, dynamic>> tags = const [],
  List<Map<String, dynamic>> photos = const [],
  Map<String, dynamic>? preference,
}) =>
    {
      'id': id,
      'phone': '13800138000',
      'nickname': nickname,
      'gender': gender,
      'birthday': birthday,
      'age': birthday == null ? null : 26,
      'city': city,
      'bio': bio,
      'status': missing.isEmpty ? 'complete' : 'incomplete',
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
