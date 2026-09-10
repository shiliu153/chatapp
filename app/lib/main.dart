import 'package:flutter/material.dart';

import 'core/api_client.dart';

const String apiBase = String.fromEnvironment('API_BASE',
    defaultValue: 'http://127.0.0.1:8000/api/v1');

void main() {
  runApp(const ChatApp());
}

class ChatApp extends StatelessWidget {
  const ChatApp({super.key, this.api});
  final ApiClient? api; // 测试注入用;不传则 HomePage 用真实 ApiClient

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '交友 Chat',
      theme: ThemeData(colorSchemeSeed: Colors.pink, useMaterial3: true),
      home: HomePage(api: api),
    );
  }
}

class HomePage extends StatefulWidget {
  const HomePage({super.key, this.api});
  final ApiClient? api; // 测试注入用

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  late final ApiClient _api = widget.api ?? ApiClient(baseUrl: apiBase);
  late Future<String> _health = _api.health();

  void _retry() {
    setState(() {
      _health = _api.health();
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('交友 Chat — M0 握手')),
      body: Center(
        child: FutureBuilder<String>(
          future: _health,
          builder: (context, snapshot) {
            if (snapshot.connectionState != ConnectionState.done) {
              return const CircularProgressIndicator();
            }
            if (snapshot.hasError) {
              return Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Text('后端连接失败', style: TextStyle(fontSize: 20)),
                  Text('${snapshot.error}', textAlign: TextAlign.center),
                  const SizedBox(height: 12),
                  FilledButton(onPressed: _retry, child: const Text('重试')),
                ],
              );
            }
            return Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.check_circle, color: Colors.green, size: 48),
                const Text('后端连接成功', style: TextStyle(fontSize: 20)),
                Text('status = ${snapshot.data}'),
              ],
            );
          },
        ),
      ),
    );
  }
}
