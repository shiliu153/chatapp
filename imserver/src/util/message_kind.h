#pragma once
#include <cstddef>
#include <string>

/// 消息 kind(库里存的整数)→ 协议里的名字。
///
/// 1=text 2=custom(贴纸 / 系统灰条)3=image 4=voice。
/// 下行 `message` 帧与引用快照(`ref.kind`)共用这一份映射 ——
/// 两边各写一份就会出现「气泡显示图片、引用块显示 text」这种错位。
///
/// Args:
///   kind: 库里存的 kind 整数。
///
/// Returns:
///   `text` / `custom` / `image` / `voice`;未知值按 `text` 兜底。
inline std::string kind_name(int kind) {
  switch (kind) {
    case 2:
      return "custom";
    case 3:
      return "image";
    case 4:
      return "voice";
    default:
      return "text";
  }
}

/// 按**字符**(而不是字节)截断 UTF-8 文本。
///
/// 为什么不能按字节截:`std::string::substr(0, 120)` 会把一个三字节的汉字劈成
/// 半个,发到客户端就是乱码 / 非法 UTF-8。这里只在码点边界上切。
///
/// Args:
///   text: 待截断的 UTF-8 文本。
///   max_chars: 最多保留的码点数。
///
/// Returns:
///   不超过 `max_chars` 个码点的前缀(未超长时原样返回)。
inline std::string truncate_utf8(const std::string& text, std::size_t max_chars) {
  std::size_t count = 0;
  for (std::size_t i = 0; i < text.size(); ++i) {
    // 0b10xxxxxx 是续字节,只有非续字节才算一个新的字符起点。
    if ((static_cast<unsigned char>(text[i]) & 0xC0) == 0x80) {
      continue;
    }
    if (count == max_chars) {
      return text.substr(0, i);
    }
    ++count;
  }
  return text;
}
