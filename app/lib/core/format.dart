String formatDate(DateTime date) =>
    '${date.year.toString().padLeft(4, '0')}-'
    '${date.month.toString().padLeft(2, '0')}-'
    '${date.day.toString().padLeft(2, '0')}';

DateTime? parseDate(String? text) =>
    (text == null || text.isEmpty) ? null : DateTime.parse(text);

/// 消息时间:今天显示 HH:mm,更早显示 MM-dd。
String formatMessageTime(DateTime time) {
  final now = DateTime.now();
  final sameDay = time.year == now.year && time.month == now.month && time.day == now.day;
  if (sameDay) {
    return '${time.hour.toString().padLeft(2, '0')}:${time.minute.toString().padLeft(2, '0')}';
  }
  return '${time.month.toString().padLeft(2, '0')}-${time.day.toString().padLeft(2, '0')}';
}

/// 聊天页时间条:今天 HH:mm / 昨天 HH:mm / 本年 M月d日 HH:mm / 跨年 yyyy年M月d日 HH:mm。
String formatChatTimestamp(DateTime time, {DateTime? now}) {
  final n = now ?? DateTime.now();
  final hm =
      '${time.hour.toString().padLeft(2, '0')}:${time.minute.toString().padLeft(2, '0')}';
  final today = DateTime(n.year, n.month, n.day);
  final day = DateTime(time.year, time.month, time.day);
  if (day == today) return hm;
  if (day == today.subtract(const Duration(days: 1))) return '昨天 $hm';
  if (time.year == n.year) return '${time.month}月${time.day}日 $hm';
  return '${time.year}年${time.month}月${time.day}日 $hm';
}

/// 动态相对时间:刚刚 / x 分钟前 / x 小时前 / x 天前(7 天内)/ M 月 d 日 / yyyy 年 M 月 d 日。
String formatPostTime(DateTime time, {DateTime? now}) {
  final n = now ?? DateTime.now();
  final diff = n.difference(time);
  if (diff.inMinutes < 1) return '刚刚';
  if (diff.inMinutes < 60) return '${diff.inMinutes} 分钟前';
  if (diff.inHours < 24) return '${diff.inHours} 小时前';
  if (diff.inDays < 7) return '${diff.inDays} 天前';
  if (time.year == n.year) return '${time.month} 月 ${time.day} 日';
  return '${time.year} 年 ${time.month} 月 ${time.day} 日';
}

/// 最后活跃:刚刚 / x 分钟前 / x 小时前 / x 天前(在线状态文案用;7 天外数据已过期)。
String formatLastActive(DateTime time, {DateTime? now}) {
  final diff = (now ?? DateTime.now()).difference(time);
  if (diff.inMinutes < 1) return '刚刚';
  if (diff.inMinutes < 60) return '${diff.inMinutes} 分钟前';
  if (diff.inHours < 24) return '${diff.inHours} 小时前';
  return '${diff.inDays} 天前';
}
