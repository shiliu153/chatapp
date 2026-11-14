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
* 文件名称          src/util/hmac.cpp
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
#include "util/hmac.h"

#include <openssl/evp.h>
#include <openssl/hmac.h>

#include <array>
#include <stdexcept>

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     HMAC-SHA256 计算 输出小写十六进制
// 参数说明     key              HMAC 密钥
//              data             待签名数据
// 返回参数     std::string      64 字符小写十六进制摘要
// 使用示例     hmac_sha256_hex(secret, payload);
// 备注信息     底层 OpenSSL HMAC 返回空指针时抛 std::runtime_error 大小写与 Django 侧 hexdigest 一致
//-------------------------------------------------------------------------------------------------------------------
std::string hmac_sha256_hex(std::string_view key, std::string_view data) {
  std::array<unsigned char, EVP_MAX_MD_SIZE> digest{};
  unsigned int length = 0;
  if (HMAC(EVP_sha256(), key.data(), static_cast<int>(key.size()),
           reinterpret_cast<const unsigned char*>(data.data()), data.size(), digest.data(),
           &length) == nullptr) {
    throw std::runtime_error("hmac failed");
  }
  static constexpr char kHex[] = "0123456789abcdef";
  std::string output;
  output.reserve(length * 2);
  for (unsigned int i = 0; i < length; ++i) {
    output.push_back(kHex[digest[i] >> 4]);
    output.push_back(kHex[digest[i] & 0xF]);
  }
  return output;
}
