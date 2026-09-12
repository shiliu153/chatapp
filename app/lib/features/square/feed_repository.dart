import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import 'models.dart';

class FeedRepository {
  FeedRepository(this._api);

  final ApiClient _api;

  Future<({List<Post> items, bool hasMore})> fetchPosts(
      {int limit = 20, int offset = 0, String path = '/posts'}) async {
    final page = await _api.get(path, query: {'limit': limit, 'offset': offset})
        as Map<String, dynamic>;
    final items = (page['results'] as List<dynamic>)
        .map((item) => Post.fromJson(item as Map<String, dynamic>))
        .toList();
    return (items: items, hasMore: page['next'] != null);
  }

  Future<void> toggleLike(int postId, {required bool like}) async {
    if (like) {
      await _api.post('/posts/$postId/like');
    } else {
      await _api.delete('/posts/$postId/like');
    }
  }

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
}

final feedRepositoryProvider = Provider<FeedRepository>(
    (ref) => FeedRepository(ref.watch(apiClientProvider)));
