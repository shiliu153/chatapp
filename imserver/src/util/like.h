#pragma once
#include <string>

/// 把 LIKE 模式里的特殊字符转义。
///
/// 转义字符选 `!` 而不是反斜杠:反斜杠在 SQL 字符串字面量里要写两次、
/// 且受 `NO_BACKSLASH_ESCAPES` 影响,而 `!` 在 SQL 里没有特殊含义。
/// 调用方 SQL 必须写 `LIKE ? ESCAPE '!'`。
///
/// Args:
///   input: 用户输入的关键词(未经转义)。
///
/// Returns:
///   转义后的关键词,`!`/`%`/`_` 前各插一个 `!`。
inline std::string escape_like(const std::string& input) {
  std::string out;
  out.reserve(input.size() + 8);
  for (const char c : input) {
    if (c == '!' || c == '%' || c == '_') {
      out.push_back('!');
    }
    out.push_back(c);
  }
  return out;
}

/// 用户关键词 → `%关键词%` 模式串(供 prepared statement 绑定)。
///
/// Args:
///   keyword: 用户输入的关键词。
///
/// Returns:
///   带前后通配符的 LIKE 模式串。
inline std::string like_pattern(const std::string& keyword) {
  return "%" + escape_like(keyword) + "%";
}
