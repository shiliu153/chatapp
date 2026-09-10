import 'package:flutter/material.dart';

class ChatApp extends StatelessWidget {
  const ChatApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '交友 Chat',
      theme: ThemeData(colorSchemeSeed: Colors.pink, useMaterial3: true),
      home: const Scaffold(body: Center(child: Text('M2a 开发中'))),
    );
  }
}
