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
unsigned char fold(unsigned char byte) {
  return (byte >= 'A' && byte <= 'Z') ? static_cast<unsigned char>(byte - 'A' + 'a') : byte;
}

/// 去掉首尾空白(空格 / 制表 / CR —— 词表文件可能是 Windows 编辑的 CRLF)。
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

int Matcher::step(int node, unsigned char byte) const {
  while (node != 0 && nodes_[node].next.find(byte) == nodes_[node].next.end()) {
    node = nodes_[node].fail;
  }
  const auto found = nodes_[node].next.find(byte);
  return found == nodes_[node].next.end() ? 0 : found->second;
}

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
