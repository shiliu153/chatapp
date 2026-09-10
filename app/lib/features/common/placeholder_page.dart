import 'package:flutter/material.dart';

/// 还没有实现的页面占位;真页面上线后连同路由一起替换。
class PlaceholderPage extends StatelessWidget {
  const PlaceholderPage({super.key, required this.title});

  final String title;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(title)),
      body: Center(child: Text('$title 施工中')),
    );
  }
}
