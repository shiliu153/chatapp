#include <gtest/gtest.h>
#include <unistd.h>

#include <filesystem>
#include <fstream>
#include <string>

#include "util/sensitive.h"

namespace {

/// 写一份临时词表并返回路径(用例结束自行删除)。
std::string write_temp(const std::string& name, const std::string& content) {
  const auto path = std::filesystem::temp_directory_path() /
                    ("im_sensitive_" + std::to_string(::getpid()) + "_" + name + ".txt");
  std::ofstream file(path, std::ios::binary | std::ios::trunc);
  file << content;
  file.close();
  return path.string();
}

}  // namespace

TEST(SensitiveTest, HitsChineseWordInsideSentence) {
  sensitive::Matcher matcher;
  matcher.build({"违禁词"});
  EXPECT_FALSE(matcher.empty());
  EXPECT_EQ(matcher.size(), 1u);
  EXPECT_TRUE(matcher.hit("这是一句违禁词啊"));
  EXPECT_TRUE(matcher.hit("违禁词"));
  // 半个词不算命中(按 UTF-8 字节走不会在字中间对上)
  EXPECT_FALSE(matcher.hit("违禁"));
  EXPECT_FALSE(matcher.hit("禁词"));
  EXPECT_FALSE(matcher.hit("你好"));
}

TEST(SensitiveTest, IgnoresAsciiCase) {
  sensitive::Matcher matcher;
  matcher.build({"badword"});
  EXPECT_TRUE(matcher.hit("BADWORD"));
  EXPECT_TRUE(matcher.hit("BadWord"));
  EXPECT_TRUE(matcher.hit("不会吧 BADWORD 真的假的"));
  EXPECT_FALSE(matcher.hit("bad word"));
}

TEST(SensitiveTest, MatchesAtTextBoundaries) {
  sensitive::Matcher matcher;
  matcher.build({"赌博"});
  // 开头 / 结尾 / 整串:三个边界都不能差一个字节
  EXPECT_TRUE(matcher.hit("赌博网站"));
  EXPECT_TRUE(matcher.hit("一起去赌博"));
  EXPECT_TRUE(matcher.hit("赌博"));
  EXPECT_FALSE(matcher.hit("赌"));
  EXPECT_FALSE(matcher.hit("博"));
}

TEST(SensitiveTest, HandlesOverlappingAndMultipleWords) {
  sensitive::Matcher matcher;
  // 「he」是「she」的真后缀:失败链没接对时,「s h e」会漏掉「he」
  matcher.build({"he", "she", "洗钱"});
  EXPECT_TRUE(matcher.hit("she"));
  EXPECT_TRUE(matcher.hit("xhe"));
  EXPECT_TRUE(matcher.hit("帮忙洗钱"));
  EXPECT_FALSE(matcher.hit("sh"));
  EXPECT_EQ(matcher.size(), 3u);
}

TEST(SensitiveTest, ScansLongTextInOnePass) {
  sensitive::Matcher matcher;
  matcher.build({"洗钱", "badword"});
  // 4KB 纯中文(≈1365 字)不含敏感词:必须正常返回 false
  std::string clean;
  while (clean.size() < 4096) {
    clean += "你好";
  }
  EXPECT_FALSE(matcher.hit(clean));
  // 敏感词放在 4KB 文本的最末尾:必须扫到底才认
  clean += "去洗钱吧";
  EXPECT_TRUE(matcher.hit(clean));
}

TEST(SensitiveTest, EmptyTableNeverBlocks) {
  sensitive::Matcher matcher;
  matcher.build({});
  EXPECT_TRUE(matcher.empty());
  EXPECT_FALSE(matcher.hit("随便什么内容"));

  // 词表文件不存在 = 不启用(不 fail-closed):load 返回 false,hit 恒 false
  sensitive::Matcher missing;
  EXPECT_FALSE(missing.load("/nonexistent/imserver/sensitive_words.txt"));
  EXPECT_TRUE(missing.empty());
  EXPECT_FALSE(missing.hit("洗钱"));
}

TEST(SensitiveTest, LoadSkipsCommentsAndBlankLines) {
  const auto path = write_temp("comments",
                               "# 这是注释\r\n"
                               "\r\n"
                               "洗钱  \r\n"
                               "   \r\n"
                               "# 也是注释\r\n"
                               "badword\r\n");
  sensitive::Matcher matcher;
  EXPECT_TRUE(matcher.load(path));
  EXPECT_EQ(matcher.size(), 2u);
  // 行尾空格 / CRLF 不应成为词的一部分
  EXPECT_TRUE(matcher.hit("帮我洗钱"));
  EXPECT_TRUE(matcher.hit("BADWORD"));
  std::filesystem::remove(path);
}

TEST(SensitiveTest, ShippedWordlistIsUsable) {
  // 随镜像打包的那份词表必须真的能读、能拦(文件格式写坏了这里就红)
  const std::string path = std::string(IM_DATA_DIR) + "/sensitive_words.txt";
  sensitive::Matcher matcher;
  EXPECT_TRUE(matcher.load(path));
  EXPECT_FALSE(matcher.empty());
  EXPECT_GE(matcher.size(), 20u);
  EXPECT_TRUE(matcher.hit("我要举报有人在买卖毒品"));
  EXPECT_FALSE(matcher.hit("今天天气不错,一起吃个饭?"));
}
