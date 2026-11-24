import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../core/api_exception.dart';
import '../../core/theme/app_typography.dart';
import '../../core/theme/ember_theme_context.dart';
import '../../core/theme/tokens.g.dart' as tokens;
import '../../core/ui/ember_ui.dart';
import '../../im/im_manager.dart';
import '../../im/im_repository.dart';
import '../chat/conversations_controller.dart';
import '../chat/match_cache.dart';
import '../chat/widgets/photo_viewer.dart';
import '../moderation/models.dart';
import '../moderation/moderation_controller.dart';
import '../moderation/moderation_repository.dart';
import '../moderation/widgets/report_sheet.dart';
import '../presence/presence_controller.dart';
import '../square/feed_repository.dart';
import '../square/square_controller.dart';
import 'profile_component_sizes.dart';
import 'widgets/profile_confirm_dialog.dart';
import 'widgets/profile_illustration.dart';
import 'widgets/profile_info_row.dart';
import 'widgets/profile_photo_header.dart';
import 'widgets/user_profile_skeleton.dart';
import 'widgets/voice_intro_bar.dart';

/// 他人资料页(E-5.4 page spec §2:二级页,全屏 push,顶栏走 §9.4 shell)。
///
/// 视觉迁移口径:
/// - 顶栏 52(返回 22 Phosphor `caret-left` + 标题 17/w600 居中),**头图滚动时
///   从全透明渐变到 `surface.page` + `border.divider` 底边**(§9.4 唯一例外);
/// - 照片头图 `overlay.scrim` 叠字 `title` 24;头像 `EmberAvatar` 96;信息行
///   [ProfileInfoRow];标签 `EmberChip`(只读);语音介绍卡保留形态换皮;
/// - 操作区保留(关注 / 解除配对 / 举报 / 拉黑),只换成 `EmberButton` 与
///   「图标 + 明确动词」的 Dialog(§9.3)。
///
/// 业务零改动:关注仍是乐观更新 + 失败回滚、拉黑仍清本机会话、解除配对仍失效
/// 配对缓存 —— 一行逻辑没动,只换取值与控件。
class UserProfilePage extends ConsumerWidget {
  /// 构造他人资料页。
  const UserProfilePage({super.key, required this.userId, this.heroTag});

  /// 看谁的资料。
  final int userId;

  /// Hero tag;来自路由 `extra`(发现页卡照片 / 对话页头像)。null(深链 / 无来源)
  /// 时不包 Hero。
  final String? heroTag;

  /// 轻量结果反馈走 `EmberToast`(§9.3「不打断」),不再用 SnackBar。
  void _toast(BuildContext context, String message) =>
      EmberToast.show(context, message);

  Future<void> _report(BuildContext context, WidgetRef ref) async {
    final result = await showModalBottomSheet<({String type, String detail})>(
      context: context,
      isScrollControlled: true,
      builder: (context) => const ReportSheet(),
    );
    if (result == null) return;
    try {
      await ref.read(moderationRepositoryProvider).report(
          targetUserId: userId, type: result.type, detail: result.detail);
      if (context.mounted) _toast(context, '已收到举报,我们会尽快处理');
    } on ApiException catch (error) {
      if (context.mounted) _toast(context, error.message);
    }
  }

  Future<void> _block(BuildContext context, WidgetRef ref) async {
    // 破坏性确认:图标 + 明确动词(§9.3),不用「确定 / 取消」那对无信息量按钮。
    final confirmed = await showProfileConfirmDialog(
      context,
      icon: PhosphorIconsRegular.prohibit,
      title: '拉黑这位用户?',
      message: '拉黑后你们将互相不可见,本机聊天记录会被清除',
      confirmLabel: '拉黑',
      danger: true,
      confirmKey: const Key('user.block.confirm'),
    );
    if (!confirmed) return;
    try {
      await ref.read(moderationRepositoryProvider).block(userId);
    } on ApiException catch (error) {
      if (context.mounted) _toast(context, error.message);
      return;
    }
    // 黑名单列表是全局缓存的:拉黑后不失效,设置里再打开还是旧列表(2026-09-11 手测 bug)
    ref.invalidate(blockedUsersProvider);
    try {
      // 拉黑已生效,清本机会话只是收尾:失败不打断流程(对方消息已被 IM 黑名单拦)
      await ref.read(imClientProvider).deleteConversation('u$userId');
      await ref.read(conversationsProvider.notifier).reload();
    } catch (_) {}
    if (context.mounted) {
      _toast(context, '已拉黑');
      context.pop();
    }
  }

  Future<void> _unmatch(BuildContext context, WidgetRef ref) async {
    final confirmed = await showProfileConfirmDialog(
      context,
      icon: PhosphorIconsRegular.linkBreak,
      title: '解除配对?',
      message: '解除后双方将无法再聊天,且无法恢复。',
      confirmLabel: '解除配对',
      danger: true,
      confirmKey: const Key('user.unmatch.confirm'),
    );
    if (!confirmed || !context.mounted) return;
    try {
      await ref.read(imRepositoryProvider).unmatch(userId);
    } on ApiException catch (error) {
      if (context.mounted) _toast(context, error.message);
      return;
    }
    try {
      await ref.read(imClientProvider).deleteConversation('u$userId');
    } catch (_) {}
    ref.invalidate(matchCacheProvider);
    unawaited(ref.read(conversationsProvider.notifier).reload());
    if (context.mounted) {
      _toast(context, '已解除配对');
      context.pop();
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final profile = ref.watch(userProfileProvider(userId));
    // 在线状态是公开信息(不依赖配对):与广场/动态详情同款写法
    ref.read(presenceProvider.notifier).track('user:$userId', [userId]);
    final online = ref.watch(presenceProvider)[userId]?.online ?? false;
    // 「解除配对」只在确实配对时出现;缓存未加载完不显示(避免误判)
    final matches = ref.watch(matchCacheProvider).value ?? const <String, MatchEntry>{};
    final isMatched = matches.containsKey('u$userId');
    void onBack() => Navigator.of(context).maybePop();
    void onMore(String value) => switch (value) {
          'unmatch' => _unmatch(context, ref),
          'report' => _report(context, ref),
          _ => _block(context, ref),
        };
    return profile.when(
      // loading 也要有目标端的 Hero(否则转场找不到落点),骨架自己包了一层。
      loading: () => _ProfileScaffold(
        progress: 1,
        onBack: onBack,
        child: UserProfileSkeleton(heroTag: heroTag),
      ),
      error: (error, _) => _ProfileScaffold(
        progress: 1,
        title: '资料',
        onBack: onBack,
        child: Center(
          child: Padding(
            padding: EdgeInsets.all(tokens.space24),
            child: EmberEmpty(
              illustration:
                  const ProfileIllustration(ProfileIllustrationKind.loadFailed),
              title: '资料没能加载出来',
              description: apiMessageOf(error),
              actionLabel: '重试',
              actionKey: const Key('user.retry'),
              onAction: () => ref.invalidate(userProfileProvider(userId)),
            ),
          ),
        ),
      ),
      data: (data) => _ProfileBody(
        profile: data,
        heroTag: heroTag,
        online: online,
        isMatched: isMatched,
        onBack: onBack,
        onMore: onMore,
      ),
    );
  }
}

/// 二级页外壳:内容 + 浮在内容上的顶栏(§9.4)。loading / error 态没有照片,
/// 顶栏直接给实底([progress] = 1)。
class _ProfileScaffold extends StatelessWidget {
  const _ProfileScaffold({
    required this.progress,
    required this.onBack,
    required this.child,
    this.title,
    this.onMore,
    this.isMatched = false,
  });

  final double progress;
  final VoidCallback onBack;
  final Widget child;
  final String? title;
  final ValueChanged<String>? onMore;
  final bool isMatched;

  @override
  Widget build(BuildContext context) => Scaffold(
        body: Stack(
          children: [
            child,
            _ProfileTopBar(
              progress: progress,
              title: title,
              onBack: onBack,
              onMore: onMore,
              isMatched: isMatched,
            ),
          ],
        ),
      );
}

/// §9.4 二级页顶栏:高 52;返回 22 + 标题 17/w600 居中;[progress] 由滚动位置驱动,
/// 0 = 全透明压在照片上(白字),1 = `surface.page` 实底 + `border.divider` 底边。
class _ProfileTopBar extends StatelessWidget {
  const _ProfileTopBar({
    required this.progress,
    required this.onBack,
    this.title,
    this.onMore,
    this.isMatched = false,
  });

  /// 0–1 的实底进度。
  final double progress;

  final VoidCallback onBack;
  final String? title;
  final ValueChanged<String>? onMore;

  /// 是否已配对(决定菜单里有没有「解除配对」)。
  final bool isMatched;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final faded = progress.clamp(0.0, 1.0);
    // 图标 / 标题色:白(压在照片上)→ `text.primary`(实底上)。两套主题都成立,
    // 因为照片叠字本来就是「白字压深 scrim」。
    final foreground = Color.lerp(Colors.white, colors.textPrimary, faded)!;
    // 标题过半程才淡入:避免与头图叠字里的昵称撞在同一屏。
    final titleOpacity = faded <= ProfileComponentSizes.topBarTitleStart
        ? 0.0
        : ((faded - ProfileComponentSizes.topBarTitleStart) /
                (1 - ProfileComponentSizes.topBarTitleStart))
            .clamp(0.0, 1.0);
    final more = onMore;
    return SafeArea(
      bottom: false,
      child: Container(
        height: tokens.sizeControlHeight,
        decoration: BoxDecoration(
          color: colors.surfacePage.withValues(alpha: faded),
          border: Border(
            bottom: BorderSide(
              color: colors.borderDivider.withValues(alpha: faded),
            ),
          ),
        ),
        child: Row(
          children: [
            _TopBarButton(
              entryKey: const Key('user.back'),
              icon: PhosphorIconsRegular.caretLeft,
              label: '返回',
              color: foreground,
              onTap: onBack,
            ),
            Expanded(
              child: Opacity(
                opacity: titleOpacity,
                child: Text(
                  title ?? '',
                  textAlign: TextAlign.center,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppText.subtitle.copyWith(color: foreground),
                ),
              ),
            ),
            if (more == null)
              SizedBox(width: tokens.sizeTouchApp)
            else
              SizedBox(
                width: tokens.sizeTouchApp,
                height: tokens.sizeTouchApp,
                child: PopupMenuButton<String>(
                  key: const Key('user.more'),
                  tooltip: '更多',
                  padding: EdgeInsets.zero,
                  icon: Icon(
                    PhosphorIconsRegular.dotsThree,
                    size: tokens.sizeIcon24,
                    color: foreground,
                  ),
                  onSelected: more,
                  itemBuilder: (context) => [
                    if (isMatched)
                      const PopupMenuItem(
                        key: Key('user.unmatch'),
                        value: 'unmatch',
                        child: Text('解除配对'),
                      ),
                    const PopupMenuItem(
                      key: Key('user.report'),
                      value: 'report',
                      child: Text('举报'),
                    ),
                    const PopupMenuItem(
                      key: Key('user.block'),
                      value: 'block',
                      child: Text('拉黑'),
                    ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }
}

/// 顶栏图标按钮:热区 48(§8.4),图标本体 22(E-5.4 page spec §3「返回 22」)。
class _TopBarButton extends StatelessWidget {
  const _TopBarButton({
    required this.entryKey,
    required this.icon,
    required this.label,
    required this.color,
    required this.onTap,
  });

  final Key entryKey;
  final IconData icon;
  final String label;
  final Color color;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => EmberPressable(
        key: entryKey,
        onTap: onTap,
        pressedScale: 0.97,
        borderRadius: BorderRadius.circular(tokens.radiusPill),
        semanticLabel: label,
        builder: (context, state) => SizedBox(
          width: tokens.sizeTouchApp,
          height: tokens.sizeTouchApp,
          child: Icon(icon, size: 22, color: color),
        ),
      );
}

/// 资料正文:头图 → 身份行(头像 96 + 关注/粉丝 + 关注钮)→ 信息卡 → 语音卡 → 相册。
///
/// 有状态只为一件事:把滚动位置换算成顶栏的实底进度(§9.4「头图滚动时顶栏
/// 可透明化」)。滚动回调里只在进度真的变了才 `setState`,避免每帧重建整页。
class _ProfileBody extends StatefulWidget {
  const _ProfileBody({
    required this.profile,
    required this.heroTag,
    required this.online,
    required this.isMatched,
    required this.onBack,
    required this.onMore,
  });

  final UserProfile profile;
  final String? heroTag;
  final bool online;
  final bool isMatched;
  final VoidCallback onBack;
  final ValueChanged<String> onMore;

  @override
  State<_ProfileBody> createState() => _ProfileBodyState();
}

class _ProfileBodyState extends State<_ProfileBody> {
  final ScrollController _scroll = ScrollController();
  double _progress = 0;

  @override
  void initState() {
    super.initState();
    _scroll.addListener(_onScroll);
  }

  @override
  void dispose() {
    _scroll
      ..removeListener(_onScroll)
      ..dispose();
    super.dispose();
  }

  void _onScroll() {
    final next =
        (_scroll.offset / ProfileComponentSizes.topBarFadeDistance).clamp(0.0, 1.0);
    // 0.02 的死区:四舍五入带来的抖动不值得整页重建。
    if ((next - _progress).abs() < 0.02) return;
    setState(() => _progress = next);
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final profile = widget.profile;
    final photos = profile.photos.map((photo) => photo.url).toList();
    final tagNames = profile.tags.map((tag) => tag.name).join('、');
    final voice = profile.voice;
    return _ProfileScaffold(
      progress: _progress,
      title: profile.nickname,
      onBack: widget.onBack,
      onMore: widget.onMore,
      isMatched: widget.isMatched,
      child: ListView(
        key: const Key('user.body'),
        controller: _scroll,
        padding: EdgeInsets.zero,
        children: [
          ProfilePhotoHeader(
            photoUrl: photos.isEmpty ? null : photos.first,
            nickname: profile.nickname,
            age: profile.age,
            city: profile.city,
            online: widget.online,
            heroTag: widget.heroTag,
          ),
          Padding(
            padding: EdgeInsets.fromLTRB(
              tokens.space20,
              tokens.space20,
              tokens.space20,
              0,
            ),
            child: _IdentityBlock(
              profile: profile,
              online: widget.online,
              avatarUrl: photos.isEmpty ? null : photos.first,
            ),
          ),
          Padding(
            padding: EdgeInsets.fromLTRB(
              tokens.space20,
              tokens.space24,
              tokens.space20,
              tokens.space32,
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                EmberCard(
                  padding: EdgeInsets.zero,
                  child: Column(
                    children: [
                      ProfileInfoRow(
                        label: '个性签名',
                        value: profile.bio,
                      ),
                      ProfileInfoRow(
                        label: '标签',
                        value: tagNames,
                        showDivider: false,
                        child: tagNames.isEmpty
                            ? Text(
                                '未填',
                                style: AppText.body
                                    .copyWith(color: colors.textSecondary),
                              )
                            : Wrap(
                                spacing: tokens.space8,
                                runSpacing: tokens.space8,
                                children: [
                                  for (final tag in profile.tags)
                                    EmberChip(
                                      label: tag.name,
                                      // 他人资料页的标签只展示(§4「标签 default」)。
                                      readOnly: true,
                                    ),
                                ],
                              ),
                      ),
                    ],
                  ),
                ),
                // 批次 R:语音自我介绍是公开的;没录过(voice == null)时整块不渲染,
                // 不留空白占位。
                if (voice != null) ...[
                  SizedBox(height: tokens.space12),
                  EmberCard(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '语音介绍',
                          style: AppText.subtitle.copyWith(color: colors.textPrimary),
                        ),
                        SizedBox(height: tokens.space12),
                        VoiceIntroBar(
                          key: const Key('user.voice.bar'),
                          source: voice.url,
                          durationMs: voice.durationMs,
                          keyPrefix: 'user.voice',
                        ),
                      ],
                    ),
                  ),
                ],
                if (photos.isNotEmpty) ...[
                  SizedBox(height: tokens.space12),
                  EmberCard(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '相册',
                          style: AppText.subtitle.copyWith(color: colors.textPrimary),
                        ),
                        SizedBox(height: tokens.space12),
                        GridView.count(
                          shrinkWrap: true,
                          physics: const NeverScrollableScrollPhysics(),
                          crossAxisCount: 3,
                          mainAxisSpacing: tokens.space8,
                          crossAxisSpacing: tokens.space8,
                          children: [
                            for (var i = 0; i < photos.length; i++)
                              _AlbumThumb(
                                index: i,
                                url: photos[i],
                                userId: profile.userId,
                                urls: photos,
                              ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// 相册缩略图:点开全屏 + Hero(§9.3「沉浸内容 = 全屏 + Hero 转场」)。
class _AlbumThumb extends StatelessWidget {
  const _AlbumThumb({
    required this.index,
    required this.url,
    required this.userId,
    required this.urls,
  });

  final int index;
  final String url;
  final int userId;
  final List<String> urls;

  /// 相册第 [index] 张的 Hero tag(与全屏页同名)。
  static String heroTagOf(int userId, int index) => 'photo-user-$userId-$index';

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return EmberPressable(
      key: Key('user.album.photo:$index'),
      onTap: () => openPhotoViewer(
        context,
        urls: urls,
        initialIndex: index,
        heroTags: [for (var i = 0; i < urls.length; i++) heroTagOf(userId, i)],
      ),
      pressedScale: EmberComponentSizes.cardPressedScale,
      borderRadius: BorderRadius.circular(tokens.radiusSm),
      semanticLabel: '相册第 ${index + 1} 张照片',
      builder: (context, state) => ClipRRect(
        borderRadius: BorderRadius.circular(tokens.radiusSm),
        child: Hero(
          tag: heroTagOf(userId, index),
          child: Image.network(
            url,
            fit: BoxFit.cover,
            errorBuilder: (c, e, s) => ColoredBox(
              color: colors.surfaceSunken,
              child: Icon(
                PhosphorIconsRegular.image,
                size: tokens.sizeIcon24,
                color: colors.textTertiary,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// 身份区:头像 96 + 关注/粉丝计数 + ID + 关注按钮。
///
/// 关注是**乐观更新**:点下去立刻切态与改粉丝数,请求失败再回滚并提示 ——
/// 关注是低风险动作,等网络往返再变灰会让整页像卡住。计数只在本页本地维护
/// (不回写 `userProfileProvider`),所以离开再进来仍以服务端为准。
///
/// 为什么整块是有状态的:`_following` 与 `_followerCount` 必须在同一个 State 里,
/// 否则点「已关注」时按钮变了、计数没变(拆成两个组件就会互相看不见对方的乐观态)。
class _IdentityBlock extends ConsumerStatefulWidget {
  const _IdentityBlock({
    required this.profile,
    required this.online,
    required this.avatarUrl,
  });

  final UserProfile profile;
  final bool online;

  /// 头像地址(取第一张相册图,与头图同源)。
  final String? avatarUrl;

  @override
  ConsumerState<_IdentityBlock> createState() => _IdentityBlockState();
}

class _IdentityBlockState extends ConsumerState<_IdentityBlock> {
  late bool _following;
  late int _followerCount;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _following = widget.profile.isFollowed;
    _followerCount = widget.profile.followerCount;
  }

  @override
  void didUpdateWidget(covariant _IdentityBlock oldWidget) {
    super.didUpdateWidget(oldWidget);
    // 换了个人才重置;同一人刷新时保留乐观态(否则刚关注完会被旧响应打回去)
    if (oldWidget.profile.userId != widget.profile.userId) {
      _following = widget.profile.isFollowed;
      _followerCount = widget.profile.followerCount;
    }
  }

  void _toast(String message) => EmberToast.show(context, message);

  Future<void> _toggle() async {
    if (_busy) return;
    final target = !_following;
    setState(() {
      _following = target;
      _followerCount += target ? 1 : -1;
      _busy = true;
    });
    try {
      final repository = ref.read(feedRepositoryProvider);
      if (target) {
        await repository.follow(widget.profile.userId);
      } else {
        await repository.unfollow(widget.profile.userId);
      }
      // 关注关系变了 → 广场「关注」tab 的列表必须失效,否则切回去还是旧列表
      // (1.0.9 记录的已知限制,批次 J 顺手补掉)
      ref.invalidate(followingProvider);
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _following = !target;
        _followerCount += target ? -1 : 1;
      });
      _toast(error.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final avatarUrl = widget.avatarUrl;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        EmberAvatar(
              image: (avatarUrl == null || avatarUrl.isEmpty)
                  ? null
                  : NetworkImage(avatarUrl),
              size: EmberComponentSizes.avatarHero,
              name: widget.profile.nickname,
              online: widget.online,
            ),
        SizedBox(width: tokens.space20),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Row(
                children: [
                  _FollowCount(
                        key: const Key('user.followingCount'),
                        label: '关注',
                        value: widget.profile.followingCount,
                      ),
                  SizedBox(width: tokens.space16),
                  _FollowCount(
                    key: const Key('user.followerCount'),
                    label: '粉丝',
                    value: _followerCount,
                  ),
                ],
              ),
              SizedBox(height: tokens.space4),
              Text(
                'ID:u${widget.profile.userId}',
                style: AppText.micro.copyWith(color: colors.textTertiary),
              ),
              SizedBox(height: tokens.space12),
              // 关注是这一页的主操作(§2「品牌色只出现在引导视线处」):主按钮 + 光晕;
              // 与头像同在一行,避免把信息卡整块挤到折叠线以下。
              EmberButton(
                key: const Key('user.follow'),
                label: _following ? '已关注' : '关注',
                variant: _following
                    ? EmberButtonVariant.secondary
                    : EmberButtonVariant.primary,
                expand: true,
                onPressed: _busy ? null : _toggle,
              ),
            ],
          ),
        ),
      ],
    );
  }
}

/// 「12 关注」这样的一格计数:数字 `body` / w700 `text.primary`,标签 `caption`
/// `text.secondary`。
class _FollowCount extends StatelessWidget {
  const _FollowCount({super.key, required this.label, required this.value});

  final String label;
  final int value;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          '$value',
          style: AppText.body.copyWith(
            color: colors.textPrimary,
            fontWeight: FontWeight.w700,
          ),
        ),
        SizedBox(width: tokens.space4),
        Text(label, style: AppText.caption.copyWith(color: colors.textSecondary)),
      ],
    );
  }
}
