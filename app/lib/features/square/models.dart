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
  });

  final int id;
  final FeedAuthor author;
  final String text;
  final DateTime createdAt;

  factory PostCommentItem.fromJson(Map<String, dynamic> json) => PostCommentItem(
        id: json['id'] as int,
        author: FeedAuthor.fromJson(json['author'] as Map<String, dynamic>),
        text: json['text'] as String,
        createdAt: DateTime.parse(json['created_at'] as String),
      );
}
