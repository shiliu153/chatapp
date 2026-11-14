/*********************************************************************************************************************
* chat_app 自建 IM 服务端（imserver）是本项目唯一的 IM 后端，C++20 实现，对外提供 WebSocket :9100 与 HTTP :9101
* Copyright (c) 2026 shiliu153
*
* 本文件是 chat_app 自建 IM 服务端的一部分
*
* 额外注明：
* 本文件使用 MIT 开源许可证协议 许可申明英文版见仓库根目录 LICENSE 文件
* 欢迎各位使用并传播本程序 但修改内容时必须保留作者的版权声明（即本声明）
*
* 文件名称          src/service/message_service.cpp
* 项目名称          chat_app / imserver
* 公司名称          个人项目（shiliu153）
* 版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
* 开发环境          CMake 3.22 + g++ (C++20) Linux x86_64
* 适用平台          Linux x86_64 服务端
* 仓库地址          https://github.com/shiliu153/chatapp
*
* 修改记录
* 日期              作者               备注
* 2026-11-14        shiliu153          补齐文件头与函数注释
********************************************************************************************************************/

#include "service/message_service.h"

#include <algorithm>
#include <chrono>
#include <cctype>
#include <cstdlib>
#include <functional>
#include <map>
#include <random>
#include <stdexcept>
#include <thread>

#include <nlohmann/json.hpp>

#include "store/stmt.h"
#include "util/im_id.h"
#include "util/log.h"
#include "util/message_kind.h"
#include "util/metrics.h"

namespace {

/// 引用摘要最多保留多少个字符(与设计文档 §4.2 一致)。
constexpr std::size_t kRefTextMax = 120;

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     取当前系统时间毫秒数
// 参数说明     无
// 返回参数     int64_t         Unix 毫秒时间戳
// 使用示例     const int64_t ts = now_ms();
// 备注信息     用 system_clock 受系统时间跳变影响 只用于落库与展示时间 不用于测量耗时
//-------------------------------------------------------------------------------------------------------------------
int64_t now_ms() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(
             std::chrono::system_clock::now().time_since_epoch())
      .count();
}

/// 死锁重试的退避毫秒数:指数式增长 + 线程本地随机抖动。
///
/// 固定退避会让同一批撞在一起的线程「同时醒来再撞一次」,抖动把重试错开。
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     计算死锁重试的退避毫秒数
// 参数说明     attempt         第几次重试 从 0 开始
// 返回参数     int             本次退避的毫秒数 线性增长加随机抖动
// 使用示例     std::this_thread::sleep_for(std::chrono::milliseconds(retry_backoff_ms(attempt)));
// 备注信息     抖动源是 thread_local std::mt19937 每线程独立种子 固定退避会让同批线程同时醒来再撞一次
//              只用于 MySQL 1213 死锁与 1205 锁等待超时后的重试
//-------------------------------------------------------------------------------------------------------------------
int retry_backoff_ms(int attempt) {
  thread_local std::mt19937 rng([] {
    std::random_device seed;
    return std::mt19937(seed() ^ static_cast<unsigned>(
                                     std::hash<std::thread::id>{}(std::this_thread::get_id())));
  }());
  std::uniform_int_distribution<int> jitter(0, 2 * (attempt + 1));
  return 2 * (attempt + 1) + jitter(rng);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     统计 UTF-8 文本的字符数
// 参数说明     text            待统计的 UTF-8 文本
// 返回参数     std::size_t     字符数 不是字节数
// 使用示例     const std::size_t chars = utf8_length(text);
// 备注信息     只数首字节 续字节 0x80~0xBF 不计 不做编码合法性校验
//-------------------------------------------------------------------------------------------------------------------
std::size_t utf8_length(const std::string& text) {
  std::size_t count = 0;
  for (unsigned char ch : text) {
    if ((ch & 0xC0) != 0x80) {
      ++count;
    }
  }
  return count;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     去掉文本首尾的 ASCII 空白
// 参数说明     text            原文本
// 返回参数     std::string     去掉首尾空格 制表符 回车 换行后的文本 全空白时返回空串
// 使用示例     const std::string text = trim(request.text);
// 备注信息     只裁首尾 不动内部空白 也不处理非 ASCII 空白
//-------------------------------------------------------------------------------------------------------------------
std::string trim(const std::string& text) {
  const auto first = text.find_first_not_of(" \t\r\n");
  if (first == std::string::npos) {
    return "";
  }
  const auto last = text.find_last_not_of(" \t\r\n");
  return text.substr(first, last - first + 1);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     校验客户端消息 id 是否合法
// 参数说明     value           待校验的 client_msg_id
// 返回参数     bool            长度 1~64 且只含字母 数字 下划线 连字符时返回 true
// 使用示例     if (!valid_client_id(request.client_msg_id)) { return 42201; }
// 备注信息     合法的 client_msg_id 是幂等重放的唯一键 不合法在落库前就回 42201
//-------------------------------------------------------------------------------------------------------------------
bool valid_client_id(const std::string& value) {
  if (value.empty() || value.size() > 64) {
    return false;
  }
  for (unsigned char ch : value) {
    if (!std::isalnum(ch) && ch != '_' && ch != '-') {
      return false;
    }
  }
  return true;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     由消息行组装下行结果并补发送者资料
// 参数说明     row             已落库的消息行
//              users           用户仓库 用来补昵称与头像
// 返回参数     SendResult      含 msg_id seq ts 昵称头像与整行
// 使用示例     return result_for(*existing, users_);
// 备注信息     1062 幂等重放也走这里 整行必须带出 下行帧才能与 /im/api/messages 共用同一序列化
//-------------------------------------------------------------------------------------------------------------------
SendResult result_for(const MessageRow& row, UserRepo& users) {
  SendResult result;
  result.msg_id = row.msg_id;
  result.seq = row.seq;
  result.ts = row.created_at;
  if (auto profile = users.get(row.from_id)) {
    result.from_nickname = profile->nickname;
    result.from_avatar = profile->avatar;
  }
  // 幂等重放(同一个 client_msg_id)也要带上整行:下行帧照样走 message_json。
  result.row = row;
  return result;
}

/// 这条消息能不能被引用。
///
/// 系统灰条(配对成功 / 封禁通知…)不是「人说的话」,引用它既没有内容也没有意义,
/// 一律拒。注意贴纸也走 `kind=2`,但它是用户发的 —— 所以判据是载荷的 `type`,
/// 不是 kind。
///
/// Args:
///   row: 被引用的消息行。
///
/// Returns:
///   可引用返回 true。
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     判断一条消息能否作为引用对象
// 参数说明     row             被引用的消息行
// 返回参数     bool            可引用返回 true
// 使用示例     if (!quotable(*referenced)) { return 42201; }
// 备注信息     kind 不等于 2 一律可引用 kind 等于 2 时看载荷 type 是否为 sticker
//              系统灰条不是人说的话 载荷解析失败按不可引用处理
//-------------------------------------------------------------------------------------------------------------------
bool quotable(const MessageRow& row) {
  if (row.kind != 2) {
    return true;
  }
  try {
    return nlohmann::json::parse(row.body).value("type", std::string()) == "sticker";
  } catch (const std::exception&) {
    return false;
  }
}

/// 生成引用快照(**只能由服务端做**)。
///
/// 为什么不信客户端:让客户端传快照等于允许任何人伪造「对方说过 X」。
/// 这里吃的是**回库查到的行**,只摘 id / 发送者 / 类型 / 摘要 / 是否已撤回。
///
/// Args:
///   row: 被引用的消息行(已确认在同一会话里)。
///
/// Returns:
///   下行 `ref` 对象:`{msg_id, from, kind, text, revoked}`。
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     由消息行生成引用快照
// 参数说明     row             被引用的消息行 已确认在同一会话内
// 返回参数     nlohmann::json  下行 ref 对象 含 msg_id from kind text revoked
// 使用示例     ref_snapshot = build_ref_snapshot(*referenced).dump();
// 备注信息     只能由服务端生成 客户端夹带的快照一律不采信
//              文本摘要截断到 120 字符 已撤回的消息只留 revoked 不泄漏原文 图片语音贴纸写占位文案
//-------------------------------------------------------------------------------------------------------------------
nlohmann::json build_ref_snapshot(const MessageRow& row) {
  nlohmann::json snapshot = {{"msg_id", row.msg_id},
                             {"from", peer_id(row.from_id)},
                             {"kind", kind_name(row.kind)},
                             {"revoked", row.revoked_at.has_value()}};
  if (row.revoked_at.has_value()) {
    // 已撤回:只留「这条被撤回了」这件事,不泄漏原文(撤回了就该看不见)。
    snapshot["text"] = "";
    return snapshot;
  }
  switch (row.kind) {
    case 1: {
      std::string text;
      try {
        text = nlohmann::json::parse(row.body).value("text", std::string());
      } catch (const std::exception&) {
        text.clear();
      }
      snapshot["text"] = truncate_utf8(text, kRefTextMax);
      break;
    }
    case 3:
      snapshot["text"] = "[图片]";
      break;
    case 4:
      snapshot["text"] = "[语音]";
      break;
    default:
      snapshot["text"] = "[贴纸]";
      break;
  }
  return snapshot;
}

}  // namespace

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     构造消息服务 绑定各仓库并读慢日志阈值
// 参数说明     pool                  MySQL 连接池
//              users                 用户仓库
//              conversations         会话仓库
//              messages              消息仓库
//              blacklist             黑名单仓库
//              text_max              文本消息最大字符数 默认 2000
//              media_prefix          媒体 URL 前缀 用于规范化图片与语音地址
//              media_sign_secret     媒体签名密钥 交给 MediaSigner
//              media_sign_ttl        媒体签名有效期秒 默认 86400
// 返回参数     void                  无返回值
// 使用示例     MessageService service(pool, users, conversations, messages, blacklist);
// 备注信息     构造只保存引用与配置 不查库 各仓库的生命周期必须长于本对象
//              环境变量 IM_SLOW_SEND_MS 非零时 单条发送超过该毫秒数打一条慢发送日志
//-------------------------------------------------------------------------------------------------------------------
MessageService::MessageService(MysqlPool& pool, UserRepo& users,
                               ConversationRepo& conversations, MessageRepo& messages,
                               BlacklistRepo& blacklist, std::size_t text_max,
                               std::string media_prefix, std::string media_sign_secret,
                               int media_sign_ttl)
    : pool_(pool),
      users_(users),
      conversations_(conversations),
      messages_(messages),
      blacklist_(blacklist),
      text_max_(text_max),
      media_prefix_(std::move(media_prefix)),
      signer_(std::move(media_sign_secret), media_sign_ttl, media_prefix_) {
  if (const char* slow = std::getenv("IM_SLOW_SEND_MS")) {
    slow_send_ms_ = std::atoi(slow);
  }
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     列出我的会话列表并修正被隐藏的摘要
// 参数说明     uid                            请求者账号
//              limit                          最多返回条数
// 返回参数     std::vector<ConversationView>  会话视图 新到旧
// 使用示例     auto views = service.list_conversations(uid, 50);
// 备注信息     只有最后一条可见消息被我隐藏的会话才回查上一条 其余会话零额外查询
//-------------------------------------------------------------------------------------------------------------------
std::vector<ConversationView> MessageService::list_conversations(uint64_t uid, int limit) {
  auto lease = pool_.acquire();
  auto views = conversations_.list(lease, uid, limit);
  // 摘要要显示「**我**最后一条可见消息」(批次 T 的多选删除):只有摘要本身被我隐藏的
  // 会话才回查上一条,绝大多数会话零额外查询。
  messages_.apply_visible_last(lease, uid, views);
  return views;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     按会话分页拉取历史消息
// 参数说明     uid                      请求者账号
//              peer                     会话对端
//              before_seq               游标 只取 seq 更小的 0 表示从最新开始
//              limit                    最多返回条数
// 返回参数     std::vector<MessageRow>  消息行 新到旧 会话不存在时返回空
// 使用示例     auto rows = service.list_messages(uid, peer, 0, 30);
// 备注信息     先按 (uid, peer) 查会话 查不到直接返回空 未配对与会话已删都不区分
//-------------------------------------------------------------------------------------------------------------------
std::vector<MessageRow> MessageService::list_messages(uint64_t uid, uint64_t peer,
                                                      uint64_t before_seq, int limit) {
  auto lease = pool_.acquire();
  const auto conversation = conversations_.find_pair(lease, uid, peer);
  if (!conversation.has_value()) {
    return {};
  }
  return messages_.list(lease, uid, conversation->id, before_seq, limit);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     按关键词搜索我的历史消息
// 参数说明     uid                      请求者账号
//              keyword                  用户关键词
//              before_id                游标消息 id 0 表示第一页
//              limit                    最多返回条数
// 返回参数     std::vector<MessageRow>  命中的消息行 新到旧
// 使用示例     auto rows = service.search(uid, "晚饭", 0, 20);
// 备注信息     只搜我参与的会话 匹配口径与游标规则见 MessageRepo::search
//-------------------------------------------------------------------------------------------------------------------
std::vector<MessageRow> MessageService::search(uint64_t uid, const std::string& keyword,
                                               uint64_t before_id, int limit) {
  auto lease = pool_.acquire();
  return messages_.search(lease, uid, keyword, before_id, limit);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     把会话标到已读并回读真实已读位置
// 参数说明     uid                      读消息的人
//              peer                     会话对端
//              seq                      读到哪 0 表示读到该会话最新
// 返回参数     std::optional<uint64_t>  实库里的 read_seq 会话不存在时 nullopt
// 使用示例     auto read_seq = service.mark_read(uid, peer, seq);
// 备注信息     落库用 GREATEST 乱序到达的旧 read 帧不会让已读回退
//              必须回读实库再广播 直接回传入参会把客户端推回未读
//-------------------------------------------------------------------------------------------------------------------
std::optional<uint64_t> MessageService::mark_read(uint64_t uid, uint64_t peer, uint64_t seq) {
  auto lease = pool_.acquire();
  const auto conversation = conversations_.find_pair(lease, uid, peer);
  if (!conversation.has_value()) {
    return std::nullopt;
  }
  const uint64_t target = seq == 0 ? conversation->last_seq : seq;
  conversations_.mark_read(lease, uid, peer, target, now_ms());
  // 回读而不是直接返回 target:落库用的是 GREATEST,乱序到达的旧 read 帧不会让
  // read_seq 回退;广播必须带真实值,否则客户端会被「更小的 N」推回未读。
  return conversations_.read_seq_for(lease, uid, peer);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     设置会话置顶与免打扰并回读真实标志
// 参数说明     uid                               会话主人
//              peer                              会话对端
//              pinned                            置顶开关 nullopt 表示不改
//              muted                             免打扰开关 nullopt 表示不改
// 返回参数     std::optional<ConversationFlags>  回读实库后的标志位 会话不存在时 nullopt
// 使用示例     auto flags = service.set_conversation_flags(uid, peer, true, std::nullopt);
// 备注信息     单方操作 只写 uid 自己那一行 不给对端发任何帧
//              置顶写当前毫秒 取消写 0 重复置顶不改时间
//-------------------------------------------------------------------------------------------------------------------
std::optional<ConversationFlags> MessageService::set_conversation_flags(
    uint64_t uid, uint64_t peer, std::optional<bool> pinned, std::optional<bool> muted) {
  auto lease = pool_.acquire();
  // 会话不存在 = 未配对 / 从没聊过:直接 nullopt,由 HTTP 层回 404。
  // 判断放在 repo 里(一次等值查询就能拿到 conv_id 与现值),不在这里先 find_pair 再写。
  return conversations_.set_flags(lease, uid, peer, pinned, muted, now_ms());
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     撤回自己发出的消息 限 120 秒内
// 参数说明     uid                              请求者账号
//              msg_id                           要撤回的消息 id
// 返回参数     std::variant<RevokeResult, int>  成功给撤回结果 失败给业务码 41001
// 使用示例     auto result = service.revoke(uid, msg_id);
// 备注信息     非本人 已撤回 距发送超过 120000 毫秒三种情形统一回 41001 调用方无法据此判断消息归属
//              撤回只写 revoked_at 不删消息行
//-------------------------------------------------------------------------------------------------------------------
std::variant<RevokeResult, int> MessageService::revoke(uint64_t uid, uint64_t msg_id) {
  auto lease = pool_.acquire();
  const auto message = messages_.get(lease, msg_id);
  if (!message.has_value() || message->from_id != uid || message->revoked_at.has_value()) {
    return 41001;
  }
  const int64_t now = now_ms();
  if (now - message->created_at > 120000) {
    return 41001;
  }
  messages_.revoke(lease, msg_id, now);
  RevokeResult result;
  result.msg_id = message->msg_id;
  result.seq = message->seq;
  result.from_id = message->from_id;
  result.to_id = message->to_id;
  result.ts = now;
  return result;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     多选删除 把一批消息从我这边隐藏
// 参数说明     uid             请求者账号
//              ids             消息 id 列表 调用方已校验非空 不超过 50 且都是正整数
// 返回参数     uint64_t        本次新隐藏的条数 重复删同一批返回 0
// 使用示例     const uint64_t hidden = service.hide_messages(uid, ids);
// 备注信息     单方语义 只写 im_message_hidden 不碰消息本体与 last_seq 不给对端发帧 不可恢复
//              别人的 id 静默忽略 不区分不存在与无权
//              减未读只算本次新隐藏 对端发来的 且尚未读的条数 事务异常回滚后重抛
//-------------------------------------------------------------------------------------------------------------------
uint64_t MessageService::hide_messages(uint64_t uid, const std::vector<uint64_t>& ids) {
  if (uid == 0 || ids.empty()) {
    return 0;
  }
  auto lease = pool_.acquire();
  lease.begin();
  try {
    const auto rows = messages_.find_mine(lease, uid, ids);
    const int64_t now = now_ms();
    // 只记「本次新隐藏」的行:减未读必须按新隐藏的算,否则重复删同一批会把
    // 未读越减越少(幂等只体现在返回值上,副作用不能重放)。
    std::vector<MessageRow> newly_hidden;
    newly_hidden.reserve(rows.size());
    for (const auto& row : rows) {
      if (messages_.hide(lease, uid, row.msg_id, now)) {
        newly_hidden.push_back(row);
      }
    }
    if (!newly_hidden.empty()) {
      // 未读减多少:只算「对端发的 + 我还没读过的(seq > 我这条会话的 read_seq)」。
      // 删掉**已读**的消息不动未读 —— 它本来就没算进未读里。
      std::vector<uint64_t> conv_ids;
      for (const auto& row : newly_hidden) {
        if (row.to_id != uid) {
          continue;
        }
        if (std::find(conv_ids.begin(), conv_ids.end(), row.conv_id) == conv_ids.end()) {
          conv_ids.push_back(row.conv_id);
        }
      }
      if (!conv_ids.empty()) {
        const auto read_seqs = conversations_.read_seqs(lease, uid, conv_ids);
        std::map<uint64_t, int> deltas;
        for (const auto& row : newly_hidden) {
          if (row.to_id != uid) {
            continue;
          }
          const auto it = read_seqs.find(row.conv_id);
          const uint64_t read_seq = it == read_seqs.end() ? 0 : it->second;
          if (row.seq > read_seq) {
            deltas[row.conv_id] += 1;
          }
        }
        for (const auto& [conv_id, delta] : deltas) {
          conversations_.decrement_unread(lease, uid, conv_id, delta, now);
        }
      }
    }
    lease.commit();
    return static_cast<uint64_t>(newly_hidden.size());
  } catch (const std::exception& error) {
    try {
      lease.rollback();
    } catch (const std::exception&) {
    }
    log_error("hide_messages_failed", {{"uid", std::to_string(uid)}, {"error", error.what()}});
    throw;
  }
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     删除我这一侧的会话
// 参数说明     uid             请求者账号
//              peer            会话对端
// 返回参数     bool            会话存在并标记成功返回 true
// 使用示例     if (!service.delete_conversation(uid, peer)) { return 404; }
// 备注信息     只置 deleted 标记 不删消息行 会话不存在返回 false 由上层回 404
//-------------------------------------------------------------------------------------------------------------------
bool MessageService::delete_conversation(uint64_t uid, uint64_t peer) {
  auto lease = pool_.acquire();
  const auto conversation = conversations_.find_pair(lease, uid, peer);
  if (!conversation.has_value()) {
    return false;
  }
  conversations_.set_deleted(lease, uid, peer, now_ms());
  return true;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     注销账号并清空该用户的全部 IM 数据
// 参数说明     uid             账号
// 返回参数     bool            全部删除并提交成功返回 true 异常回滚后返回 false
// 使用示例     const bool ok = service.delete_account(uid);
// 备注信息     隐藏行必须先清 消息删掉之后就反查不到 msg_id 隐藏行会变成永久垃圾
//              单事务依次清 隐藏行 消息 会话 黑名单 配对 用户 失败只记日志不抛
//-------------------------------------------------------------------------------------------------------------------
bool MessageService::delete_account(uint64_t uid) {
  auto lease = pool_.acquire();
  try {
    lease.begin();
    // 多选删除(批次 T)的隐藏行要**先**清:第二条靠 im_message 里的行反查 msg_id,
    // 消息删掉之后就再也查不到,隐藏行会变成永久垃圾(msg_id 还可能被自增复用)。
    messages_.delete_hidden_by_user(lease, uid);
    messages_.delete_hidden_by_messages(lease, uid);
    messages_.delete_for_user(lease, uid);
    conversations_.delete_for_user(lease, uid);
    blacklist_.delete_for_user(lease, uid);
    lease.query("DELETE FROM im_pair WHERE user_a=" + std::to_string(uid) +
                " OR user_b=" + std::to_string(uid));
    users_.remove(lease, uid);
    lease.commit();
    return true;
  } catch (const std::exception& error) {
    try {
      lease.rollback();
    } catch (const std::exception&) {
    }
    log_error("delete_account_failed", {{"uid", std::to_string(uid)}, {"error", error.what()}});
    return false;
  }
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     更新用户昵称与头像
// 参数说明     uid             账号
//              nickname        新昵称 nullopt 表示不改
//              avatar          新头像 nullopt 表示不改
// 返回参数     bool            固定返回 true 失败以异常形式抛出
// 使用示例     service.update_profile(uid, std::string("小明"), std::nullopt);
// 备注信息     只写非 nullopt 的字段 内容合法性由调用方校验
//-------------------------------------------------------------------------------------------------------------------
bool MessageService::update_profile(uint64_t uid,
                                    const std::optional<std::string>& nickname,
                                    const std::optional<std::string>& avatar) {
  auto lease = pool_.acquire();
  users_.update_profile(lease, uid, nickname, avatar, now_ms());
  return true;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     把对端加入我的黑名单
// 参数说明     owner           拉黑发起方
//              peer            被拉黑方
// 返回参数     void            无返回值
// 使用示例     service.blacklist_add(owner, peer);
// 备注信息     仓库层自己取连接 数据库异常会向上抛
//-------------------------------------------------------------------------------------------------------------------
void MessageService::blacklist_add(uint64_t owner, uint64_t peer) {
  blacklist_.add(owner, peer);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     把对端从我的黑名单移除
// 参数说明     owner           拉黑发起方
//              peer            被拉黑方
// 返回参数     void            无返回值
// 使用示例     service.blacklist_remove(owner, peer);
// 备注信息     只删 owner 到 peer 这一条 不影响对端对我的拉黑
//-------------------------------------------------------------------------------------------------------------------
void MessageService::blacklist_remove(uint64_t owner, uint64_t peer) {
  auto lease = pool_.acquire();
  blacklist_.remove(lease, owner, peer);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     判断两个账号是否已配对 复用调用方事务
// 参数说明     lease           调用方已持有的连接租约
//              a               账号 A
//              b               账号 B
// 返回参数     bool            im_pair 里存在这一对时返回 true
// 使用示例     if (!pair_exists(lease, from, to)) { return 40302; }
// 备注信息     im_pair 只存 (小, 大) 有序对 这里先取 min/max 再查
//              复用租约保证与发消息在同一事务内 不会读到并发删除的中间态
//-------------------------------------------------------------------------------------------------------------------
bool MessageService::pair_exists(MysqlPool::Lease& lease, uint64_t a, uint64_t b) {
  const uint64_t lo = std::min(a, b);
  const uint64_t hi = std::max(a, b);
  auto* result = lease.query("SELECT 1 FROM im_pair WHERE user_a=" + std::to_string(lo) +
                             " AND user_b=" + std::to_string(hi));
  if (result == nullptr) {
    return false;
  }
  const bool exists = mysql_fetch_row(result) != nullptr;
  mysql_free_result(result);
  return exists;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     判断两个账号是否已配对 自取连接
// 参数说明     a               账号 A
//              b               账号 B
// 返回参数     bool            im_pair 里存在这一对时返回 true
// 使用示例     const bool paired = service.pair_exists(a, b);
// 备注信息     内部从连接池取一条租约再转调三参版本 口径完全一致
//-------------------------------------------------------------------------------------------------------------------
bool MessageService::pair_exists(uint64_t a, uint64_t b) {
  auto lease = pool_.acquire();
  return pair_exists(lease, a, b);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     建立两个账号的配对关系
// 参数说明     a               账号 A
//              b               账号 B
// 返回参数     void            无返回值
// 使用示例     service.pair_add(a, b);
// 备注信息     落库前按 min/max 排序 重复配对靠 ON DUPLICATE KEY 幂等 不改 created_at
//-------------------------------------------------------------------------------------------------------------------
void MessageService::pair_add(uint64_t a, uint64_t b) {
  const uint64_t lo = std::min(a, b);
  const uint64_t hi = std::max(a, b);
  auto lease = pool_.acquire();
  Stmt stmt(lease.get(),
            "INSERT INTO im_pair (user_a,user_b,created_at) VALUES (?,?,?) "
            "ON DUPLICATE KEY UPDATE user_a=user_a");
  stmt.bind_uint(0, lo);
  stmt.bind_uint(1, hi);
  stmt.bind_uint(2, static_cast<uint64_t>(now_ms()));
  stmt.execute();
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     解除两个账号的配对关系
// 参数说明     a               账号 A
//              b               账号 B
// 返回参数     void            无返回值
// 使用示例     service.pair_remove(a, b);
// 备注信息     同样按 min/max 排序 关系本来不存在时静默成功
//-------------------------------------------------------------------------------------------------------------------
void MessageService::pair_remove(uint64_t a, uint64_t b) {
  const uint64_t lo = std::min(a, b);
  const uint64_t hi = std::max(a, b);
  auto lease = pool_.acquire();
  Stmt stmt(lease.get(), "DELETE FROM im_pair WHERE user_a=? AND user_b=?");
  stmt.bind_uint(0, lo);
  stmt.bind_uint(1, hi);
  stmt.execute();
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     探测数据库当前是否可用
// 参数说明     无
// 返回参数     bool            取到连接并执行 SELECT 1 成功返回 true
// 使用示例     if (!service.ready()) { return 503; }
// 备注信息     内部吞掉全部异常只回 bool 供健康检查与启动自检使用
//-------------------------------------------------------------------------------------------------------------------
bool MessageService::ready() {
  try {
    auto lease = pool_.acquire();
    auto* result = lease.query("SELECT 1");
    if (result != nullptr) {
      mysql_free_result(result);
    }
    return true;
  } catch (const std::exception&) {
    return false;
  }
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     发送一条消息 校验后落库并组装下行数据
// 参数说明     request                        发送请求 含收发双方 client_msg_id 类型与载荷
// 返回参数     std::variant<SendResult, int>  成功给刚落库的消息行 失败给业务码 42201 40302 50001
// 使用示例     auto result = service.send(request);
// 备注信息     链路 参数与载荷校验 配对检查 黑名单检查 锁会话取 seq 生成引用快照 落库 更新会话与对端状态 提交后组装下行数据
//              鉴权与发送配额在入口层完成 配额目前只在 WS 发送路径上做 下行帧由入口层按返回值推送
//              1213 死锁与 1205 锁等待超时最多重试 8 次 退避带抖动 用尽回 50001
//              1062 唯一键冲突按幂等重放处理 回已有消息行 已有行的 to 与本次不同则回 42201
//              系统通知 from 为 0 时跳过配对与黑名单检查 也不建发送者用户行
//-------------------------------------------------------------------------------------------------------------------
std::variant<SendResult, int> MessageService::send(const SendRequest& request) {
  if (request.to == 0 || request.from == request.to ||
      !valid_client_id(request.client_msg_id)) {
    return 42201;
  }

  // 按 kind 分别校验并构造落库 body:1=text、2=custom、3=image、4=voice
  nlohmann::json body;
  try {
    if (request.kind == 1) {
      const auto text = trim(request.text);
      if (text.empty() || utf8_length(text) > text_max_) {
        return 42201;
      }
      body = {{"text", text}};
    } else if (request.kind == 2) {
      if (!request.custom.is_object() || request.custom.value("type", "").empty()) {
        return 42201;
      }
      body = request.custom;
    } else if (request.kind == 3) {
      // 图片只接受本服务媒体前缀下的 URL,并落**规范 URL**(去掉 query):
      // 客户端带上来的签名是上传那一刻的,存下来会在过期后变成死链,
      // 读的时候由 MediaSigner 现签(见 frames.h / http_api.cpp)。
      const auto& image = request.image;
      if (!image.is_object()) {
        return 42201;
      }
      const auto canonical_url = signer_.canonical(image.value("url", std::string()));
      const auto canonical_thumb = signer_.canonical(image.value("thumb_url", std::string()));
      if (!canonical_url.has_value() || !canonical_thumb.has_value()) {
        return 42201;
      }
      const auto width = image.value("width", 0ULL);
      const auto height = image.value("height", 0ULL);
      const auto size = image.value("size", 0ULL);
      if (canonical_url->size() > 512 || canonical_thumb->size() > 512 || width == 0 ||
          height == 0 || width > 4096 || height > 4096 || size == 0 ||
          size > 5 * 1024 * 1024) {
        return 42201;
      }
      nlohmann::json stored = image;
      stored["url"] = *canonical_url;
      stored["thumb_url"] = *canonical_thumb;
      body = {{"image", stored}};
    } else if (request.kind == 4) {
      // 语音与图片同理:只接受本服务媒体前缀下的 URL,落规范 URL,读时现签
      const auto& voice = request.voice;
      if (!voice.is_object()) {
        return 42201;
      }
      const auto canonical = signer_.canonical(voice.value("url", std::string()));
      if (!canonical.has_value() || canonical->size() > 512) {
        return 42201;
      }
      const auto duration = voice.value("duration_ms", 0LL);
      const auto size = voice.value("size", 0LL);
      if (duration < 1000 || duration > 60000 || size <= 0 ||
          size > 2 * 1024 * 1024) {
        return 42201;
      }
      nlohmann::json stored = voice;
      stored["url"] = *canonical;
      body = {{"voice", stored}};
    } else {
      return 42201;
    }
  } catch (const std::exception&) {
    return 42201;
  }

  // 冷启动时大量新会话并发创建会在 im_conversation 的唯一键上死锁;
  // 死锁(1213)与锁等待超时(1205)是 MySQL 的可重试错误。
  // 重试 8 次 + 抖动:500 对全新配对同时发首条消息时,重试窗口要覆盖一次 InnoDB
  // 死锁检测周期(默认 50ms 量级),3 次(2/4/6ms)实测扛不住。
  for (int attempt = 0; attempt < 8; ++attempt) {
    auto lease = pool_.acquire();
    try {
      lease.begin();
      const auto t0 = std::chrono::steady_clock::now();
      auto since = [&t0]() {
        return std::chrono::duration_cast<std::chrono::microseconds>(
                   std::chrono::steady_clock::now() - t0)
            .count();
      };
      // 聊天权限:只有配对关系才允许发消息(系统通知 from=0 豁免)。
      // 未配对直接 40302,不建 im_user 行,避免任意 uid 都能被写库(H4)。
      if (request.from != 0 && !pair_exists(lease, request.from, request.to)) {
        lease.rollback();
        return 40302;
      }
      if (!users_.get(lease, request.to).has_value()) {
        lease.rollback();
        return 42201;
      }
      if (request.from != 0) {
        users_.ensure(lease, request.from, "");
      }
      const bool blocked =
          request.from != 0 && blacklist_.exists_either(lease, request.from, request.to);
      const auto m_blacklist = since();
      if (blocked) {
        lease.rollback();
        return 40302;
      }

      const int64_t now = now_ms();
      const auto conversation =
          conversations_.lock_pair(lease, request.from, request.to, now);
      const auto m_lock = since();
      const uint64_t seq = conversation.last_seq + 1;
      const std::string body_json = body.dump();

      // 引用回复(批次 L-2):只认 id,**回库查**内容并自己生成快照。
      // 三条拒绝理由都归到 42201(不新增业务码):
      //   ① 消息不存在;② 不在同一个会话里(否则就是跨会话引用);
      //   ③ 引用的是系统灰条(它不是「人说的话」,没有可显示的内容)。
      std::optional<std::string> ref_snapshot;
      if (request.ref_msg_id.has_value()) {
        const auto referenced = messages_.get(lease, *request.ref_msg_id);
        if (!referenced.has_value() || referenced->conv_id != conversation.id ||
            !quotable(*referenced)) {
          lease.rollback();
          return 42201;
        }
        ref_snapshot = build_ref_snapshot(*referenced).dump();
      }

      uint64_t msg_id = 0;
      try {
        msg_id = messages_.insert(lease, conversation.id, seq, request.from, request.to,
                                  request.kind, body_json, request.client_msg_id, now,
                                  request.ref_msg_id, ref_snapshot);
      } catch (const MysqlError& error) {
        if (error.code() != 1062) {
          throw;
        }
        lease.rollback();
        if (auto existing = messages_.find_by_client(request.from, request.client_msg_id)) {
          if (existing->to_id != request.to) {
            return 42201;
          }
          metrics::sends_ok.fetch_add(1, std::memory_order_relaxed);
          return result_for(*existing, users_);
        }
        metrics::sends_failed.fetch_add(1, std::memory_order_relaxed);
        return 50001;
      }
      const auto m_insert = since();

      conversations_.touch(lease, conversation.id, seq, msg_id, now);
      const auto m_touch = since();
      conversations_.upsert_states(lease, request.to, 1, request.from, 0, conversation.id, now);
      const auto m_state1 = since();
      const auto m_state2 = m_state1;
      lease.commit();
      const auto m_commit = since();

      SendResult result;
      result.msg_id = msg_id;
      result.seq = seq;
      result.ts = now;
      if (auto profile = users_.get(request.from)) {
        result.from_nickname = profile->nickname;
        result.from_avatar = profile->avatar;
      }
      // 把刚落库的这一行带出去:下行帧要按**库里的真实内容**拼(文本已 trim、
      // 媒体 URL 已规范、引用快照已生成),不能拿 request 再拼一遍。
      result.row.msg_id = msg_id;
      result.row.conv_id = conversation.id;
      result.row.seq = seq;
      result.row.from_id = request.from;
      result.row.to_id = request.to;
      result.row.kind = request.kind;
      result.row.body = body_json;
      result.row.client_msg_id = request.client_msg_id;
      result.row.created_at = now;
      result.row.ref_msg_id = request.ref_msg_id;
      result.row.ref_snapshot = ref_snapshot;
      const auto m_total = since();
      if (slow_send_ms_ > 0 && m_total >= slow_send_ms_ * 1000LL) {
        log_error("slow_send", {{"from", std::to_string(request.from)},
                                {"to", std::to_string(request.to)},
                                {"total_us", std::to_string(m_total)},
                                {"blacklist_us", std::to_string(m_blacklist)},
                                {"lock_us", std::to_string(m_lock - m_blacklist)},
                                {"insert_us", std::to_string(m_insert - m_lock)},
                                {"touch_us", std::to_string(m_touch - m_insert)},
                                {"state1_us", std::to_string(m_state1 - m_touch)},
                                {"state2_us", std::to_string(m_state2 - m_state1)},
                                {"commit_us", std::to_string(m_commit - m_state2)},
                                {"profile_us", std::to_string(m_total - m_commit)}});
      }
      metrics::sends_ok.fetch_add(1, std::memory_order_relaxed);
      return result;
    } catch (const MysqlError& error) {
      try {
        lease.rollback();
      } catch (const std::exception&) {
      }
      if (error.code() == 1213 || error.code() == 1205) {
        metrics::deadlock_retries.fetch_add(1, std::memory_order_relaxed);
        std::this_thread::sleep_for(std::chrono::milliseconds(retry_backoff_ms(attempt)));
        continue;
      }
      log_error("send_failed", {{"from", std::to_string(request.from)},
                                {"to", std::to_string(request.to)},
                                {"error", error.what()}});
      metrics::sends_failed.fetch_add(1, std::memory_order_relaxed);
      return 50001;
    } catch (const std::exception& error) {
      try {
        lease.rollback();
      } catch (const std::exception&) {
      }
      log_error("send_failed", {{"from", std::to_string(request.from)},
                                {"to", std::to_string(request.to)},
                                {"error", error.what()}});
      metrics::sends_failed.fetch_add(1, std::memory_order_relaxed);
      return 50001;
    }
  }

  log_error("send_failed", {{"from", std::to_string(request.from)},
                            {"to", std::to_string(request.to)},
                            {"error", "deadlock retry exhausted"}});
  metrics::sends_failed.fetch_add(1, std::memory_order_relaxed);
  return 50001;
}
