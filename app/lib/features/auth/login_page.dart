import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/providers.dart';
import 'auth_repository.dart';
import 'session.dart';

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
      if (reason != null) _show(reason);
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _phoneController.dispose();
    _codeController.dispose();
    super.dispose();
  }

  void _show(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _sendCode() async {
    final phone = _phoneController.text.trim();
    if (!_phonePattern.hasMatch(phone)) {
      _show('请输入正确的手机号');
      return;
    }
    setState(() => _sending = true);
    try {
      await ref.read(authRepositoryProvider).sendSms(phone);
      if (!mounted) return;
      _startCountdown();
      _show('验证码已发送,请查看短信');
    } on ApiException catch (error) {
      if (mounted) _show(error.message);
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
      _show('请输入正确的手机号');
      return;
    }
    if (code.length != 6) {
      _show('请输入 6 位验证码');
      return;
    }
    setState(() => _submitting = true);
    try {
      final result = await ref.read(sessionProvider.notifier).login(phone, code);
      if (!mounted) return;
      context.go(result.isNewUser ? '/onboarding' : '/home');
    } on ApiException catch (error) {
      if (mounted) {
        _show(error.statusCode == null ? '网络超时,可直接再次点击「登录」重试' : error.message);
      }
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(24),
          children: [
            const SizedBox(height: 60),
            Text('交友 Chat',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.headlineMedium),
            const SizedBox(height: 8),
            const Text('手机号登录 / 注册', textAlign: TextAlign.center),
            const SizedBox(height: 40),
            TextField(
              key: const Key('login.phone'),
              controller: _phoneController,
              keyboardType: TextInputType.phone,
              maxLength: 11,
              decoration: const InputDecoration(
                labelText: '手机号',
                counterText: '',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    key: const Key('login.code'),
                    controller: _codeController,
                    keyboardType: TextInputType.number,
                    maxLength: 6,
                    decoration: const InputDecoration(
                      labelText: '验证码',
                      counterText: '',
                      border: OutlineInputBorder(),
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                SizedBox(
                  width: 130,
                  height: 56,
                  child: OutlinedButton(
                    key: const Key('login.sendCode'),
                    onPressed: (_sending || _countdown > 0) ? null : _sendCode,
                    child: Text(_countdown > 0 ? '$_countdown 秒后重发' : '获取验证码'),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 24),
            FilledButton(
              key: const Key('login.submit'),
              onPressed: _submitting ? null : _submit,
              child: Text(_submitting ? '登录中…' : '登录 / 注册'),
            ),
            const SizedBox(height: 16),
            if (kDebugMode)
              const Text('开发模式:验证码固定 123456',
                  textAlign: TextAlign.center, style: TextStyle(color: Colors.grey)),
          ],
        ),
      ),
    );
  }
}
