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
* 文件名称          src/util/uuid.cpp
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
#include "util/uuid.h"

#include <random>

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     生成 32 字符随机十六进制串
// 参数说明     无
// 返回参数     std::string      32 字符小写十六进制 不含连字符
// 使用示例     const std::string id = random_uuid();
// 备注信息     每次调用用 std::random_device 重新播种 mt19937_64 取两个 64 位值拼 16 字节
//              不是 RFC 4122 UUID 未设置版本与变体位 只保证随机与定长
//              现用于给 /internal/send 拼系统消息的 client_msg_id 见 "sys-" + random_uuid()
//-------------------------------------------------------------------------------------------------------------------
std::string random_uuid() {
  std::random_device device;
  std::mt19937_64 engine(device());
  const uint64_t high = engine();
  const uint64_t low = engine();
  static constexpr char kHex[] = "0123456789abcdef";
  std::string output(32, '0');
  for (int i = 0; i < 16; ++i) {
    const uint64_t value = i < 8 ? high : low;
    const int shift = (7 - (i % 8)) * 8;
    const auto byte = static_cast<unsigned char>((value >> shift) & 0xFF);
    output[static_cast<std::size_t>(i * 2)] = kHex[byte >> 4];
    output[static_cast<std::size_t>(i * 2 + 1)] = kHex[byte & 0xF];
  }
  return output;
}
