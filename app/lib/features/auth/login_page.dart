import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/providers.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_brand_mark.dart';
import '../../core/widgets/app_button.dart';
import '../../core/widgets/app_section_card.dart';
import '../../core/widgets/app_text_action.dart';
import '../../core/widgets/app_text_field.dart';
import '../../core/widgets/app_toast.dart';
import 'auth_repository.dart';
import 'session.dart';

/// 登录页(附录 E):静态品牌区 + 表单卡 + 渐变主按钮。
/// 品牌区**静态无动画** —— 本页有大量 pumpAndSettle 用例(附录 E.3)。
class LoginPage extends ConsumerStatefulWidget {
  const LoginPage({super.key});

  @override
  ConsumerState<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends ConsumerState<LoginPage> {
  static final _phonePattern = RegExp(r'^1[3-9]\d{9}$');

  final _phoneController = TextEditingController();
  final _codeController = TextEditingController();
  Timer? _timer;
  int _countdown = 0;
  bool _sending = false;
  bool _submitting = false;

  @override
  void initState() {
    super.initState();
    // 被踢/强退带过来的原因(一次性信号):首帧后提示,让用户知道为什么被退出
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final reason = ref.read(tokenStoreProvider).takeForceLogoutReason();
      if (reason != null) AppToast.show(context, reason);
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _phoneController.dispose();
    _codeController.dispose();
    super.dispose();
  }

  Future<void> _sendCode() async {
    final phone = _phoneController.text.trim();
    if (!_phonePattern.hasMatch(phone)) {
      AppToast.show(context, '请输入正确的手机号');
      return;
    }
    setState(() => _sending = true);
    try {
      await ref.read(authRepositoryProvider).sendSms(phone);
      if (!mounted) return;
      _startCountdown();
      AppToast.show(context, '验证码已发送,请查看短信');
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  void _startCountdown() {
    _timer?.cancel();
    setState(() => _countdown = 60);
    _timer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (!mounted) {
        timer.cancel();
        return;
      }
      if (_countdown <= 1) {
        timer.cancel();
        setState(() => _countdown = 0);
      } else {
        setState(() => _countdown -= 1);
      }
    });
  }

  Future<void> _submit() async {
    final phone = _phoneController.text.trim();
    final code = _codeController.text.trim();
    if (!_phonePattern.hasMatch(phone)) {
      AppToast.show(context, '请输入正确的手机号');
      return;
    }
    if (code.length != 6) {
      AppToast.show(context, '请输入 6 位验证码');
      return;
    }
    setState(() => _submitting = true);
    try {
      final result = await ref.read(sessionProvider.notifier).login(phone, code);
      if (!mounted) return;
      context.go(result.isNewUser ? '/onboarding' : '/home');
    } on ApiException catch (error) {
      if (mounted) {
        AppToast.show(
          context,
          error.statusCode == null ? '网络超时,可直接再次点击「登录」重试' : error.message,
        );
      }
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.bgPage,
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(AppSpacing.xxl),
          children: [
            const SizedBox(height: AppSpacing.xxl),
            const Center(child: AppBrandMark(key: Key('login.brand'))),
            const SizedBox(height: AppSpacing.lg),
            Text('交友 Chat',
                textAlign: TextAlign.center,
                style: AppText.display.copyWith(color: AppColors.text1)),
            const SizedBox(height: AppSpacing.xs),
            Text('手机号登录 / 注册',
                textAlign: TextAlign.center,
                style: AppText.caption.copyWith(color: AppColors.text2)),
            const SizedBox(height: AppSpacing.xxl),
            AppSectionCard(
              children: [
                AppTextField(
                  key: const Key('login.phone'),
                  controller: _phoneController,
                  label: '手机号',
                  keyboardType: TextInputType.phone,
                  maxLength: 11,
                ),
                AppTextField(
                  key: const Key('login.code'),
                  controller: _codeController,
                  label: '验证码',
                  keyboardType: TextInputType.number,
                  maxLength: 6,
                  suffix: AppTextAction(
                    key: const Key('login.sendCode'),
                    label: _countdown > 0 ? '$_countdown 秒后重发' : '获取验证码',
                    onPressed: (_sending || _countdown > 0) ? null : _sendCode,
                  ),
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.xxl),
            AppButton(
              key: const Key('login.submit'),
              label: _submitting ? '登录中…' : '登录 / 注册',
              onPressed: _submitting ? null : _submit,
            ),
            const SizedBox(height: AppSpacing.lg),
            if (kDebugMode)
              Text('开发模式:验证码固定 123456',
                  textAlign: TextAlign.center,
                  style: AppText.micro.copyWith(color: AppColors.text3)),
          ],
        ),
      ),
    );
  }
}
