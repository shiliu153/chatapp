#pragma once
#include <cstddef>
#include <map>
#include <string>
#include <string_view>
#include <vector>

/// 聊天文字敏感词匹配(批次 Q,2026-11-09)。
///
/// 为什么放 imserver:聊天消息由客户端 WS **直连 imserver** 落库,不经过 Django,
/// 要拦就只能在 `send` 路径上拦(详见 `docs/ops/imserver.md`「聊天文字敏感词」)。
///
/// 为什么是 Aho-Corasick 而不是「词表 for 循环 + find`:前者单条消息 O(n),
/// 后者 O(n·m)。词表会长(主人按需增删),一旦几十上百条,双字节扫描的
/// 朴素写法在 2C2G 上就成了可感知的发送延迟。
namespace sensitive {

/// 敏感词匹配器:启动时从词表文件构建一次,之后**只读**(多线程并发 `hit` 安全)。
///
/// 设计要点:
///   1. 按 UTF-8 **字节**建树与匹配 —— 中文每字 3 字节,词与文本都按字节走,
///      天然对齐,不需要做字符解码(也不会在半个汉字上误命中);
///   2. ASCII 统一折成小写,`FUCK` / `Fuck` / `fuck` 命中同一条;中文不受影响
///      (对 UTF-8 高位字节调用 tolower 会把字节改坏,所以只折 ASCII);
///   3. `build()` 之后匹配是纯读,无锁、无分配,可以在 IO 线程上直接调用。
class Matcher {
 public:
  /// 从词表文件构建。
  ///
  /// 文件格式:UTF-8,一行一词;`#` 开头为注释,空行忽略;行尾空白与 CRLF 一并去掉。
  ///
  /// Args:
  ///   path: 词表文件路径;空串或文件不存在 = **不启用**(打 warning,不 fail-closed ——
  ///     词库配错不该把整个聊天挂掉)。
  ///
  /// Returns:
  ///   文件读到了返回 true;读不到返回 false(此时 `empty()` 为真,`hit` 恒 false)。
  bool load(const std::string& path);

  /// 直接用一组词构建(单测用,也便于将来做「按租户加载」)。
  ///
  /// Args:
  ///   words: 词表;空串与只含空白/注释符的条目被忽略。
  void build(const std::vector<std::string>& words);

  /// 词表是否为空(= 不拦任何东西)。
  bool empty() const { return words_ == 0; }

  /// 已加载的词条数(观测与测试用)。
  std::size_t size() const { return words_; }

  /// 文本是否命中任一敏感词。O(n),n = 文本字节数。
  ///
  /// Args:
  ///   text: 待检查的文本(UTF-8 字节序列)。
  ///
  /// Returns:
  ///   命中返回 true。
  bool hit(std::string_view text) const;

 private:
  /// 自动机的一个状态:出边(按字节)、失败指针、是否某个词的结尾(已按失败链合并)。
  struct Node {
    std::map<unsigned char, int> next;
    int fail = 0;
    bool output = false;
  };

  /// 从 `node` 读一个字节后的下一个状态(goto 失败就沿失败链回退)。
  int step(int node, unsigned char byte) const;

  std::vector<Node> nodes_{1};  // 0 号恒为根
  std::size_t words_ = 0;
};

}  // namespace sensitive
