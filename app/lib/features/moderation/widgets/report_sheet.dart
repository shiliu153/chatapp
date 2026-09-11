import 'package:flutter/material.dart';

/// 举报类型:值与后端 ReportType 对齐。
const reportTypes = [
  ('harassment', '骚扰'),
  ('porn', '色情'),
  ('fraud', '诈骗'),
  ('other', '其他'),
];

/// 底部弹窗;提交时 pop 出 `(type, detail)`,取消 pop null。
class ReportSheet extends StatefulWidget {
  const ReportSheet({super.key});

  @override
  State<ReportSheet> createState() => _ReportSheetState();
}

class _ReportSheetState extends State<ReportSheet> {
  String? _type;
  final _detail = TextEditingController();

  @override
  void dispose() {
    _detail.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.fromLTRB(16, 16, 16, 16 + MediaQuery.viewInsetsOf(context).bottom),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('举报', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 4),
          for (final (value, label) in reportTypes)
            ListTile(
              key: Key('report.type.$value'),
              contentPadding: EdgeInsets.zero,
              title: Text(label),
              trailing: _type == value ? const Icon(Icons.check, color: Colors.pink) : null,
              onTap: () => setState(() => _type = value),
            ),
          TextField(
            key: const Key('report.detail'),
            controller: _detail,
            maxLength: 200,
            decoration: const InputDecoration(labelText: '补充说明(可选)'),
          ),
          const SizedBox(height: 8),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              key: const Key('report.submit'),
              onPressed: _type == null
                  ? null
                  : () => Navigator.pop(context, (type: _type!, detail: _detail.text.trim())),
              child: const Text('提交举报'),
            ),
          ),
        ],
      ),
    );
  }
}
