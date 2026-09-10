import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_exception.dart';
import '../profile_controller.dart';

class TagSelector extends ConsumerWidget {
  const TagSelector({super.key, required this.selectedIds, required this.onChanged});

  final Set<int> selectedIds;
  final ValueChanged<Set<int>> onChanged;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tags = ref.watch(tagsProvider);
    return tags.when(
      loading: () => const Padding(
        padding: EdgeInsets.all(8),
        child: Center(child: CircularProgressIndicator()),
      ),
      error: (error, _) => Text(error is ApiException ? error.message : '标签加载失败'),
      data: (list) => Wrap(
        spacing: 8,
        runSpacing: 8,
        children: [
          for (final tag in list)
            FilterChip(
              label: Text(tag.name),
              selected: selectedIds.contains(tag.id),
              onSelected: (selected) {
                final next = {...selectedIds};
                if (selected) {
                  next.add(tag.id);
                } else {
                  next.remove(tag.id);
                }
                onChanged(next);
              },
            ),
        ],
      ),
    );
  }
}
