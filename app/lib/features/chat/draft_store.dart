import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 聊天草稿(批次 T-2):**纯客户端**的半成品输入,只在本机、只给自己看。
///
/// 存 `shared_preferences`,key 为 `chat_draft:{peerId}`(peerId 是 IM id,如 `u9`),
/// 与网页端同名前缀,排查时两边能对上。**不写服务端** —— 草稿是「还没决定要不要说」
/// 的内容,上行既要多一套权限/清理逻辑,也会让它离开本机,收益不抵成本
/// (设计取舍见 `docs/superpowers/plans/2026-11-10-batch-t-chat-polish.md` Task 2)。
///
/// 为什么是 `Notifier` 而不是普通工具类:会话列表要按草稿渲染「[草稿] 」前缀,
/// 必须能在草稿变化时重建。state 是「peerId → 草稿文本」的内存快照,prefs 只是落盘;
/// 进 App 时后台预加载一次([preload]),之后读写都先走内存。
class DraftStore extends Notifier<Map<String, String>> {
  /// prefs 里的 key 前缀(网页端 `localStorage` 用同一个)。
  static const keyPrefix = 'chat_draft:';

  /// 预加载只跑一次:重复调用复用同一个 Future,不重复读盘。
  Future<void>? _loading;

  /// provider 已销毁:异步回调里不能再写 state(Riverpod 3 会抛)。
  bool _disposed = false;

  @override
  Map<String, String> build() {
    ref.onDispose(() => _disposed = true);
    // 启动即后台预加载:列表页一进来就要显示「[草稿] 」,不能等用户点进会话才读。
    unawaited(preload());
    return const {};
  }

  /// 从 prefs 把全部草稿读进内存(幂等)。
  Future<void> preload() => _loading ??= _load();

  Future<void> _load() async {
    final prefs = await SharedPreferences.getInstance();
    final loaded = <String, String>{};
    for (final key in prefs.getKeys()) {
      if (!key.startsWith(keyPrefix)) continue;
      final text = prefs.getString(key) ?? '';
      // 空白草稿等于没有草稿:历史版本 / 手滑存下的空串不占位,也不会让列表挂前缀。
      if (text.trim().isEmpty) continue;
      loaded[key.substring(keyPrefix.length)] = text;
    }
    if (_disposed) return;
    state = loaded;
  }

  /// 某个会话的草稿;没有(或只剩空白)返回 null。
  ///
  /// Args:
  ///   peerId: 会话对端的 IM id,如 `u9`。
  ///
  /// Returns:
  ///   草稿原文;没有草稿时为 null。
  String? draftOf(String peerId) {
    final text = state[peerId];
    return (text == null || text.trim().isEmpty) ? null : text;
  }

  /// 存一条草稿(输入框防抖 300ms 后调用)。全空白等同 [clear]。
  ///
  /// Args:
  ///   peerId: 会话对端的 IM id。
  ///   text: 输入框原文(不裁剪:前导空格也是用户打的)。
  Future<void> save(String peerId, String text) async {
    if (text.trim().isEmpty) return clear(peerId);
    if (state[peerId] != text && !_disposed) {
      state = {...state, peerId: text};
    }
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('$keyPrefix$peerId', text);
  }

  /// 删掉一条草稿(发送成功 / 输入框清空后调用)。
  ///
  /// Args:
  ///   peerId: 会话对端的 IM id。
  Future<void> clear(String peerId) async {
    if (state.containsKey(peerId) && !_disposed) {
      state = {...state}..remove(peerId);
    }
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('$keyPrefix$peerId');
  }
}

/// 全 App 一份草稿表:会话列表与聊天页共享同一条内存快照。
final draftStoreProvider =
    NotifierProvider<DraftStore, Map<String, String>>(DraftStore.new);
