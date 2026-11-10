import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import 'models.dart';

class FeedRepository {
  FeedRepository(this._api);

  final ApiClient _api;

  /// 广场动态流(游标分页):首页不传 [cursor],之后传上一页的 `nextCursor`。
  ///
  /// 后端已改成复合游标(backlog D-1):`?before=<游标>`,响应带 `next_cursor`。
  /// 不再用 offset —— 动态流头部会持续插入新行,offset 翻页会重复/漏读。
  Future<({List<Post> items, String? nextCursor})> fetchPosts(
      {int limit = 20, String? cursor, String path = '/posts'}) async {
    final page = await _api.get(path, query: {
      'limit': limit,
      'before': ?cursor,
    }) as Map<String, dynamic>;
    final items = (page['results'] as List<dynamic>)
        .map((item) => Post.fromJson(item as Map<String, dynamic>))
        .toList();
    return (items: items, nextCursor: page['next_cursor'] as String?);
  }

  Future<void> toggleLike(int postId, {required bool like}) async {
    if (like) {
      await _api.post('/posts/$postId/like');
    } else {
      await _api.delete('/posts/$postId/like');
    }
  }

  /// 「谁点了赞」(游标分页,按点赞时间倒序)。
  ///
  /// `count` 是**过滤后**的可见人数,不是动态上的 `like_count`;因此这里不读它,
  /// 列表就是唯一口径(没人点赞时 `items` 为空,不是错误)。
  Future<({List<PostLikeUser> items, String? nextCursor})> fetchLikes(int postId,
      {int limit = 30, String? cursor}) async {
    final page = await _api.get('/posts/$postId/likes', query: {
      'limit': limit,
      'before': ?cursor,
    }) as Map<String, dynamic>;
    final items = (page['results'] as List<dynamic>)
        .map((item) => PostLikeUser.fromJson(item as Map<String, dynamic>))
        .toList();
    return (items: items, nextCursor: page['next_cursor'] as String?);
  }

  /// 收藏 / 取消收藏:两个方法都**恒 204**(幂等),所以调用方只做乐观翻转。
  Future<void> setFavorite(int postId, {required bool favorite}) async {
    if (favorite) {
      await _api.post('/posts/$postId/favorite');
    } else {
      await _api.delete('/posts/$postId/favorite');
    }
  }

  /// 我的收藏:响应形状与广场动态流逐字段一致,只是排序按**收藏时间**倒序
  /// (游标落在收藏行上,由后端保证),所以直接复用 [fetchPosts] 的解析。
  Future<({List<Post> items, String? nextCursor})> fetchFavorites(
          {int limit = 20, String? cursor}) =>
      fetchPosts(path: '/feed/favorites', limit: limit, cursor: cursor);

  /// 关注某人(幂等 204;重复关注不会报错)。
  Future<void> follow(int userId) async => _api.post('/users/$userId/follow');

  /// 取消关注(幂等 204;没关注过也返回成功)。
  Future<void> unfollow(int userId) async => _api.delete('/users/$userId/follow');

  Future<Post> createPost({
    required String text,
    required List<({Uint8List bytes, String name})> images,
  }) async {
    final data = await _api.post('/posts', data: FormData.fromMap({
      'text': text,
      'images': [
        for (final image in images)
          MultipartFile.fromBytes(image.bytes, filename: image.name),
      ],
    }));
    return Post.fromJson(data as Map<String, dynamic>);
  }

  Future<Post> fetchPost(int id) async =>
      Post.fromJson(await _api.get('/posts/$id') as Map<String, dynamic>);

  Future<({List<PostCommentItem> items, bool hasMore})> fetchComments(
      int postId, {int limit = 100, int offset = 0}) async {
    final page = await _api.get('/posts/$postId/comments',
        query: {'limit': limit, 'offset': offset}) as Map<String, dynamic>;
    final items = (page['results'] as List<dynamic>)
        .map((item) => PostCommentItem.fromJson(item as Map<String, dynamic>))
        .toList();
    return (items: items, hasMore: page['next'] != null);
  }

  Future<void> addComment(int postId, String text, {int? parentId}) async {
    await _api.post('/posts/$postId/comments', data: {
      'text': text,
      'parent_id': ?parentId,
    });
  }

  Future<({List<PostCommentItem> items, bool hasMore})> fetchReplies(
      int postId, int commentId, {int limit = 100, int offset = 0}) async {
    final page = await _api.get('/posts/$postId/comments/$commentId/replies',
        query: {'limit': limit, 'offset': offset}) as Map<String, dynamic>;
    final items = (page['results'] as List<dynamic>)
        .map((item) => PostCommentItem.fromJson(item as Map<String, dynamic>))
        .toList();
    return (items: items, hasMore: page['next'] != null);
  }

  Future<void> deleteComment(int postId, int commentId) async {
    await _api.delete('/posts/$postId/comments/$commentId');
  }

  Future<void> deletePost(int id) async {
    await _api.delete('/posts/$id');
  }

  Future<void> reportPost(int postId, {required String type, String detail = ''}) async {
    await _api.post('/posts/$postId/report', data: {'type': type, 'detail': detail});
  }
}

final feedRepositoryProvider = Provider<FeedRepository>(
    (ref) => FeedRepository(ref.watch(apiClientProvider)));
