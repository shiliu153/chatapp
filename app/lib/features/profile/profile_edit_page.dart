import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_exception.dart';
import '../../core/format.dart';
import '../../core/theme/app_typography.dart';
import '../../core/theme/ember_theme_context.dart';
import '../../core/theme/tokens.g.dart' as tokens;
import '../../core/ui/ember_ui.dart';
import 'models.dart';
import 'profile_controller.dart';
import 'widgets/photo_grid.dart';
import 'widgets/profile_form_fields.dart';
import 'widgets/profile_illustration.dart';
import 'widgets/profile_voice_card.dart';

/// 编辑资料(附录 E / E-5.6c):§9.4 二级页 shell + 三张分组卡
/// (基本信息 / 关于我 / 照片)+ 底部主操作「保存」。
///
/// **只换皮**:字段集合、PATCH 的字段与取值、保存后 `pop` 的行为与改版前一致。
/// 三处口径按 page spec 落地:
/// - 校验失败**不弹全局 Toast**,字段下方给 `status.danger` 文字 + 描边转红(§5);
/// - 提交失败给表单底部的 `status.danger` 提示条,**保留已填内容**(§5);
/// - 照片管理沿用现有交互(加号格 + 每张右上角删除钮),本页只换外壳(§7 第 4 条)。
class ProfileEditPage extends ConsumerStatefulWidget {
  /// 构造编辑资料页。
  const ProfileEditPage({super.key});

  @override
  ConsumerState<ProfileEditPage> createState() => _ProfileEditPageState();
}

class _ProfileEditPageState extends ConsumerState<ProfileEditPage> {
  final _nickname = TextEditingController();
  final _city = TextEditingController();
  final _bio = TextEditingController();
  String? _gender;
  DateTime? _birthday;
  Set<int> _tagIds = {};
  bool _prefilled = false;
  bool _saving = false;

  /// 昵称的校验说明(page spec §5:错误只落在字段上,不弹 Toast)。
  String? _nicknameError;

  /// 生日的校验说明(未满 18 岁)。
  String? _birthdayError;

  /// 提交失败的提示条文案;`null` 时不出提示条。
  String? _submitError;

  @override
  void dispose() {
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

  Future<void> _save() async {
    final nickname = _nickname.text.trim();
    final birthday = _birthday;
    // 校验规则一字未动(昵称必填 / 未满 18 岁不许保存),只是把提示从 Toast
    // 挪到字段下方(page spec §5)。
    final nicknameError = nickname.isEmpty ? '请填写昵称' : null;
    final birthdayError = birthday != null && !isAtLeast18(birthday)
        ? '未满 18 周岁,无法使用本应用'
        : null;
    if (nicknameError != null || birthdayError != null) {
      setState(() {
        _nicknameError = nicknameError;
        _birthdayError = birthdayError;
        _submitError = null;
      });
      return;
    }

    final patch = <String, dynamic>{
      'nickname': nickname,
      'city': _city.text.trim(),
      'bio': _bio.text.trim(),
      'tag_ids': _tagIds.toList(),
    };
    if (_gender != null) patch['gender'] = _gender;
    if (birthday != null) patch['birthday'] = formatDate(birthday);

    setState(() {
      _nicknameError = null;
      _birthdayError = null;
      _submitError = null;
      _saving = true;
    });
    try {
      await ref.read(profileProvider.notifier).save(patch);
      if (!mounted) return;
      EmberToast.show(context, '已保存');
      Navigator.of(context).pop();
    } on ApiException catch (error) {
      // 提交失败:提示条 + 保留已填内容(不弹 Toast,§5)。
      if (mounted) setState(() => _submitError = error.message);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final profile = ref.watch(profileProvider);
    return EmberPageScaffold(
      title: '编辑资料',
      backKey: const Key('edit.back'),
      // 加载 / 错误态没有可提交的表单,底部主操作区整块不出现。
      bottomBar: profile.maybeWhen(
        orElse: () => null,
        data: (_) => Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (_submitError != null) ...[
              FormErrorBanner(message: _submitError!),
              SizedBox(height: tokens.space12),
            ],
            EmberButton(
              key: const Key('edit.save'),
              label: '保存',
              expand: true,
              loading: _saving,
              onPressed: _save,
            ),
          ],
        ),
      ),
      body: profile.when(
        // 骨架放进可滚动列表:800×600 的测试视口与窄屏手机上,三块卡片骨架
        // 比可视区高,直接塞进 Column 会 RenderFlex overflow(暗色回归用例抓到过)。
        loading: () => ListView(
          key: const Key('edit.skeleton'),
          padding: EdgeInsets.only(top: tokens.space16, bottom: tokens.space40),
          children: const [_EditSkeleton()],
        ),
        error: (error, _) => Center(
          child: Padding(
            padding: EdgeInsets.all(tokens.space20),
            child: EmberEmpty(
              illustration:
                  const ProfileIllustration(ProfileIllustrationKind.loadFailed),
              title: '没能加载出来',
              description: apiMessageOf(error),
              actionLabel: '重试',
              actionKey: const Key('edit.retry'),
              onAction: () => ref.read(profileProvider.notifier).reload(),
            ),
          ),
        ),
        data: (data) {
          _prefill(data);
          return ListView(
            // 横向 20 由 shell 给(§9.4),这里只补纵向气口。
            padding: EdgeInsets.only(top: tokens.space16, bottom: tokens.space40),
            children: [
              _Section(
                title: '基本信息',
                children: [
                  NicknameField(
                    controller: _nickname,
                    errorText: _nicknameError,
                  ),
                  GenderSelector(
                    value: _gender,
                    onChanged: (value) => setState(() => _gender = value),
                  ),
                  BirthdayField(
                    value: _birthday,
                    errorText: _birthdayError,
                    onChanged: (value) => setState(() {
                      _birthday = value;
                      _birthdayError = null;
                    }),
                  ),
                  CityField(controller: _city),
                ],
              ),
              SizedBox(height: tokens.space24),
              _Section(
                title: '关于我',
                children: [
                  BioField(controller: _bio),
                  TagField(
                    selectedIds: _tagIds,
                    onChanged: (ids) => setState(() => _tagIds = ids),
                  ),
                ],
              ),
              SizedBox(height: tokens.space24),
              const _Section(title: '照片', children: [PhotoGrid()]),
              SizedBox(height: tokens.space24),
              // 语音自我介绍(批次 R,与聊天语音共用录音链路):属 E-5.4 已交付的
              // 组件,本单只把它放进新的页面骨架里,内部一行未动。
              const ProfileVoiceCard(),
            ],
          );
        },
      ),
    );
  }
}

/// 分组卡:标题 17/w600 + `EmberCard` 内 16 间距的一列字段(§5.2 卡片内间距)。
class _Section extends StatelessWidget {
  const _Section({required this.title, required this.children});

  final String title;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // 标题与内容 12(§5.2);与 E-5.6a 的引导页分组卡同一口径。
        Padding(
          padding: EdgeInsets.only(bottom: tokens.space12),
          child: Text(
            title,
            style: AppText.subtitle.copyWith(color: colors.textPrimary),
          ),
        ),
        EmberCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              for (var i = 0; i < children.length; i++) ...[
                if (i > 0) SizedBox(height: tokens.space16),
                children[i],
              ],
            ],
          ),
        ),
      ],
    );
  }
}

/// 加载态骨架:三块「标题 + 卡片」(`surface.sunken` 色块,§8.3 骨架)。
class _EditSkeleton extends StatelessWidget {
  const _EditSkeleton();

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (var block = 0; block < 3; block++) ...[
          if (block > 0) SizedBox(height: tokens.space24),
          const EmberSkeleton(width: 96, height: tokens.fontSizeSubtitle),
          SizedBox(height: tokens.space12),
          // 一张卡片的高度:两个 52 控件 + 间距 + 上下内边距 20。
          const EmberSkeleton(
            height: tokens.sizeControlHeight * 2 +
                tokens.space16 +
                tokens.space20 * 2,
            radius: tokens.radiusLg,
          ),
        ],
      ],
    );
  }
}
