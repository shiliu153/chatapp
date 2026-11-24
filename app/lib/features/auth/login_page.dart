import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/providers.dart';
import '../../core/theme/app_typography.dart';
import '../../core/theme/ember_theme_context.dart';
import '../../core/theme/tokens.g.dart' as tokens;
import '../../core/ui/ember_ui.dart';
import 'auth_repository.dart';
import 'ember_brand_mark.dart';
import 'session.dart';

/// 登录页(附录 E):品牌区 + 手机号 / 验证码两步单页 + 主按钮(E-5.6a 迁移到 Ember)。
///
/// **保留「手机号 + 验证码」单页两步**(E-5.6 spec §7 拍板第 3 条):交互与请求链一行未动,
/// 本单只换皮 —— 品牌 mark 去渐变、字段换 [`EmberField`]、按钮换 [`EmberButton`]、
/// 客户端校验的提示从全局 Toast 收进字段下方(§5「表单校验失败不弹全局 Toast」)。
///
/// 品牌区**静态无动画** —— 本页有大量 pumpAndSettle 用例(附录 E.3)。
class LoginPage extends ConsumerStatefulWidget {
  /// 构造登录页。
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

  /// 手机号字段的错误说明(§8.3 error:描边转 `status.danger` **且必须带文字**)。
  String? _phoneError;

  /// 验证码字段的错误说明。
  String? _codeError;

  @override
  void initState() {
    super.initState();
    // 被踢/强退带过来的原因(一次性信号):首帧后提示,让用户知道为什么被退出
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final reason = ref.read(tokenStoreProvider).takeForceLogoutReason();
      if (reason != null) EmberToast.show(context, reason);
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _phoneController.dispose();
    _codeController.dispose();
    super.dispose();
  }

  /// 校验手机号;不合法时把说明落到字段下方,返回 `false`。
  bool _validatePhone() {
    final phone = _phoneController.text.trim();
    final ok = _phonePattern.hasMatch(phone);
    setState(() => _phoneError = ok ? null : '请输入正确的手机号');
    return ok;
  }

  Future<void> _sendCode() async {
    if (!_validatePhone()) return;
    final phone = _phoneController.text.trim();
    setState(() => _sending = true);
    try {
      await ref.read(authRepositoryProvider).sendSms(phone);
      if (!mounted) return;
      _startCountdown();
      EmberToast.show(context, '验证码已发送,请查看短信');
    } on ApiException catch (error) {
      if (mounted) EmberToast.show(context, error.message);
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
    final phoneOk = _validatePhone();
    final code = _codeController.text.trim();
    final codeOk = code.length == 6;
    setState(() => _codeError = codeOk ? null : '请输入 6 位验证码');
    if (!phoneOk || !codeOk) return;

    final phone = _phoneController.text.trim();
    setState(() => _submitting = true);
    try {
      final result = await ref.read(sessionProvider.notifier).login(phone, code);
      if (!mounted) return;
      context.go(result.isNewUser ? '/onboarding' : '/home');
    } on ApiException catch (error) {
      if (mounted) {
        // 服务端错误(码过期 / 网络超时)仍走 Toast:它不是「字段格式不对」,
        // 落到某个字段下方会指错地方(§5「表单校验失败」与「提交失败」是两回事)。
        EmberToast.show(
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
    final colors = context.ember;
    return Scaffold(
      backgroundColor: colors.surfacePage,
      body: SafeArea(
        child: ListView(
          padding: EdgeInsets.symmetric(horizontal: tokens.space20),
          children: [
            SizedBox(height: tokens.space40),
            const Center(child: EmberBrandMark(key: Key('login.brand'))),
            SizedBox(height: tokens.space20),
            Text(
              '交友 Chat',
              textAlign: TextAlign.center,
              style: AppText.display.copyWith(color: colors.textPrimary),
            ),
            SizedBox(height: tokens.space4),
            Text(
              '手机号登录 / 注册',
              textAlign: TextAlign.center,
              style: AppText.caption.copyWith(color: colors.textSecondary),
            ),
            SizedBox(height: tokens.space32),
            EmberField(
              key: const Key('login.phone'),
              controller: _phoneController,
              label: '手机号',
              placeholder: '手机号',
              keyboardType: TextInputType.phone,
              errorText: _phoneError,
            ),
            SizedBox(height: tokens.space12),
            Row(
              // 字段与「获取验证码」按钮顶部对齐:字段出错误说明时字段变高,
              // 按钮不该跟着往下掉。
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: EmberField(
                    key: const Key('login.code'),
                    controller: _codeController,
                    label: '验证码',
                    placeholder: '验证码',
                    keyboardType: TextInputType.number,
                    errorText: _codeError,
                  ),
                ),
                SizedBox(width: tokens.space12),
                EmberButton(
                  key: const Key('login.sendCode'),
                  // 文字按钮(§8.2):`brand.default` 15/w600 无底,最小触控 48。
                  variant: EmberButtonVariant.text,
                  label: _countdown > 0 ? '$_countdown 秒后重发' : '获取验证码',
                  onPressed: (_sending || _countdown > 0) ? null : _sendCode,
                ),
              ],
            ),
            SizedBox(height: tokens.space32),
            EmberButton(
              key: const Key('login.submit'),
              label: '登录 / 注册',
              expand: true,
              loading: _submitting,
              onPressed: _submit,
            ),
            SizedBox(height: tokens.space16),
            if (kDebugMode)
              Text(
                '开发模式:验证码固定 123456',
                textAlign: TextAlign.center,
                style: AppText.micro.copyWith(color: colors.textTertiary),
              ),
          ],
        ),
      ),
    );
  }
}
