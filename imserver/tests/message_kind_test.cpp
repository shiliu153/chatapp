/// 消息 kind 映射与引用摘要截断的单元测试(批次 L-2)。
///
/// 这两件事都是「下行帧 / 引用快照」共用的纯函数,错一个就会同时影响气泡与引用块:
///   - `kind_name`:引用快照里的 `ref.kind` 必须与消息自己的 `kind` 同名,
///     否则客户端会拿到「气泡是图片、引用块写 text」这种对不上的数据;
///   - `truncate_utf8`:引用摘要按**字符**截断。按字节截会把汉字劈成半个,
///     发出去就是非法 UTF-8。
#include <gtest/gtest.h>

#include <string>

#include "util/message_kind.h"

TEST(MessageKind, MapsKindToProtocolName) {
  EXPECT_EQ(kind_name(1), "text");
  EXPECT_EQ(kind_name(2), "custom");
  EXPECT_EQ(kind_name(3), "image");
  EXPECT_EQ(kind_name(4), "voice");
  // 未知值按 text 兜底:宁可显示成文本,也不给客户端一个它不认识的枚举
  EXPECT_EQ(kind_name(99), "text");
}

TEST(MessageKind, TruncateUtf8KeepsWholeCharacters) {
  // 短文本原样返回
  EXPECT_EQ(truncate_utf8("今晚吃饭?", 120), "今晚吃饭?");
  // 130 个汉字截到 120 个 —— 不能出现半个汉字(字节数会是 360,不是 120)
  const std::string long_text(130, 'a');
  const std::string ascii = truncate_utf8(long_text, 120);
  EXPECT_EQ(ascii.size(), 120U);

  std::string chinese;
  for (int i = 0; i < 130; ++i) {
    chinese += "引";
  }
  const std::string truncated = truncate_utf8(chinese, 120);
  // 120 个汉字 = 360 字节。按字节截会得到 120 字节(40 个汉字 + 半个),
  // 这里必须正好停在字符边界上。
  EXPECT_EQ(truncated.size(), 120U * 3U);
  EXPECT_EQ(truncated, chinese.substr(0, 120U * 3U));

  // 四字节字符(emoji)同理:不能被劈成半个代理/半个码点
  std::string emoji;
  for (int i = 0; i < 5; ++i) {
    emoji += "😀";
  }
  EXPECT_EQ(truncate_utf8(emoji, 2).size(), 2U * 4U);
  EXPECT_EQ(truncate_utf8(emoji, 2), emoji.substr(0, 2U * 4U));

  // 恰好等于上限时不截断
  EXPECT_EQ(truncate_utf8("你好", 2), "你好");
  EXPECT_EQ(truncate_utf8("你好", 1), "你");
}
