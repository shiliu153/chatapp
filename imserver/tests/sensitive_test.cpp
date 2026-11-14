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
* 文件名称          tests/sensitive_test.cpp
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证中文词在句中命中
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R HitsChineseWordInsideSentence
// 备注信息     按 UTF-8 字节建树 词在句中与整串都命中 半个词与无关文本不命中 词表大小为 1
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证 ASCII 大小写不敏感
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R IgnoresAsciiCase
// 备注信息     BADWORD 与 BadWord 都命中 混排中文的句子也命中 被空格拆开的 bad word 不命中
//-------------------------------------------------------------------------------------------------------------------
TEST(SensitiveTest, IgnoresAsciiCase) {
  sensitive::Matcher matcher;
  matcher.build({"badword"});
  EXPECT_TRUE(matcher.hit("BADWORD"));
  EXPECT_TRUE(matcher.hit("BadWord"));
  EXPECT_TRUE(matcher.hit("不会吧 BADWORD 真的假的"));
  EXPECT_FALSE(matcher.hit("bad word"));
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证命中覆盖文本三种边界
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R MatchesAtTextBoundaries
// 备注信息     词在开头 结尾 整串三个位置都命中 单个字 赌 与 博 不算命中
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证后缀重叠词不互相吞掉
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R HandlesOverlappingAndMultipleWords
// 备注信息     he 是 she 的真后缀 失败链接错会漏掉 xhe 断言 size 为 3 且 sh 不命中
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证超长文本单遍扫描
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R ScansLongTextInOnePass
// 备注信息     4KB 纯中文无词返回 false 敏感词追加到文本末尾后必须扫到底才返回 true
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证空词表与缺文件不拦截
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R EmptyTableNeverBlocks
// 备注信息     build 空表后 hit 恒 false 词表文件不存在时 load 返回 false 不 fail-closed
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证词表加载跳过注释与空行
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R LoadSkipsCommentsAndBlankLines
// 备注信息     井号注释 空行 CRLF 与行尾空格都忽略 断言词条数为 2 且命中正常
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证随镜像词表可用
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R ShippedWordlistIsUsable
// 备注信息     读 IM_DATA_DIR 下的词表 断言至少 20 条 命中涉毒文本且不误伤日常闲聊
//-------------------------------------------------------------------------------------------------------------------
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
