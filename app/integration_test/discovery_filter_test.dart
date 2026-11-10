// 真机判定:筛选面板「滚动区里的控件能收到真实指针事件」(issue #213 P0)。
//
// 为什么单开一条:**widget 测试抓不住这类问题**。`tester.tap` 在 800×600 的测试窗口
// 里跑,面板往往不需要滚动;真机是 411×914dp,面板的滚动视口只有 ~400dp 高。
// 一旦布局把视口压成 0(或者控件画在视口外),控件会「画得出来、点不动」——
// 在单测里照样绿,在模拟器上手点全死。这条用例专门在真实设备布局上钉三件事:
//
// 1. 滚动视口有可用的高度(不是被压扁的 0);
// 2. 点在 chip 上,**通过真实 hit test** 能把它切成选中态,并且换算进「应用」后的筛选;
// 3. 拖 RangeSlider 能改年龄区间,同样换算进筛选。
//
// 与 `smoke_test.dart` 同一条轨(`.github/workflows/app-ui.yml` 的 app-ui),
// 后端**不可达**也不影响:标签池用 `tagsProvider` 覆盖成固定值,不碰网络。

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import 'package:chatapp_app/core/theme/app_theme.dart';
import 'package:chatapp_app/features/discovery/models.dart';
import 'package:chatapp_app/features/discovery/widgets/discovery_filter_sheet.dart';
import 'package:chatapp_app/features/profile/models.dart';
import 'package:chatapp_app/features/profile/profile_controller.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('筛选面板:滚动区里的 chip 与滑块都能收到真实指针事件', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          // 不碰网络:标签池固定成 6 个(与真机上的 12 个同样会换行)
          tagsProvider.overrideWith((ref) async => const [
                Tag(id: 1, name: '旅行'),
                Tag(id: 2, name: '读书'),
                Tag(id: 3, name: '电影'),
                Tag(id: 4, name: '音乐'),
                Tag(id: 5, name: '美食'),
                Tag(id: 6, name: '摄影'),
              ]),
        ],
        child: MaterialApp(
          theme: buildAppTheme(brightness: Brightness.light),
          home: const _SheetHost(),
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('host.open')));
    await tester.pumpAndSettle();
    expect(find.text('筛选'), findsOneWidget);

    // ① 滚动视口必须有真实高度 —— 视口塌成 0 时控件「画得出来但点不动」,
    //    这正是 issue #213 报的现象,所以先在设备上把它量出来。
    final scrollView = find.descendant(
      of: find.byType(DiscoveryFilterSheet),
      matching: find.byType(SingleChildScrollView),
    );
    expect(scrollView, findsOneWidget);
    final viewport = tester.renderObject<RenderBox>(scrollView);
    expect(viewport.size.height, greaterThan(100),
        reason: '滚动视口只有 ${viewport.size.height},内容会被画在视口外 → 整块点不动');

    // ② chip 在滚动区内:点它必须变成选中态(选中后「应用」带出 tag_ids)
    await tester.tap(find.text('音乐'));
    await tester.pumpAndSettle();

    // ③ RangeSlider 也在滚动区内:从**右端**往左拖,上限必须变小。
    //    必须从右端抓:RangeSlider 抓「离按下点最近的滑块」,从中间按会抓到左滑块
    //    (已经在最小值 18,再往左拖不动),看起来就像「拖了没反应」。
    final sliderRect = tester.getRect(find.byType(RangeSlider));
    await tester.dragFrom(
        Offset(sliderRect.right - 30, sliderRect.center.dy), const Offset(-140, 0));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('filter.apply')));
    await tester.pumpAndSettle();

    expect(tester.widget<Text>(find.byKey(const Key('applied.tags'))).data, 'tags=4',
        reason: 'chip 没收到指针事件(点了还是未选中)');
    final age = tester.widget<Text>(find.byKey(const Key('applied.age'))).data!;
    expect(age, isNot('age=null-null'),
        reason: '滑块没收到指针事件:年龄区间仍等于偏好(18–99),所以一个参数都没发');
    final maxAge = int.parse(age.split('-').last);
    expect(maxAge, isNot(99), reason: '滑块没收到指针事件:age_max 仍是偏好上限 99($age)');
  });
}

/// 打开面板的宿主:把「应用」拿到的筛选原样显示出来,好让用例断言结果。
class _SheetHost extends StatefulWidget {
  const _SheetHost();

  @override
  State<_SheetHost> createState() => _SheetHostState();
}

class _SheetHostState extends State<_SheetHost> {
  DiscoveryFilter _applied = DiscoveryFilter.none;

  Future<void> _open() async {
    final picked = await showDiscoveryFilterSheet(
      context,
      preference: const Preference(ageMin: 18, ageMax: 99),
      initial: DiscoveryFilter.none,
    );
    if (picked == null || !mounted) return;
    setState(() => _applied = picked);
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        body: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              ElevatedButton(
                key: const Key('host.open'),
                onPressed: _open,
                child: const Text('打开筛选'),
              ),
              Text('tags=${_applied.tagIds.join(",")}', key: const Key('applied.tags')),
              Text('age=${_applied.ageMin}-${_applied.ageMax}',
                  key: const Key('applied.age')),
            ],
          ),
        ),
      );
}
