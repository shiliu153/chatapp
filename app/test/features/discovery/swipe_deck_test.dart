import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/discovery/models.dart';
import 'package:chatapp_app/features/discovery/widgets/swipe_deck.dart';

import '../../support/sample_data.dart';
import '../../support/heart_theme.dart';

List<Candidate> _candidates() => [
      Candidate.fromJson(candidateJson(userId: 9, nickname: '小红')),
      Candidate.fromJson(candidateJson(userId: 10, nickname: '小刚')),
      Candidate.fromJson(candidateJson(userId: 11, nickname: '小美')),
    ];

/// 最小宿主:收到滑卡结果就从卡组去掉一张(模仿页面的行为)。
class _Host extends StatefulWidget {
  const _Host({required this.decisions});

  final List<String> decisions;

  @override
  State<_Host> createState() => _HostState();
}

class _HostState extends State<_Host> {
  final List<Candidate> _left = _candidates();

  @override
  Widget build(BuildContext context) {
    return MaterialApp(theme: heartTheme, 
      home: Scaffold(
        body: SwipeDeck(
          candidates: _left,
          onDecide: (candidate, {required like}) async {
            widget.decisions.add('${candidate.userId}:${like ? 'like' : 'pass'}');
            setState(() => _left.removeAt(0));
            return false;
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

  testWidgets('喜欢钮没有心跳脉冲:点下去只有一次按压反馈,没有循环缩放', (tester) async {
    // E-5.2 page spec §7.3 / 拍板 2:装饰性循环动画一律取消(只留在线点呼吸与骨架屏)。
    // 旧用例断言的是 1→1.25→1 的脉冲,现在改成「脉冲键不存在 + 按压弹簧会收敛回 1」。
    final decisions = <String>[];
    await tester.pumpWidget(_Host(decisions: decisions));
    await tester.pump();

    expect(find.byKey(const Key('deck.pulse')), findsNothing);

    await tester.tap(find.byKey(const Key('discovery.like')));
    await tester.pump(); // ticker 基线帧
    await tester.pump(const Duration(milliseconds: 60));

    final likeButton = find.byKey(const Key('discovery.like'));
    expect(tester.getSize(likeButton), const Size(64, 64)); // 主操作大档

    // 弹簧收敛后(没有脉冲残留)缩放回到 1:残留循环动画会让这里持续 ≠ 1
    await tester.pump(const Duration(milliseconds: 600));
    final transform = tester.widget<Transform>(
      find.descendant(of: likeButton, matching: find.byType(Transform)).first,
    );
    expect(transform.transform.storage[0], closeTo(1.0, 0.01));
  });

  testWidgets('喜欢 / 跳过两钮都有读屏标签(§8.4 图标按钮必须有 label)', (tester) async {
    final decisions = <String>[];
    await tester.pumpWidget(_Host(decisions: decisions));
    await tester.pump();
    // 语义节点由 `EmberPressable` 的 `Semantics(label:)` 提供:直接读组件声明的
    // label(卡片上的「喜欢爬山」也是同一批文字,按 label 搜索会撞上,不能用来断言)
    String labelOf(String key) => tester
        .widget<Semantics>(
          find
              .descendant(of: find.byKey(Key(key)), matching: find.byType(Semantics))
              .first,
        )
        .properties
        .label!;

    expect(labelOf('discovery.like'), '喜欢');
    expect(labelOf('discovery.pass'), '跳过');
  });
}
