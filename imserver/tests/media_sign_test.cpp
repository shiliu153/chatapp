#include <gtest/gtest.h>

#include <optional>
#include <string>

#include "util/media_sign.h"

TEST(MediaSignerTest, MatchesSharedVector) {
  // 与 Django im/media_sign.py 的共享测试向量必须一致(exp 由整点对齐 + ttl 算出)
  MediaSigner signer("test-media-secret", 86400, "http://cdn/media/chat/");
  const auto signed_url =
      signer.sign_url("http://cdn/media/chat/2026/10/12-abc.jpg", 1761782400);
  EXPECT_EQ(signed_url,
            "http://cdn/media/chat/2026/10/12-abc.jpg?e=1761868800&s="
            "b57407845446ea5b208d43263f9b8d1a404ee807c8f77aeadaf02d6ab8aba718");
}

TEST(MediaSignerTest, CanonicalStripsQueryAndRejectsForeignUrl) {
  MediaSigner signer("s", 86400, "http://cdn/media/chat/");
  EXPECT_EQ(signer.canonical("http://cdn/media/chat/a.jpg?e=1&s=2"),
            std::optional<std::string>("http://cdn/media/chat/a.jpg"));
  EXPECT_FALSE(signer.canonical("http://evil/a.jpg").has_value());
  EXPECT_FALSE(signer.canonical("").has_value());
}

TEST(MediaSignerTest, DisabledSignerLeavesUrlUntouched) {
  MediaSigner signer("", 86400, "http://cdn/media/chat/");
  EXPECT_FALSE(signer.enabled());
  const std::string url = "http://cdn/media/chat/a.jpg";
  EXPECT_EQ(signer.sign_url(url, 1761782400), url);
}

TEST(MediaSignerTest, SignsImageObjectInPlace) {
  MediaSigner signer("test-media-secret", 86400, "http://cdn/media/chat/");
  nlohmann::json image = {{"url", "http://cdn/media/chat/a.jpg?e=1&s=old"},
                          {"thumb_url", "http://cdn/media/chat/a_thumb.jpg"}};
  signer.sign_image(image, 1761782400);
  EXPECT_EQ(image["url"].get<std::string>().find("s=old"), std::string::npos);
  EXPECT_NE(image["thumb_url"].get<std::string>().find("?e="), std::string::npos);
}
