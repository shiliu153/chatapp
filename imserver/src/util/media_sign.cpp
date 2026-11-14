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
* 文件名称          src/util/media_sign.cpp
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
#include "util/media_sign.h"

#include <chrono>

#include "util/hmac.h"

namespace {

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     取当前 Unix 秒时间戳
// 参数说明     无
// 返回参数     int64_t          秒级时间戳
// 使用示例     int64_t now = now_seconds();
// 备注信息     走 system_clock 墙钟 供 sign_url 在 now 传 0 时取当前时间
//-------------------------------------------------------------------------------------------------------------------
int64_t now_seconds() {
  return std::chrono::duration_cast<std::chrono::seconds>(
             std::chrono::system_clock::now().time_since_epoch())
      .count();
}

// 从 "http://host/media/chat/" 里取出 "/media/chat/"
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     从媒体前缀 URL 里截出路径部分
// 参数说明     media_prefix     IM_MEDIA_PREFIX 形如 http://host/media/chat/
// 返回参数     std::string      路径前缀 形如 /media/chat/
// 使用示例     path_prefix_of("http://127.0.0.1:8000/media/chat/");
// 备注信息     没有 :// 时按相对路径处理 取不到首个 / 时原样返回
//-------------------------------------------------------------------------------------------------------------------
std::string path_prefix_of(const std::string& media_prefix) {
  const auto scheme = media_prefix.find("://");
  const auto start = scheme == std::string::npos ? 0 : scheme + 3;
  const auto slash = media_prefix.find('/', start);
  return slash == std::string::npos ? media_prefix : media_prefix.substr(slash);
}

}  // namespace

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     构造媒体签名器 推导路径前缀并兜底 TTL
// 参数说明     secret           签名密钥 为空表示不启用签名
//              ttl              签名有效期秒 非正数按 86400 兜底
//              media_prefix     IM_MEDIA_PREFIX 形如 http://host/media/chat/
// 返回参数     void             无返回值
// 使用示例     MediaSigner signer(secret, 3600, "http://127.0.0.1:8000/media/chat/");
// 备注信息     path_prefix_ 由 media_prefix 推导 密钥为空时所有签名方法原样返回 URL
//-------------------------------------------------------------------------------------------------------------------
MediaSigner::MediaSigner(std::string secret, int ttl, std::string media_prefix)
    : secret_(std::move(secret)),
      media_prefix_(std::move(media_prefix)),
      path_prefix_(path_prefix_of(media_prefix_)),
      ttl_(ttl > 0 ? ttl : 86400) {}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     去 query 并校验 URL 属于媒体前缀
// 参数说明     url              待规范化的绝对 URL
// 返回参数     std::optional<std::string>  去掉 query 的 URL 前缀不匹配时返回 nullopt
// 使用示例     auto clean = signer.canonical(url);
// 备注信息     只保留第一个 ? 之前的部分 前缀按从头整段匹配 不做大小写折叠
//-------------------------------------------------------------------------------------------------------------------
std::optional<std::string> MediaSigner::canonical(const std::string& url) const {
  const auto clean = url.substr(0, url.find('?'));
  if (media_prefix_.empty() || clean.rfind(media_prefix_, 0) != 0) {
    return std::nullopt;
  }
  return clean;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     给聊天媒体 URL 追加 e 与 s 两个签名参数
// 参数说明     url              待签名的绝对 URL 不属于媒体前缀时原样返回
//              now              签名基准秒 传 0 表示取当前时间
// 返回参数     std::string      带 ?e=<exp>&s=<hex> 的 URL
// 使用示例     std::string signed_url = signer.sign_url(url);
// 备注信息     exp 按整点对齐 exp = now - now % 3600 + ttl 同一小时内同一张图 URL 稳定
//-------------------------------------------------------------------------------------------------------------------
std::string MediaSigner::sign_url(const std::string& url, int64_t now) const {
  const auto clean = canonical(url);
  if (!clean.has_value() || !enabled()) {
    return url;
  }
  const auto path_at = clean->find(path_prefix_);
  if (path_at == std::string::npos) {
    return url;
  }
  const auto path = clean->substr(path_at);
  const int64_t moment = now > 0 ? now : now_seconds();
  const int64_t expires = moment - moment % 3600 + ttl_;
  const auto signature = hmac_sha256_hex(secret_, path + "\n" + std::to_string(expires));
  return *clean + "?e=" + std::to_string(expires) + "&s=" + signature;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     就地给 JSON 对象里若干 URL 字段加签名
// 参数说明     object           待处理的 JSON 对象
//              keys             要签名的字段名列表
//              now              签名基准秒 传 0 表示取当前时间
// 返回参数     void             无返回值
// 使用示例     signer.sign_media(frame, {"url"});
// 备注信息     未启用签名或不是 JSON object 时直接返回 字段不存在或非字符串时跳过该字段
//-------------------------------------------------------------------------------------------------------------------
void MediaSigner::sign_media(nlohmann::json& object,
                             std::initializer_list<const char*> keys, int64_t now) const {
  if (!enabled() || !object.is_object()) {
    return;
  }
  for (const char* key : keys) {
    if (!object.contains(key) || !object[key].is_string()) {
      continue;
    }
    object[key] = sign_url(object[key].get<std::string>(), now);
  }
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     给图片对象的 url 与 thumb_url 加签名
// 参数说明     image            图片 JSON 对象
//              now              签名基准秒 传 0 表示取当前时间
// 返回参数     void             无返回值
// 使用示例     signer.sign_image(image);
// 备注信息     等价于 sign_media(image, {"url", "thumb_url"}, now)
//-------------------------------------------------------------------------------------------------------------------
void MediaSigner::sign_image(nlohmann::json& image, int64_t now) const {
  sign_media(image, {"url", "thumb_url"}, now);
}
