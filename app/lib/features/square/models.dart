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
  });

  final int id;
  final FeedAuthor author;
  final String text;
  final List<String> images;
  final int likeCount;
  final int commentCount;
  final bool likedByMe;
  final DateTime createdAt;

  factory Post.fromJson(Map<String, dynamic> json) => Post(
        id: json['id'] as int,
        author: FeedAuthor.fromJson(json['author'] as Map<String, dynamic>),
        text: json['text'] as String? ?? '',
        images: (json['images'] as List<dynamic>? ?? []).cast<String>(),
        likeCount: json['like_count'] as int? ?? 0,
        commentCount: json['comment_count'] as int? ?? 0,
        likedByMe: json['liked_by_me'] as bool? ?? false,
        createdAt: DateTime.parse(json['created_at'] as String),
      );

  Post copyWith({int? likeCount, bool? likedByMe}) => Post(
        id: id,
        author: author,
        text: text,
        images: images,
        likeCount: likeCount ?? this.likeCount,
        commentCount: commentCount,
        likedByMe: likedByMe ?? this.likedByMe,
        createdAt: createdAt,
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
