#include <gtest/gtest.h>

#include "util/hmac.h"

TEST(HmacTest, KnownVector) {
  EXPECT_EQ(hmac_sha256_hex("key", "The quick brown fox jumps over the lazy dog"),
            "f7bc83f430538424b13298e6aa6fb143ef4d59a14946175997479dbc2d1a3cd8");
}
