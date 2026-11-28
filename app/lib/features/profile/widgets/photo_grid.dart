import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../../core/api_exception.dart';
import '../../../core/image_pick.dart';
import '../../../core/theme/ember_theme_context.dart';
import '../../../core/theme/tokens.g.dart' as tokens;
import '../../../core/ui/ember_ui.dart';
import '../models.dart';
import '../profile_controller.dart';
import '../profile_repository.dart';

/// 单张照片上限 5MB(与后端 `config/images.py` 的上限一致,本地先拦一次)。
const _maxBytes = 5 * 1024 * 1024;

/// 资料照片网格(E-5.6c 换皮):3 列、`radius.sm` 12、间距 8;最多 [maxCount] 张。
///
/// **交互一行未动**(page spec §7 第 4 条「只换皮」):加号格选图上传、每张右上角删除钮
/// 二次确认、未过审的照片在左下角带状态角标。改版前就没有拖动排序,本单也不新增
/// (新增排序能力属功能改动),所以读屏按事实播报:
/// - 照片格「第 N 张照片」,未过审时补一句状态(颜色不是唯一线索,§8.4);
/// - 删除钮「删除第 N 张照片」;
/// - 加号格「添加照片」。
class PhotoGrid extends ConsumerStatefulWidget {
  /// 构造照片网格。
  const PhotoGrid({super.key, this.pickImage = pickImageFromGallery, this.maxCount = 6});

  /// 测试注入用;默认打开系统相册。
  final PickImage pickImage;

  /// 最多几张。
  final int maxCount;

  @override
  ConsumerState<PhotoGrid> createState() => _PhotoGridState();
}

class _PhotoGridState extends ConsumerState<PhotoGrid> {
  bool _busy = false;

  Future<void> _add() async {
    final file = await widget.pickImage();
    if (file == null) return;
    final bytes = await file.readAsBytes();
    if (!mounted) return;
    if (bytes.length > _maxBytes) {
      EmberToast.show(context, '图片不能超过 5MB');
      return;
    }
    setState(() => _busy = true);
    try {
      await ref.read(profileRepositoryProvider).uploadPhoto(bytes, file.name);
      await ref.read(profileProvider.notifier).reload();
    } on ApiException catch (error) {
      if (mounted) EmberToast.show(context, error.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _confirmDelete(Photo photo) async {
    final confirmed = await showEmberDialog(
      context,
      icon: PhosphorIconsRegular.trash,
      title: '删除这张照片?',
      message: '删除后不再出现在你的资料里。',
      confirmLabel: '删除',
      danger: true,
    );
    if (!confirmed || !mounted) return;
    try {
      await ref.read(profileRepositoryProvider).deletePhoto(photo.id);
      await ref.read(profileProvider.notifier).reload();
    } on ApiException catch (error) {
      if (mounted) EmberToast.show(context, error.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final photos = ref.watch(profileProvider).value?.photos ?? const <Photo>[];
    return GridView.count(
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      crossAxisCount: 3,
      mainAxisSpacing: tokens.space8,
      crossAxisSpacing: tokens.space8,
      children: [
        for (var i = 0; i < photos.length; i++)
          _PhotoTile(
            index: i + 1,
            photo: photos[i],
            onDelete: () => _confirmDelete(photos[i]),
          ),
        if (photos.length < widget.maxCount)
          _AddTile(busy: _busy, onTap: _busy ? null : _add),
      ],
    );
  }
}

/// 一张照片:圆角 12 的方图 + 左下角审核状态角标 + 右上角删除钮。
class _PhotoTile extends StatelessWidget {
  const _PhotoTile({
    required this.index,
    required this.photo,
    required this.onDelete,
  });

  /// 第几张(从 1 开始,读屏用)。
  final int index;

  /// 照片数据。
  final Photo photo;

  /// 删除回调。
  final VoidCallback onDelete;

  /// 审核状态文案;已过审时为空。
  String get _statusText =>
      photo.isApproved ? '' : (photo.status == 'pending' ? '待审核' : '已驳回');

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final status = _statusText;
    return Semantics(
      container: true,
      // 「第 N 张照片」是 page spec §6 第 3 条的口径;未过审再补状态(§8.4)。
      label: status.isEmpty ? '第 $index 张照片' : '第 $index 张照片，$status',
      child: Stack(
        fit: StackFit.expand,
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(tokens.radiusSm),
            child: Image.network(
              photo.url,
              fit: BoxFit.cover,
              errorBuilder: (context, error, stack) => ColoredBox(
                color: colors.surfaceSunken,
                child: Center(
                  child: Icon(
                    PhosphorIconsRegular.imageBroken,
                    size: tokens.sizeIcon24,
                    color: colors.textTertiary,
                  ),
                ),
              ),
            ),
          ),
          if (status.isNotEmpty)
            Positioned(
              left: tokens.space4,
              bottom: tokens.space4,
              child: _StatusBadge(
                text: status,
                danger: photo.status != 'pending',
              ),
            ),
          Positioned(
            right: 0,
            top: 0,
            child: EmberPressable(
              key: Key('photo.delete.${photo.id}'),
              semanticLabel: '删除第 $index 张照片',
              onTap: onDelete,
              borderRadius: BorderRadius.circular(tokens.radiusSm),
              builder: (context, state) => SizedBox(
                // 热区 48(§8.4「图标本体可以小,热区不能缩」),徽标 24 居中。
                width: tokens.sizeTouchApp,
                height: tokens.sizeTouchApp,
                child: Center(child: _RemoveBadge(pressed: state.pressed)),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// 审核状态角标(`status.warning` 待审 / `status.danger` 驳回,文字取 `on` 色)。
class _StatusBadge extends StatelessWidget {
  const _StatusBadge({required this.text, required this.danger});

  final String text;
  final bool danger;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return ExcludeSemantics(
      child: Container(
        padding: EdgeInsets.symmetric(
          horizontal: tokens.space8,
          vertical: tokens.space4,
        ),
        decoration: BoxDecoration(
          color: danger ? colors.statusDanger : colors.statusWarning,
          borderRadius: BorderRadius.circular(tokens.radiusXs),
        ),
        child: Text(
          text,
          style: TextStyle(
            fontSize: tokens.fontSizeMicro,
            height: tokens.fontLineHeightMicro,
            color: danger ? colors.statusOnDanger : colors.statusOnWarning,
          ),
        ),
      ),
    );
  }
}

/// 半透明深底圆 + 白叉(照片右上角删除钮)。
///
/// 发动态选图另有一份同款私有副本 —— 不跨 feature import(几十行不值得建依赖)。
class _RemoveBadge extends StatelessWidget {
  const _RemoveBadge({required this.pressed});

  /// 是否按下(按下时底更深一档,给出可感知的反馈)。
  final bool pressed;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return Container(
      width: tokens.sizeIcon24,
      height: tokens.sizeIcon24,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        color: colors.overlayScrim.withValues(alpha: pressed ? 0.75 : 0.55),
      ),
      child: Icon(
        PhosphorIconsRegular.x,
        size: tokens.sizeIcon16,
        // `overlay.scrim` 在明暗两套里都是深底,前景必须固定取白(`overlay.on`);
        // `EmberColors` 目前没有暴露这一档,沿用 `EmberToast` 在 scrim 上用白字的
        // 同一口径,已记入 PR「遗留」。
        color: Colors.white,
      ),
    );
  }
}

/// 加号格:`surface.sunken` 底 + 1px `border.divider` 描边,上传中显示转圈。
class _AddTile extends StatelessWidget {
  const _AddTile({required this.busy, required this.onTap});

  /// 是否正在上传。
  final bool busy;

  /// 点击回调;`null` 即不可点(上传中)。
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return EmberPressable(
      key: const Key('photo.add'),
      semanticLabel: '添加照片',
      onTap: onTap,
      borderRadius: BorderRadius.circular(tokens.radiusSm),
      builder: (context, state) => DecoratedBox(
        decoration: BoxDecoration(
          color: colors.surfaceSunken,
          borderRadius: BorderRadius.circular(tokens.radiusSm),
          border: Border.all(color: colors.borderDivider),
        ),
        child: Center(
          child: busy
              ? SizedBox(
                  width: tokens.sizeIcon20,
                  height: tokens.sizeIcon20,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    color: colors.brandDefault,
                  ),
                )
              : Icon(
                  PhosphorIconsRegular.plus,
                  size: tokens.sizeIcon24,
                  color: colors.textTertiary,
                ),
        ),
      ),
    );
  }
}
