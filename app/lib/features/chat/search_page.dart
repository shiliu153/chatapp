import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../core/api_exception.dart';
import '../../core/format.dart';
import '../../core/theme/ember_colors.dart';
import '../../core/theme/ember_theme_context.dart';
import '../../core/theme/tokens.g.dart' as tokens;
import '../../core/ui/ember_ui.dart';
import '../../im/im_client.dart';
import '../../im/im_manager.dart';
import 'widgets/chat_illustration.dart';

/// 聊天记录搜索页:输入关键词 → 300ms 防抖 → 调 IM 的 searchMessages;
/// 点结果进聊天页并按 focus 定位(见 ChatPage.focusMsgId)。
///
/// E-5.6d 把整页迁到 Ember(page spec §1 D 组;E-5.3 那单只换了搜索图标,整页仍是
/// 心跳口径,见 E-5.3 page spec 的「遗留」第 4 条):顶栏换
/// [`EmberPageScaffold`](§9.4)、输入框换 [`EmberField`](§8.3 四态)、
/// 结果行换 [`EmberPressable`] + [`EmberAvatar`]、空 / 错态换 [`EmberEmpty`] +
/// unDraw、骨架换 [`EmberSkeleton`]、「加载更多」换 [`EmberButton`] 文字变体。
/// **搜索逻辑一行没动**:防抖、过期响应丢弃(序号)、游标翻页、命中高亮窗口
/// 全部沿用改造前的实现。
class SearchPage extends ConsumerStatefulWidget {
  /// 构造搜索页。
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
    return EmberPageScaffold(
      title: '搜索',
      backKey: const Key('search.back'),
      // 结果行整行铺满(分隔线横贯),横向 20 由行自己给(§5.2 / §9.4)。
      contentPadding: EdgeInsets.zero,
      body: Column(
        children: [
          Padding(
            padding: EdgeInsets.fromLTRB(
              tokens.space20,
              tokens.space12,
              tokens.space20,
              tokens.space12,
            ),
            child: EmberField(
              // 页面测试按 `search.input` 定点输入:EmberField 的默认 Key 是
              // `ember.field.input`,这里必须换掉,否则同页多框会串。
              fieldKey: const Key('search.input'),
              controller: _input,
              placeholder: '搜索聊天记录',
              label: '搜索聊天记录',
              prefixIcon: PhosphorIconsRegular.magnifyingGlass,
              autofocus: true,
              onChanged: _onChanged,
              onSubmitted: (value) => _run(value.trim()),
            ),
          ),
          Expanded(child: _body()),
        ],
      ),
    );
  }

  Widget _body() {
    if (_keyword.isEmpty) {
      return const _Centered(
        child: EmberEmpty(
          illustration: ChatIllustration(ChatIllustrationKind.emptyThreads),
          title: '搜索聊天记录',
          description: '输入关键词,找回你们聊过的内容',
        ),
      );
    }
    if (_loading && _hits.isEmpty) {
      return const _SearchSkeleton();
    }
    if (_error != null && _hits.isEmpty) {
      return _Centered(
        child: EmberEmpty(
          illustration: const ChatIllustration(ChatIllustrationKind.loadFailed),
          title: '加载失败',
          description: _error!,
          actionLabel: '重试',
          actionKey: const Key('search.retry'),
          onAction: () => _run(_keyword),
        ),
      );
    }
    if (_hits.isEmpty) {
      return const _Centered(
        child: EmberEmpty(
          illustration: ChatIllustration(ChatIllustrationKind.emptyThreads),
          title: '没有找到相关消息',
          description: '换个关键词试试',
        ),
      );
    }
    return Column(
      children: [
        Expanded(
          child: ListView.builder(
            key: const Key('search.hits'),
            padding: EdgeInsets.only(bottom: tokens.space8),
            itemCount: _hits.length,
            itemBuilder: (context, index) {
              final hit = _hits[index];
              return _SearchHitTile(hit: hit, keyword: _keyword);
            },
          ),
        ),
        if (_hasMore)
          Padding(
            padding: EdgeInsets.only(bottom: tokens.space12),
            child: EmberButton(
              key: const Key('search.more'),
              label: '加载更多',
              variant: EmberButtonVariant.text,
              // 翻页请求在飞时置灰(与改造前 `TextButton(onPressed: null)` 同一口径)。
              // 刻意不用 `loading:`,那会在树里挂一个无限转圈 —— 页面测试里
              // `pumpAndSettle` 永远等不到收敛。
              onPressed: _loading ? null : () => _run(_keyword, append: true),
            ),
          ),
      ],
    );
  }
}

/// 一条命中:头像 40 + 会话名 17/w600 + 高亮片段 + 消息时间 13 `text.tertiary`。
///
/// 为什么不用 [`EmberSettingsTile`]:左侧要头像(它只收 `IconData`),而且摘要
/// 是**富文本**(命中片段 `brand.default` + w600);行高 / 字号仍与它对齐
/// (68 / 17-w600 / 13,§5.2)。
class _SearchHitTile extends StatelessWidget {
  const _SearchHitTile({required this.hit, required this.keyword});

  final ImSearchHit hit;
  final String keyword;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final name = hit.peerName ?? hit.peerId;
    final time = formatMessageTime(
      DateTime.fromMillisecondsSinceEpoch(hit.timestamp),
    );
    return Semantics(
      container: true,
      button: true,
      // 读屏(page spec §6 第 3 条):「会话名,命中片段,时间」。
      label: '$name，${hit.text}，$time',
      onTap: () => context.push('/chat/${hit.peerId}?focus=${hit.msgId}'),
      child: ExcludeSemantics(
        child: EmberPressable(
          key: Key('search.hit:${hit.msgId}'),
          onTap: () => context.push('/chat/${hit.peerId}?focus=${hit.msgId}'),
          pressedScale: 0.97,
          builder: (context, state) => ColoredBox(
            color: state.pressed ? colors.surfaceSunken : Colors.transparent,
            child: ConstrainedBox(
              // 行高下沿 68(spec §5.2「列表行高 68–76」)。
              constraints: const BoxConstraints(minHeight: _minRowHeight),
              child: DecoratedBox(
                decoration: BoxDecoration(
                  border: Border(
                    bottom: BorderSide(color: colors.borderDivider, width: 1),
                  ),
                ),
                child: Padding(
                  padding: EdgeInsets.symmetric(
                    horizontal: tokens.space20,
                    vertical: tokens.space12,
                  ),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      EmberAvatar(
                        image: (hit.peerAvatar == null || hit.peerAvatar!.isEmpty)
                            ? null
                            : NetworkImage(hit.peerAvatar!),
                        size: EmberComponentSizes.avatarMd,
                        name: name,
                      ),
                      SizedBox(width: tokens.space12),
                      Expanded(
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              name,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: TextStyle(
                                fontSize: tokens.fontSizeSubtitle,
                                fontWeight: FontWeight.w600,
                                height: tokens.fontLineHeightSubtitle,
                                color: colors.textPrimary,
                              ),
                            ),
                            SizedBox(height: tokens.space4),
                            Text.rich(
                              TextSpan(
                                children: _highlight(hit.text, keyword, colors),
                              ),
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                            ),
                          ],
                        ),
                      ),
                      SizedBox(width: tokens.space8),
                      Text(
                        time,
                        style: TextStyle(
                          fontSize: tokens.fontSizeCaption,
                          height: tokens.fontLineHeightCaption,
                          color: colors.textTertiary,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  /// 行高下沿 68(与 `EmberSettingsTile` 同一口径)。
  static const double _minRowHeight = 68;

  /// 把命中片段切成若干 TextSpan,命中部分主色加粗;过长时保留命中前后各 20 字。
  static List<TextSpan> _highlight(
      String text, String keyword, EmberColors colors) {
    final plain = TextStyle(
      fontSize: tokens.fontSizeBody,
      height: tokens.fontLineHeightBody,
      color: colors.textSecondary,
    );
    final marked = TextStyle(
      fontSize: tokens.fontSizeBody,
      height: tokens.fontLineHeightBody,
      color: colors.brandDefault,
      fontWeight: FontWeight.w600,
    );
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

/// 骨架:6 行「圆头像 + 两行文字」(`surface.sunken` 呼吸,§8.3)。
class _SearchSkeleton extends StatelessWidget {
  const _SearchSkeleton();

  @override
  Widget build(BuildContext context) {
    return ListView(
      key: const Key('search.skeleton'),
      padding: EdgeInsets.symmetric(vertical: tokens.space12),
      children: [
        for (var i = 0; i < 6; i++)
          Padding(
            padding: EdgeInsets.symmetric(
              horizontal: tokens.space20,
              vertical: tokens.space12,
            ),
            child: Row(
              children: [
                const EmberSkeleton(
                  width: EmberComponentSizes.avatarMd,
                  height: EmberComponentSizes.avatarMd,
                  shape: BoxShape.circle,
                ),
                SizedBox(width: tokens.space12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      EmberSkeleton(
                        width: 120,
                        height: tokens.fontSizeSubtitle,
                      ),
                      SizedBox(height: tokens.space8),
                      EmberSkeleton(height: tokens.fontSizeCaption),
                    ],
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

/// 空 / 错两态居中且可滚动(小屏 + 大字号下不溢出)。
class _Centered extends StatelessWidget {
  const _Centered({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) => SingleChildScrollView(
        child: ConstrainedBox(
          constraints: BoxConstraints(minHeight: constraints.maxHeight),
          child: Center(
            child: Padding(
              padding: EdgeInsets.all(tokens.space24),
              child: child,
            ),
          ),
        ),
      ),
    );
  }
}
