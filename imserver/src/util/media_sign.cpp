#include "util/media_sign.h"

#include <chrono>

#include "util/hmac.h"

namespace {

int64_t now_seconds() {
  return std::chrono::duration_cast<std::chrono::seconds>(
             std::chrono::system_clock::now().time_since_epoch())
      .count();
}

// 从 "http://host/media/chat/" 里取出 "/media/chat/"
std::string path_prefix_of(const std::string& media_prefix) {
  const auto scheme = media_prefix.find("://");
  const auto start = scheme == std::string::npos ? 0 : scheme + 3;
  const auto slash = media_prefix.find('/', start);
  return slash == std::string::npos ? media_prefix : media_prefix.substr(slash);
}

}  // namespace

MediaSigner::MediaSigner(std::string secret, int ttl, std::string media_prefix)
    : secret_(std::move(secret)),
      media_prefix_(std::move(media_prefix)),
      path_prefix_(path_prefix_of(media_prefix_)),
      ttl_(ttl > 0 ? ttl : 86400) {}

std::optional<std::string> MediaSigner::canonical(const std::string& url) const {
  const auto clean = url.substr(0, url.find('?'));
  if (media_prefix_.empty() || clean.rfind(media_prefix_, 0) != 0) {
    return std::nullopt;
  }
  return clean;
}

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

void MediaSigner::sign_image(nlohmann::json& image, int64_t now) const {
  sign_media(image, {"url", "thumb_url"}, now);
}
