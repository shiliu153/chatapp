import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/format.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_avatar.dart';
import '../../core/widgets/app_empty_state.dart';
import '../../core/widgets/app_error_view.dart';
import '../../core/widgets/app_skeleton.dart';
import '../../core/widgets/app_sub_page_bar.dart';
import '../../im/im_client.dart';
import '../../im/im_manager.dart';

/// 聊天记录搜索页:输入关键词 → 300ms 防抖 → 调 IM 的 searchMessages;
/// 点结果进聊天页并按 focus 定位(见 ChatPage.focusMsgId)。
class SearchPage extends ConsumerStatefulWidget {
  const SearchPage({super.key});

  @override
  ConsumerState<SearchPage> createState() => _SearchPageState();
}

class _SearchPageState extends ConsumerState<SearchPage> {
  final _input = TextEditingController();
  Timer? _debounce;
  List<ImSearchHit> _hits = const [];
  bool _loading = false;
  bool _hasMore = false;
  String? _error;
  String _keyword = '';
  int _requestSeq = 0;

  @override
  void dispose() {
    _debounce?.cancel();
    _input.dispose();
    super.dispose();
  }

  void _onChanged(String value) {
    _debounce?.cancel();
    final keyword = value.trim();
    if (keyword.isEmpty) {
      setState(() {
        _hits = const [];
        _keyword = '';
        _error = null;
        _hasMore = false;
        _loading = false;
      });
      return;
    }
    _debounce = Timer(const Duration(milliseconds: 300), () => _run(keyword));
  }

  Future<void> _run(String keyword, {bool append = false}) async {
    final client = ref.read(imClientProvider);
    final seq = ++_requestSeq;
    setState(() {
      _loading = true;
      _error = null;
      if (!append) _keyword = keyword;
    });
    try {
      final result = await client.searchMessages(
        keyword,
        limit: 20,
        beforeId: append && _hits.isNotEmpty ? _hits.last.msgId : null,
      );
      if (!mounted || seq != _requestSeq) return; // 丢弃过期响应(防抖只挡输入,不挡慢请求)
      setState(() {
        _hits = append ? [..._hits, ...result.items] : result.items;
        _hasMore = result.hasMore;
        _loading = false;
      });
    } catch (error) {
      if (!mounted || seq != _requestSeq) return;
      setState(() {
        _error = apiMessageOf(error);
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            const AppSubPageBar(title: '搜索', backKey: Key('search.back')),
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.pageH, AppSpacing.xs, AppSpacing.pageH, AppSpacing.sm),
              child: TextField(
                key: const Key('search.input'),
                controller: _input,
                autofocus: true,
                textInputAction: TextInputAction.search,
                onChanged: _onChanged,
                onSubmitted: (value) => _run(value.trim()),
                decoration: InputDecoration(
                  hintText: '搜索聊天记录',
                  prefixIcon: const Icon(Icons.search_rounded, size: 22),
                  filled: true,
                  fillColor: AppColors.bgPage,
                  contentPadding: const EdgeInsets.symmetric(vertical: 10),
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(12),
                    borderSide: BorderSide.none,
                  ),
                ),
              ),
            ),
            Expanded(child: _body()),
          ],
        ),
      ),
    );
  }

  Widget _body() {
    if (_keyword.isEmpty) {
      return const Center(
        child: AppEmptyState(
          emoji: '🔍',
          title: '搜索聊天记录',
          description: '输入关键词,找回你们聊过的内容',
        ),
      );
    }
    if (_loading && _hits.isEmpty) {
      return ListView(
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.pageH),
        children: const [
          SizedBox(height: AppSpacing.md),
          AppSkeleton(height: 48, radius: 12),
          SizedBox(height: AppSpacing.sm),
          AppSkeleton(height: 48, radius: 12),
          SizedBox(height: AppSpacing.sm),
          AppSkeleton(height: 48, radius: 12),
        ],
      );
    }
    if (_error != null && _hits.isEmpty) {
      return AppErrorView(
        message: _error!,
        retryKey: const Key('search.retry'),
        onRetry: () => _run(_keyword),
      );
    }
    if (_hits.isEmpty) {
      return const Center(
        child: AppEmptyState(
          emoji: '🫧',
          title: '没有找到相关消息',
          description: '换个关键词试试',
        ),
      );
    }
    return Column(
      children: [
        Expanded(
          child: ListView(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.pageH),
            children: [for (final hit in _hits) _SearchHitTile(hit: hit, keyword: _keyword)],
          ),
        ),
        if (_hasMore)
          Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.sm),
            child: TextButton(
              key: const Key('search.more'),
              onPressed: _loading ? null : () => _run(_keyword, append: true),
              child: Text('加载更多', style: AppText.body.copyWith(color: AppColors.brand)),
            ),
          ),
      ],
    );
  }
}

class _SearchHitTile extends StatelessWidget {
  const _SearchHitTile({required this.hit, required this.keyword});

  final ImSearchHit hit;
  final String keyword;

  @override
  Widget build(BuildContext context) {
    final name = hit.peerName ?? hit.peerId;
    return ListTile(
      key: Key('search.hit:${hit.msgId}'),
      contentPadding: EdgeInsets.zero,
      onTap: () => context.push('/chat/${hit.peerId}?focus=${hit.msgId}'),
      leading: AppAvatar(imageUrl: hit.peerAvatar, size: 44, fallbackText: name),
      title: Text(name,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: AppText.subtitle.copyWith(color: AppColors.text1)),
      subtitle: Text.rich(
        TextSpan(children: _highlight(hit.text, keyword)),
        maxLines: 2,
        overflow: TextOverflow.ellipsis,
      ),
      trailing: Text(
        formatMessageTime(DateTime.fromMillisecondsSinceEpoch(hit.timestamp)),
        style: AppText.micro.copyWith(color: AppColors.text3),
      ),
    );
  }

  /// 把命中片段切成若干 TextSpan,命中部分主色加粗;过长时保留命中前后各 20 字。
  static List<TextSpan> _highlight(String text, String keyword) {
    final plain = AppText.body.copyWith(color: AppColors.text2);
    final marked = AppText.body
        .copyWith(color: AppColors.brand, fontWeight: FontWeight.w600);
    final lower = text.toLowerCase();
    final key = keyword.toLowerCase();
    final first = key.isEmpty ? -1 : lower.indexOf(key);
    if (first < 0) return [TextSpan(text: text, style: plain)];

    // 窗口:首次命中前 20 字 ~ 命中后 20 字
    final start = (first - 20).clamp(0, text.length);
    final windowEnd = (first + key.length + 20).clamp(0, text.length);
    final window = text.substring(start, windowEnd);
    final windowLower = lower.substring(start, windowEnd);

    final spans = <TextSpan>[];
    if (start > 0) spans.add(TextSpan(text: '…', style: plain));
    var cursor = 0;
    while (cursor < window.length) {
      final at = windowLower.indexOf(key, cursor);
      if (at < 0) {
        spans.add(TextSpan(text: window.substring(cursor), style: plain));
        break;
      }
      if (at > cursor) {
        spans.add(TextSpan(text: window.substring(cursor, at), style: plain));
      }
      spans.add(TextSpan(text: window.substring(at, at + key.length), style: marked));
      cursor = at + key.length;
    }
    if (windowEnd < text.length) spans.add(TextSpan(text: '…', style: plain));
    return spans;
  }
}
