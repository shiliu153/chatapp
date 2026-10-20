/// 撤回规则:腾讯 IM 默认只允许撤回 2 分钟内的消息。
///
/// 前端先判一次,是为了「超时就不显示撤回项」,避免用户点下去才报错;
/// 真正的时限仍由服务端强制,超时调用会抛 [ImException]。
library;

import '../../im/im_client.dart';

/// 撤回窗口(与腾讯控制台默认值一致)。
const recallWindow = Duration(minutes: 2);

/// 这条消息当前能否撤回。
///
/// Args:
///   message: 待判断的消息。
///   now: 参照时间(测试注入;默认取当前时间)。
///
/// Returns:
///   自己发的、文字或图片、非发送中/失败/已撤回、且距发送不超过 [recallWindow] 时为 `true`。
bool canRecall(ChatMessage message, {DateTime? now}) {
  if (!message.isSelf || message.isRevoked) return false;
  if (message.isPending || message.isFailed) return false;
  if (message.kind != ChatMessageKind.text && message.kind != ChatMessageKind.image) return false;
  final at = DateTime.fromMillisecondsSinceEpoch(message.timestamp);
  final current = now ?? DateTime.now();
  final age = current.difference(at);
  return !age.isNegative && age <= recallWindow;
}
