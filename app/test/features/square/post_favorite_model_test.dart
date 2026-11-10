import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/square/models.dart';

import '../../support/sample_data.dart';

/// 契约映射:`is_favorited` 与 `PostLiker` 的字段名照 `docs/api/feed.md` §5.16–§5.19。
///
/// App 的 `fromJson` 是**容错**写法(`?? false` / `?? ''`),后端改名不会崩、
/// 只会静默变空值 —— 所以这里对「字段名本身」做断言,而不是只看能不能解析。
void main() {
  test('Post.fromJson:is_favorited 为 true / false / 缺失三种情况', () {
    expect(Post.fromJson(postJson(isFavorited: true)).isFavorited, isTrue);
    expect(Post.fromJson(postJson(isFavorited: false)).isFavorited, isFalse);

    // 老响应(字段还没上线)不该让整条动态解析失败
    final legacy = postJson()..remove('is_favorited');
    expect(Post.fromJson(legacy).isFavorited, isFalse);
  });

  test('Post.copyWith 只改收藏标记,其余字段原样保留', () {
    final post = Post.fromJson(postJson(
        id: 5, nickname: 'Alice', text: '原文', likeCount: 3, likedByMe: true));

    final favorited = post.copyWith(isFavorited: true);
    expect(favorited.isFavorited, isTrue);
    expect(favorited.id, 5);
    expect(favorited.text, '原文');
    expect(favorited.likeCount, 3);
    expect(favorited.likedByMe, isTrue);

    // 不传就是不覆盖(收藏态不会被点赞更新顺手清掉)
    expect(favorited.copyWith(likeCount: 4).isFavorited, isTrue);
  });

  test('PostLikeUser.fromJson:四个契约字段(user_id/nickname/avatar_url/liked_at)', () {
    final user = PostLikeUser.fromJson(postLikerJson(
        userId: 12, nickname: '小雨12', avatarUrl: 'http://test/a.png'));

    expect(user.userId, 12);
    expect(user.nickname, '小雨12');
    expect(user.avatarUrl, 'http://test/a.png');
    expect(user.likedAt, DateTime.parse('2026-11-10T14:02:11+08:00'));

    // 无已过审照片时后端给 null
    expect(PostLikeUser.fromJson(postLikerJson(avatarUrl: null)).avatarUrl, isNull);
  });
}
