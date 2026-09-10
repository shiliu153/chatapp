import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/discovery/models.dart';
import 'package:chatapp_app/features/discovery/widgets/swipe_deck.dart';

import '../../support/sample_data.dart';

List<Candidate> _candidates() => [
      Candidate.fromJson(candidateJson(userId: 9, nickname: '小红')),
      Candidate.fromJson(candidateJson(userId: 10, nickname: '小刚')),
      Candidate.fromJson(candidateJson(userId: 11, nickname: '小美')),
    ];

/// 最小宿主:收到滑卡结果就从卡组去掉一张(模仿页面的行为)。
class _Host extends StatefulWidget {
  const _Host({required this.decisions, this.matched = false});

  final List<String> decisions;
  final bool matched;

  @override
  State<_Host> createState() => _HostState();
}

class _HostState extends State<_Host> {
  final List<Candidate> _left = _candidates();

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      home: Scaffold(
        body: SwipeDeck(
          candidates: _left,
          onDecide: (candidate, {required like}) async {
            widget.decisions.add('${candidate.userId}:${like ? 'like' : 'pass'}');
            setState(() => _left.removeAt(0));
            return widget.matched;
          },
        ),
      ),
    );
  }
}

void main() {
  testWidgets('右滑超过阈值 → 判定 like,下一张升为顶层', (tester) async {
    final decisions = <String>[];
    await tester.pumpWidget(_Host(decisions: decisions));
    await tester.pump();

    await tester.drag(find.byKey(const Key('deck.topCard')), const Offset(400, 0));
    await tester.pumpAndSettle();

    expect(decisions, ['9:like']);
    expect(find.text('小红,25'), findsNothing);
    expect(find.text('小刚,25'), findsOneWidget);
  });

  testWidgets('左滑 → 判定 pass', (tester) async {
    final decisions = <String>[];
    await tester.pumpWidget(_Host(decisions: decisions));
    await tester.pump();

    await tester.drag(find.byKey(const Key('deck.topCard')), const Offset(-400, 0));
    await tester.pumpAndSettle();

    expect(decisions, ['9:pass']);
  });

  testWidgets('拖动不到阈值 → 弹回,不算一次滑卡', (tester) async {
    final decisions = <String>[];
    await tester.pumpWidget(_Host(decisions: decisions));
    await tester.pump();

    await tester.drag(find.byKey(const Key('deck.topCard')), const Offset(60, 0));
    await tester.pumpAndSettle();

    expect(decisions, isEmpty);
    expect(find.text('小红,25'), findsOneWidget);
  });

  testWidgets('♥/✕ 按钮等价于滑卡', (tester) async {
    final decisions = <String>[];
    await tester.pumpWidget(_Host(decisions: decisions));
    await tester.pump();

    await tester.tap(find.byKey(const Key('discovery.like')));
    await tester.pumpAndSettle();
    expect(decisions, ['9:like']);

    await tester.tap(find.byKey(const Key('discovery.pass')));
    await tester.pumpAndSettle();
    expect(decisions, ['9:like', '10:pass']);
  });
}
