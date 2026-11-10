class FeedAuthor {
  const FeedAuthor({required this.userId, required this.nickname, this.avatarUrl});

  final int userId;
  final String nickname;
  final String? avatarUrl;

  factory FeedAuthor.fromJson(Map<String, dynamic> json) => FeedAuthor(
        userId: json['user_id'] as int,
        nickname: json['nickname'] as String? ?? '',
        avatarUrl: json['avatar_url'] as String?,
      );
}

class Post {
  const Post({
    required this.id,
    required this.author,
    required this.text,
    required this.images,
    required this.likeCount,
    required this.commentCount,
    required this.likedByMe,
    required this.createdAt,
    this.isFavorited = false,
  });

  final int id;
  final FeedAuthor author;
  final String text;
  final List<String> images;
  final int likeCount;
  final int commentCount;
  final bool likedByMe;
  final DateTime createdAt;

  /// 我是否收藏了这条动态(`is_favorited`)。**只读服务端**,不在本地持久化。
  final bool isFavorited;

  factory Post.fromJson(Map<String, dynamic> json) => Post(
        id: json['id'] as int,
        author: FeedAuthor.fromJson(json['author'] as Map<String, dynamic>),
        text: json['text'] as String? ?? '',
        images: (json['images'] as List<dynamic>? ?? []).cast<String>(),
        likeCount: json['like_count'] as int? ?? 0,
        commentCount: json['comment_count'] as int? ?? 0,
        likedByMe: json['liked_by_me'] as bool? ?? false,
        isFavorited: json['is_favorited'] as bool? ?? false,
        createdAt: DateTime.parse(json['created_at'] as String),
      );

  Post copyWith({int? likeCount, bool? likedByMe, bool? isFavorited}) => Post(
        id: id,
        author: author,
        text: text,
        images: images,
        likeCount: likeCount ?? this.likeCount,
        commentCount: commentCount,
        likedByMe: likedByMe ?? this.likedByMe,
        isFavorited: isFavorited ?? this.isFavorited,
        createdAt: createdAt,
      );
}

/// 「谁点了赞」里的一行(`GET /posts/{id}/likes` 的 `PostLiker` 契约组件)。
///
/// 字段名跟契约走,别改名:`user_id` / `nickname` / `avatar_url` / `liked_at`。
class PostLikeUser {
  const PostLikeUser({
    required this.userId,
    required this.nickname,
    required this.likedAt,
    this.avatarUrl,
  });

  final int userId;
  final String nickname;

  /// 无已过审照片时为 null(契约里 `avatar_url` 可空)。
  final String? avatarUrl;
  final DateTime likedAt;

  factory PostLikeUser.fromJson(Map<String, dynamic> json) => PostLikeUser(
        userId: json['user_id'] as int,
        nickname: json['nickname'] as String? ?? '',
        avatarUrl: json['avatar_url'] as String?,
        likedAt: DateTime.parse(json['liked_at'] as String),
      );
}

class PostCommentItem {
  const PostCommentItem({
    required this.id,
    required this.author,
    required this.text,
    required this.createdAt,
    this.parentId,
    this.replyTo,
    this.replyCount = 0,
    this.replies = const [],
  });

  final int id;
  final FeedAuthor author;
  final String text;
  final DateTime createdAt;

  /// 顶级评论为 null;回复为所属顶级评论的 id。
  final int? parentId;

  /// 被回复者;顶级评论为 null。
  final FeedAuthor? replyTo;

  /// 该楼层的可见回复总数(回复对象恒为 0)。
  final int replyCount;

  /// 内嵌的前两条回复(回复对象恒为空)。
  final List<PostCommentItem> replies;

  factory PostCommentItem.fromJson(Map<String, dynamic> json) => PostCommentItem(
        id: json['id'] as int,
        author: FeedAuthor.fromJson(json['author'] as Map<String, dynamic>),
        text: json['text'] as String,
        createdAt: DateTime.parse(json['created_at'] as String),
        parentId: json['parent_id'] as int?,
        replyTo: json['reply_to'] == null
            ? null
            : FeedAuthor.fromJson(json['reply_to'] as Map<String, dynamic>),
        replyCount: json['reply_count'] as int? ?? 0,
        replies: (json['replies'] as List<dynamic>? ?? [])
            .map((item) => PostCommentItem.fromJson(item as Map<String, dynamic>))
            .toList(),
      );
}
