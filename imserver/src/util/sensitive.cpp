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
* 文件名称          src/util/sensitive.cpp
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
#include "util/sensitive.h"

#include <algorithm>
#include <cctype>
#include <filesystem>
#include <fstream>
#include <system_error>

#include "util/log.h"

namespace sensitive {

namespace {

/// 只折 ASCII 的大小写。UTF-8 高位字节(>=0x80)在 C 的 `tolower` 下行为依赖 locale,
/// 一旦被改坏就不再是合法的 UTF-8 序列,所以命中判断一律只看 A–Z。
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     把 A–Z 折成小写 其它字节原样返回
// 参数说明     byte             待折叠的字节
// 返回参数     unsigned char    折叠后的字节
// 使用示例     const auto lower = fold('F');
// 备注信息     只处理 ASCII 高位字节不动 避免把 UTF-8 多字节序列改坏
//-------------------------------------------------------------------------------------------------------------------
unsigned char fold(unsigned char byte) {
  return (byte >= 'A' && byte <= 'Z') ? static_cast<unsigned char>(byte - 'A' + 'a') : byte;
}

/// 去掉首尾空白(空格 / 制表 / CR —— 词表文件可能是 Windows 编辑的 CRLF)。
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     去掉行首尾的空格 制表 CR 与 LF
// 参数说明     line             词表文件的一行 按值传入
// 返回参数     std::string      去掉首尾空白后的串 全空白返回空串
// 使用示例     const auto item = trim(std::move(line));
// 备注信息     兼容 Windows 编辑出的 CRLF 词表 中间空白保留
//-------------------------------------------------------------------------------------------------------------------
std::string trim(std::string line) {
  const auto keep = [](unsigned char ch) {
    return !(ch == ' ' || ch == '\t' || ch == '\r' || ch == '\n');
  };
  const auto first = std::find_if(line.begin(), line.end(), keep);
  if (first == line.end()) {
    return {};
  }
  const auto last = std::find_if(line.rbegin(), line.rend(), keep).base();
  return std::string(first, last);
}

}  // namespace

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     从词表文件构建敏感词自动机
// 参数说明     path             词表文件路径 一行一词 # 开头为注释
// 返回参数     bool             读到词条返回 true 文件缺失或为空返回 false
// 使用示例     sensitive::Matcher matcher; matcher.load(cfg.sensitive_words_path);
// 备注信息     读不到不 fail-closed 打 sensitive_words_disabled 后清空词表返回 false
//              原因区分 missing 与 unreadable 后者是容器内非 root 的权限问题
//              读到词条则打 sensitive_words_loaded 带 path 与词条数
//-------------------------------------------------------------------------------------------------------------------
bool Matcher::load(const std::string& path) {
  std::vector<std::string> words;
  std::ifstream file(path);
  if (!file) {
    // 不 fail-closed:词表缺失/读不到只是「这个功能没开」,不能让聊天整体不可用。
    // 但必须喊一声 —— 否则线上悄无声息地不拦,谁也不知道。
    // 「文件在但读不到」单独标出来:那是权限问题(容器以非 root 跑),不是「没配」。
    std::error_code ec;
    const bool exists = !path.empty() && std::filesystem::exists(path, ec);
    build({});
    log_warn("sensitive_words_disabled",
             {{"path", path},
              {"reason", exists ? "unreadable" : "missing"},
              {"policy", "chat text is NOT filtered"}});
    return false;
  }
  std::string line;
  while (std::getline(file, line)) {
    const auto item = trim(std::move(line));
    if (item.empty() || item[0] == '#') {
      continue;
    }
    words.push_back(item);
  }
  if (words.empty()) {
    build({});
    log_warn("sensitive_words_disabled",
             {{"path", path}, {"reason", "empty"}, {"policy", "chat text is NOT filtered"}});
    return false;
  }
  build(words);
  log_info("sensitive_words_loaded",
           {{"path", path}, {"words", std::to_string(words_)}});
  return true;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用一组词构建 Aho-Corasick 自动机
// 参数说明     words            词表 空串与只含空白的条目被跳过
// 返回参数     void             无返回值
// 使用示例     matcher.build({"赌博", "fuck"});
// 备注信息     先把 nodes_ 重建为单根 再按字节插 Trie 最后 BFS 建失败指针
//              失败指针逐层合并 output 命中判定只需看当前节点的 output
//              词先做 ASCII 折叠 构建后只读 多线程 hit 安全
//-------------------------------------------------------------------------------------------------------------------
void Matcher::build(const std::vector<std::string>& words) {
  nodes_.assign(1, Node{});
  words_ = 0;
  for (const auto& word : words) {
    std::string payload;
    payload.reserve(word.size());
    for (const unsigned char byte : word) {
      payload.push_back(static_cast<char>(fold(byte)));
    }
    if (payload.empty()) {
      continue;
    }
    int node = 0;
    for (const unsigned char byte : payload) {
      const auto found = nodes_[node].next.find(byte);
      if (found != nodes_[node].next.end()) {
        node = found->second;
        continue;
      }
      // 先 push_back 再取下标:`nodes_` 扩容后旧的引用/下标语义不变,下标才是稳的。
      nodes_.push_back(Node{});
      const int child = static_cast<int>(nodes_.size()) - 1;
      nodes_[node].next.emplace(byte, child);
      node = child;
    }
    nodes_[node].output = true;
    ++words_;
  }

  // BFS 建失败指针:根的出边失败一律回根,之后逐层把「最长的真后缀」接上,
  // 并把命中标记沿失败链合并(output 为真的状态 = 有一条词在这里结束)。
  std::vector<int> queue;
  queue.reserve(nodes_.size());
  for (const auto& [byte, child] : nodes_[0].next) {
    (void)byte;
    nodes_[child].fail = 0;
    queue.push_back(child);
  }
  for (std::size_t head = 0; head < queue.size(); ++head) {
    const int current = queue[head];
    // 只按 `current` 的下标取一次出边;循环体内 `nodes_` 不再扩容(BFS 已建完树)。
    for (const auto& [byte, child] : nodes_[current].next) {
      int fallback = nodes_[current].fail;
      while (fallback != 0 && nodes_[fallback].next.find(byte) == nodes_[fallback].next.end()) {
        fallback = nodes_[fallback].fail;
      }
      const auto found = nodes_[fallback].next.find(byte);
      const int target = found == nodes_[fallback].next.end() ? 0 : found->second;
      nodes_[child].fail = target;
      nodes_[child].output = nodes_[child].output || nodes_[target].output;
      queue.push_back(child);
    }
  }
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     沿自动机读一个字节得到下一状态
// 参数说明     node             当前状态下标 0 为根
//              byte             待读取的字节 已折叠 ASCII 大小写
// 返回参数     int              下一状态下标 无出边时回根 0
// 使用示例     node = step(node, fold(byte));
// 备注信息     循环沿 fail 链回退到根 只读 nodes_ 无锁 可在 IO 线程直接调用
//-------------------------------------------------------------------------------------------------------------------
int Matcher::step(int node, unsigned char byte) const {
  while (node != 0 && nodes_[node].next.find(byte) == nodes_[node].next.end()) {
    node = nodes_[node].fail;
  }
  const auto found = nodes_[node].next.find(byte);
  return found == nodes_[node].next.end() ? 0 : found->second;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     判断文本是否命中任一敏感词
// 参数说明     text             待检查文本 按 UTF-8 字节扫描
// 返回参数     bool             命中任一敏感词返回 true
// 使用示例     if (!sensitive_.empty() && sensitive_.hit(request.text)) { /* 拒绝发送 */ }
// 备注信息     复杂度 O(n) n 为文本字节数 词表为空或文本为空直接返回 false
//              逐字节折叠后 step 命中即返回 不做字符解码
//-------------------------------------------------------------------------------------------------------------------
bool Matcher::hit(std::string_view text) const {
  if (words_ == 0 || text.empty()) {
    return false;
  }
  int node = 0;
  for (const unsigned char byte : text) {
    node = step(node, fold(byte));
    if (nodes_[node].output) {
      return true;
    }
  }
  return false;
}

}  // namespace sensitive
