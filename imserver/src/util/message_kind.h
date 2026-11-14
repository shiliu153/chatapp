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
* 文件名称          src/util/message_kind.h
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
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     消息 kind 整数映射成协议里的名字
// 参数说明     kind             库里存的 kind 整数 1 text 2 custom 3 image 4 voice
// 返回参数     std::string      text custom image voice
// 使用示例     kind_name(3);
// 备注信息     未知值按 text 兜底 与 Django 侧常量是跨栈契约 两边不要单改
//-------------------------------------------------------------------------------------------------------------------
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
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     按码点边界截断 UTF-8 文本
// 参数说明     text             待截断的 UTF-8 文本
//              max_chars        最多保留的码点数
// 返回参数     std::string      不超过 max_chars 个码点的前缀 未超长时原样返回
// 使用示例     truncate_utf8(preview, 120);
// 备注信息     只把非续字节 0b10xxxxxx 当字符起点 不会劈开多字节汉字 按字节截会得到非法 UTF-8
//-------------------------------------------------------------------------------------------------------------------
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
