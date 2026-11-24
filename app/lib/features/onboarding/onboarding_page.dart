import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../core/api_exception.dart';
import '../../core/format.dart';
import '../../core/theme/app_typography.dart';
import '../../core/theme/ember_motion.dart';
import '../../core/theme/ember_theme_context.dart';
import '../../core/theme/tokens.g.dart' as tokens;
import '../../core/ui/ember_ui.dart';
import '../profile/models.dart';
import '../profile/profile_controller.dart';
import '../profile/widgets/photo_grid.dart';
import '../profile/widgets/profile_form_fields.dart';
import '../profile/widgets/tag_selector.dart';

/// 第 1 步(基本信息)的校验;返回中文错误说明或 `null`。
String? validateBasicStep(
    {required String nickname, required String? gender, required DateTime? birthday}) {
  if (nickname.isEmpty) return '请填写昵称';
  if (gender == null) return '请选择性别';
  if (birthday == null) return '请选择生日';
  if (!isAtLeast18(birthday)) return '未满 18 周岁,无法使用本应用';
  return null;
}

/// 第 2 步(关于我)的校验;返回中文错误说明或 `null`。
String? validateAboutStep({required String city, required String bio}) {
  if (city.isEmpty) return '请填写城市';
  if (bio.isEmpty) return '请填写简介';
  return null;
}

/// 完善资料向导(附录 E):§9.4 二级页 shell + 分段进度 + 三步表单 + 底部按钮行。
///
/// E-5.6a 只换皮:三步内容、校验顺序、每步 PATCH 的字段与「至少一张待审照片才能
/// 完成」的业务判断**一行未动**(page spec §7 拍板:引导页保留现有步骤与交互)。
///
/// 三步里的字段组件来自 `features/profile/widgets/`(昵称 / 性别 / 生日 / 城市 /
/// 简介 / 标签 / 照片格):它们与「编辑资料页」共用,按拆单结论归 **E-5.6c**(表单组),
/// 本单不碰 —— 页面外壳、进度条、按钮、加载/错误态已 Ember 化。
class OnboardingPage extends ConsumerStatefulWidget {
  /// 构造引导页。
  const OnboardingPage({super.key});

  @override
  ConsumerState<OnboardingPage> createState() => _OnboardingPageState();
}

class _OnboardingPageState extends ConsumerState<OnboardingPage> {
  final _pageController = PageController();
  final _nickname = TextEditingController();
  final _city = TextEditingController();
  final _bio = TextEditingController();
  String? _gender;
  DateTime? _birthday;
  Set<int> _tagIds = {};
  bool _prefilled = false;
  bool _busy = false;
  int _step = 0;

  @override
  void dispose() {
    _pageController.dispose();
    _nickname.dispose();
    _city.dispose();
    _bio.dispose();
    super.dispose();
  }

  void _prefill(Profile profile) {
    if (_prefilled) return;
    _prefilled = true;
    _nickname.text = profile.nickname;
    _city.text = profile.city;
    _bio.text = profile.bio;
    _gender = profile.gender;
    _birthday = parseDate(profile.birthday);
    _tagIds = profile.tags.map((tag) => tag.id).toSet();
  }

  /// 翻到第 [step] 步。
  ///
  /// 位移用 `spring.standard`(§7.1「页面切换、展开收起用 standard」);
  /// 减弱动态效果时直接跳页(§7.3:取消位移,不做 120ms 淡入 —— 这里没有淡入的
  /// 承载层,跳页等价于「没有位移」)。
  void _goToStep(int step) {
    setState(() => _step = step);
    if (EmberMotion.reducedOf(context)) {
      _pageController.jumpToPage(step);
      return;
    }
    _pageController.animateToPage(
      step,
      duration: const Duration(milliseconds: 320),
      curve: EmberMotion.springCurve(EmberMotion.standard),
    );
  }

  Future<void> _next() async {
    Map<String, dynamic>? patch;
    if (_step == 0) {
      final error = validateBasicStep(
          nickname: _nickname.text.trim(), gender: _gender, birthday: _birthday);
      if (error != null) {
        EmberToast.show(context, error);
        return;
      }
      patch = {
        'nickname': _nickname.text.trim(),
        'gender': _gender,
        'birthday': formatDate(_birthday!),
      };
    } else if (_step == 1) {
      final error = validateAboutStep(city: _city.text.trim(), bio: _bio.text.trim());
      if (error != null) {
        EmberToast.show(context, error);
        return;
      }
      patch = {
        'city': _city.text.trim(),
        'bio': _bio.text.trim(),
        'tag_ids': _tagIds.toList(),
      };
    } else {
      await _finish();
      return;
    }

    setState(() => _busy = true);
    try {
      await ref.read(profileProvider.notifier).save(patch);
      if (!mounted) return;
      _goToStep(_step + 1);
    } on ApiException catch (error) {
      if (mounted) EmberToast.show(context, error.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _finish() async {
    setState(() => _busy = true);
    try {
      await ref.read(profileProvider.notifier).reload();
      if (!mounted) return;
      final profile = ref.read(profileProvider).value;
      if (profile == null || profile.photos.where((photo) => photo.isApproved).isEmpty) {
        EmberToast.show(context, '至少上传一张照片');
        return;
      }
      context.go('/home');
    } on ApiException catch (error) {
      if (mounted) EmberToast.show(context, error.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final profile = ref.watch(profileProvider);
    return EmberPageScaffold(
      title: '完善资料',
      // 引导流程不提供返回:离开靠「稍后再说」(直接去首页),与改版前一致。
      showBack: false,
      // 内容贴边:分步进度条、PageView 与三个步骤各自管自己的水平内边距。
      contentPadding: EdgeInsets.zero,
      trailing: EmberButton(
        label: '稍后再说',
        variant: EmberButtonVariant.text,
        onPressed: () => context.go('/home'),
      ),
      bottomBar: profile.maybeWhen(
        // 加载 / 错误态不给底部按钮(没有可提交的表单)。
        orElse: () => null,
        data: (_) => _BottomActions(
          step: _step,
          busy: _busy,
          onBack: () => _goToStep(_step - 1),
          onNext: _next,
        ),
      ),
      body: profile.when(
        loading: () => Padding(
          padding: EdgeInsets.all(tokens.space20),
          child: const _OnboardingSkeleton(key: Key('onboarding.skeleton')),
        ),
        error: (error, _) => Center(
          child: Padding(
            padding: EdgeInsets.all(tokens.space20),
            child: EmberEmpty(
              // 加载失败用「暖色几何体」插画(§6:禁止灰色图标占位)。
              illustration: const _WarmGeometryIllustration(),
              title: '没能加载出来',
              description: apiMessageOf(error),
              actionLabel: '重试',
              actionKey: const Key('onboarding.retry'),
              onAction: () => ref.read(profileProvider.notifier).reload(),
            ),
          ),
        ),
        data: (data) {
          _prefill(data);
          return Column(
            children: [
              Padding(
                padding: EdgeInsets.fromLTRB(
                    tokens.space20, tokens.space8, tokens.space20, tokens.space16),
                child: Column(
                  children: [
                    _StepProgress(
                      key: const Key('onboarding.progress'),
                      steps: 3,
                      current: _step,
                    ),
                    SizedBox(height: tokens.space8),
                    Text(
                      '第 ${_step + 1} 步 / 共 3 步',
                      style: AppText.caption.copyWith(color: context.ember.textSecondary),
                    ),
                  ],
                ),
              ),
              Expanded(
                child: PageView(
                  controller: _pageController,
                  physics: const NeverScrollableScrollPhysics(),
                  children: [
                    _StepBasic(
                      nickname: _nickname,
                      gender: _gender,
                      birthday: _birthday,
                      onGenderChanged: (value) => setState(() => _gender = value),
                      onBirthdayChanged: (value) => setState(() => _birthday = value),
                    ),
                    _StepAbout(
                      city: _city,
                      bio: _bio,
                      tagIds: _tagIds,
                      onTagsChanged: (ids) => setState(() => _tagIds = ids),
                    ),
                    const _StepPhotos(),
                  ],
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}

/// 分步进度(3 段胶囊):已过段 `brand.default`,未过段 `surface.sunken`
/// (代替「心跳」期的渐变填充 —— Ember 没有渐变,§3.5)。
class _StepProgress extends StatelessWidget {
  const _StepProgress({super.key, required this.steps, required this.current});

  final int steps;
  final int current;

  /// 进度条高度:4(spec §8 未给该组件,复用 `space.4` 档)。
  static const double _height = tokens.space4;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return Semantics(
      container: true,
      label: '第 ${current + 1} 步,共 $steps 步',
      child: Row(
        children: [
          for (var i = 0; i < steps; i++) ...[
            if (i > 0) SizedBox(width: tokens.space8),
            Expanded(
              child: ExcludeSemantics(
                child: Container(
                  height: _height,
                  decoration: BoxDecoration(
                    color: i <= current ? colors.brandDefault : colors.surfaceSunken,
                    borderRadius: BorderRadius.circular(tokens.radiusPill),
                  ),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// 底部按钮行:上一步(次按钮)+ 下一步 / 完成(主按钮)。
class _BottomActions extends StatelessWidget {
  const _BottomActions({
    required this.step,
    required this.busy,
    required this.onBack,
    required this.onNext,
  });

  final int step;
  final bool busy;
  final VoidCallback onBack;
  final VoidCallback onNext;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        if (step > 0) ...[
          EmberButton(
            label: '上一步',
            variant: EmberButtonVariant.secondary,
            onPressed: busy ? null : onBack,
          ),
          SizedBox(width: tokens.space12),
        ],
        Expanded(
          child: EmberButton(
            key: const Key('onboarding.next'),
            label: step == 2 ? '完成' : '下一步',
            loading: busy,
            onPressed: onNext,
          ),
        ),
      ],
    );
  }
}

/// 加载态骨架:三行「标题 + 两个输入格」(`surface.sunken` 色块,§8.3 骨架)。
class _OnboardingSkeleton extends StatelessWidget {
  const _OnboardingSkeleton({super.key});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const EmberSkeleton(width: 120, height: 17),
        SizedBox(height: tokens.space20),
        for (var i = 0; i < 2; i++) ...[
          const EmberSkeleton(height: tokens.sizeControlHeight, radius: tokens.radiusMd),
          SizedBox(height: tokens.space12),
        ],
        const EmberSkeleton(width: 200, height: 13),
      ],
    );
  }
}

/// 「暖色几何体」插画(启动 / 加载失败用):两层同心圆 + 一道朱砂弧,
/// 全部取 `brand.default` 与 `surface.sunken`,不引新色值(§6「空态用暖色几何体」)。
class _WarmGeometryIllustration extends StatelessWidget {
  const _WarmGeometryIllustration();

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return SizedBox(
      width: EmberComponentSizes.illustrationMax,
      height: EmberComponentSizes.illustrationMax,
      child: Stack(
        alignment: Alignment.center,
        children: [
          Container(
            decoration: BoxDecoration(
              color: colors.surfaceSunken,
              shape: BoxShape.circle,
            ),
          ),
          Container(
            width: EmberComponentSizes.illustrationMax / 2,
            height: EmberComponentSizes.illustrationMax / 2,
            decoration: BoxDecoration(
              color: colors.brandDefault.withValues(alpha: 0.16),
              shape: BoxShape.circle,
            ),
          ),
          Icon(
            PhosphorIconsRegular.cloudSlash,
            size: tokens.sizeIcon24,
            color: colors.brandDefault,
          ),
        ],
      ),
    );
  }
}

class _StepBasic extends StatelessWidget {
  const _StepBasic({
    required this.nickname,
    required this.gender,
    required this.birthday,
    required this.onGenderChanged,
    required this.onBirthdayChanged,
  });

  final TextEditingController nickname;
  final String? gender;
  final DateTime? birthday;
  final ValueChanged<String> onGenderChanged;
  final ValueChanged<DateTime> onBirthdayChanged;

  @override
  Widget build(BuildContext context) => ListView(
        padding: EdgeInsets.symmetric(horizontal: tokens.space20),
        children: [
          _SectionCard(
            title: '基本信息',
            children: [
              NicknameField(controller: nickname),
              GenderSelector(value: gender, onChanged: onGenderChanged),
              BirthdayField(value: birthday, onChanged: onBirthdayChanged),
            ],
          ),
        ],
      );
}

class _StepAbout extends StatelessWidget {
  const _StepAbout({
    required this.city,
    required this.bio,
    required this.tagIds,
    required this.onTagsChanged,
  });

  final TextEditingController city;
  final TextEditingController bio;
  final Set<int> tagIds;
  final ValueChanged<Set<int>> onTagsChanged;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return ListView(
      padding: EdgeInsets.symmetric(horizontal: tokens.space20),
      children: [
        _SectionCard(
          title: '关于我',
          children: [
            CityField(controller: city),
            BioField(controller: bio),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('标签(可多选)',
                    style: AppText.caption.copyWith(color: colors.textSecondary)),
                SizedBox(height: tokens.space8),
                TagSelector(selectedIds: tagIds, onChanged: onTagsChanged),
              ],
            ),
          ],
        ),
      ],
    );
  }
}

class _StepPhotos extends StatelessWidget {
  const _StepPhotos();

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return ListView(
      padding: EdgeInsets.symmetric(horizontal: tokens.space20),
      children: [
        _SectionCard(
          title: '照片',
          children: [
            Text('上传至少 1 张照片(最多 6 张),让别人认识你',
                style: AppText.caption.copyWith(color: colors.textSecondary)),
            SizedBox(height: tokens.space12),
            const PhotoGrid(),
          ],
        ),
      ],
    );
  }
}

/// 步骤卡:`EmberCard` + 区块标题(17/w600)+ 12 间距(§5.2「标题与内容 12」)。
class _SectionCard extends StatelessWidget {
  const _SectionCard({required this.title, required this.children});

  final String title;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return EmberCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: AppText.subtitle.copyWith(color: colors.textPrimary)),
          SizedBox(height: tokens.space12),
          for (var i = 0; i < children.length; i++) ...[
            if (i > 0) SizedBox(height: tokens.space16),
            children[i],
          ],
        ],
      ),
    );
  }
}
