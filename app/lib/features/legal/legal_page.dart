import 'package:flutter/material.dart';

import 'legal_texts.dart';

class LegalPage extends StatelessWidget {
  const LegalPage.agreement({super.key}) : _title = '用户协议', _text = userAgreementText;

  const LegalPage.privacy({super.key}) : _title = '隐私政策', _text = privacyPolicyText;

  final String _title;
  final String _text;

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: Text(_title)),
        body: SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: Text(_text, style: const TextStyle(height: 1.6)),
        ),
      );
}
