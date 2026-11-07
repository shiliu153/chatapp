/// 撤回规则:只允许撤回 2 分钟内的消息(与 imserver 的实现一致)。
///
/// 前端先判一次,是为了「超时就不显示撤回项」,避免用户点下去才报错;
/// 真正的时限仍由服务端强制,超时调用会抛 [ImException]。
library;

import '../../im/im_client.dart';

/// 撤回窗口(与 imserver 的校验一致)。
const recallWindow = Duration(minutes: 2);

/// 这条消息当前能否撤回。
///
/// Args:
///   message: 待判断的消息。
///   now: 参照时间(测试注入;默认取当前时间)。
///
/// Returns:
///   自己发的、文字/图片/贴纸、非发送中/失败/已撤回、且距发送不超过 [recallWindow] 时为 `true`。
///
/// 贴纸也算(批次 J):它是一条普通消息,发错了同样要能撤回。语音仍不支持撤回
/// —— 与既有行为保持一致,不在本批扩大范围。
bool canRecall(ChatMessage message, {DateTime? now}) {
  if (!message.isSelf || message.isRevoked) return false;
  if (message.isPending || message.isFailed) return false;
  if (message.kind != ChatMessageKind.text &&
      message.kind != ChatMessageKind.image &&
      message.kind != ChatMessageKind.sticker) {
    return false;
  }
  final at = DateTime.fromMillisecondsSinceEpoch(message.timestamp);
  final current = now ?? DateTime.now();
  final age = current.difference(at);
  return !age.isNegative && age <= recallWindow;
}
