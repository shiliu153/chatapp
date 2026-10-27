#pragma once
#include <cstdint>
#include <initializer_list>
#include <nlohmann/json.hpp>
#include <optional>
#include <string>

// 聊天图片的限时签名:与 Django 的 im/media_sign.py 逐字节一致。
//
// 签名串 = path + "\n" + exp;签名 = HMAC-SHA256(secret, 签名串) 的小写 hex。
// exp 按整点对齐(now - now % 3600 + ttl),保证同一小时内同一张图给出同一个 URL。
class MediaSigner {
 public:
  MediaSigner(std::string secret, int ttl, std::string media_prefix);

  // 是否启用签名(密钥为空 = 不签,开发环境)
  bool enabled() const { return !secret_.empty(); }
  // IM_MEDIA_PREFIX 的路径部分(如 /media/chat/),用于从绝对 URL 里取 path
  const std::string& path_prefix() const { return path_prefix_; }

  // 去掉 query 并校验属于 media_prefix;不合法返回 nullopt
  std::optional<std::string> canonical(const std::string& url) const;

  // 给 URL 加 ?e=&s=(先规范化);未启用时原样返回
  std::string sign_url(const std::string& url, int64_t now = 0) const;

  // 就地给对象里若干 URL 字段签名(图片: url/thumb_url;语音: url)
  void sign_media(nlohmann::json& object, std::initializer_list<const char*> keys,
                  int64_t now = 0) const;

  // 图片的薄封装
  void sign_image(nlohmann::json& image, int64_t now = 0) const;

 private:
  std::string secret_;
  std::string media_prefix_;
  std::string path_prefix_;
  int ttl_;
};
