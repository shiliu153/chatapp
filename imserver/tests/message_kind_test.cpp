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
* 文件名称          tests/message_kind_test.cpp
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证消息 kind 整数映射为协议里的类型名
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R MessageKind.MapsKindToProtocolName
// 备注信息     覆盖 1 为 text 2 为 custom 3 为 image 4 为 voice 未知值 99 按 text 兜底 保证客户端不会收到不认识的枚举
//-------------------------------------------------------------------------------------------------------------------
TEST(MessageKind, MapsKindToProtocolName) {
  EXPECT_EQ(kind_name(1), "text");
  EXPECT_EQ(kind_name(2), "custom");
  EXPECT_EQ(kind_name(3), "image");
  EXPECT_EQ(kind_name(4), "voice");
  // 未知值按 text 兜底:宁可显示成文本,也不给客户端一个它不认识的枚举
  EXPECT_EQ(kind_name(99), "text");
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证 UTF-8 文本按字符截断且不劈开码点
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R MessageKind.TruncateUtf8KeepsWholeCharacters
// 备注信息     覆盖短文本原样返回 130 个 ASCII 截到 120 字节 130 个三字节汉字截到 120
//              字符即 360 字节 且正好停在字符边界 四字节 emoji 同理 长度恰好等于上限时不截断
//-------------------------------------------------------------------------------------------------------------------
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
