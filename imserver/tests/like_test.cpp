#include <gtest/gtest.h>

#include "util/like.h"

TEST(LikeTest, WrapsKeywordWithPercent) {
  EXPECT_EQ(like_pattern("火锅"), "%火锅%");
}

TEST(LikeTest, EscapesWildcardsAndEscapeChar) {
  EXPECT_EQ(like_pattern("100%"), "%100!%%");
  EXPECT_EQ(like_pattern("a_b"), "%a!_b%");
  EXPECT_EQ(like_pattern("!!"), "%!!!!%");
}

TEST(LikeTest, KeepsPlainTextUntouched) {
  EXPECT_EQ(like_pattern("c++ 2.0"), "%c++ 2.0%");
  EXPECT_EQ(like_pattern(""), "%%");
}
