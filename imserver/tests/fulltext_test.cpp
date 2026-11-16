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
* 文件名称          tests/fulltext_test.cpp
* 项目名称          chat_app / imserver
* 公司名称          个人项目（shiliu153）
* 版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
* 开发环境          CMake 3.22 + g++ (C++20) Linux x86_64
* 适用平台          Linux x86_64 服务端
* 仓库地址          https://github.com/shiliu153/chatapp
*
* 修改记录
* 日期              作者               备注
* 2026-11-16        shiliu153          新增文件 覆盖 FULLTEXT 关键词转义
********************************************************************************************************************/

#include <gtest/gtest.h>

#include "util/fulltext.h"

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证普通关键词原样保留
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R FulltextTest.KeepsPlainKeywordUntouched
// 备注信息     中文两字关键词与 ASCII 数字都不该被改动 它们在 ngram 下各有索引项
//-------------------------------------------------------------------------------------------------------------------
TEST(FulltextTest, KeepsPlainKeywordUntouched) {
  EXPECT_EQ(boolean_keyword("火锅"), "火锅");
  EXPECT_EQ(boolean_keyword("100"), "100");
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证 BOOLEAN MODE 操作符被换成空格
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R FulltextTest.StripsBooleanOperators
// 备注信息     换成空格而不是删掉 否则 +火锅-店 会被粘成一个假词 火锅店
//-------------------------------------------------------------------------------------------------------------------
TEST(FulltextTest, StripsBooleanOperators) {
  EXPECT_EQ(boolean_keyword("+火锅-店"), "火锅 店");
  EXPECT_EQ(boolean_keyword("~*()\"><@"), "");
  EXPECT_EQ(boolean_keyword("  \"a b\"  "), "a b");
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证 % 与 _ 不被当成操作符剥掉
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R FulltextTest.KeepsLikeWildcardChars
// 备注信息     这两个字符在 FULLTEXT 里只是普通字符 「搜索 100%」因此天然按字面匹配
//-------------------------------------------------------------------------------------------------------------------
TEST(FulltextTest, KeepsLikeWildcardChars) {
  EXPECT_EQ(boolean_keyword("100%"), "100%");
  EXPECT_EQ(boolean_keyword("a_b"), "a_b");
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证「有没有可交给索引的词」按 UTF-8 字符数判定
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R FulltextTest.DetectsIndexableTerm
// 备注信息     单字(火)按字节判会算成 3 个字符 所以这里只认码点 多词里任一个够长就 true
//-------------------------------------------------------------------------------------------------------------------
TEST(FulltextTest, DetectsIndexableTerm) {
  EXPECT_TRUE(has_indexable_term("火锅"));
  EXPECT_TRUE(has_indexable_term("c++ 2.0"));
  EXPECT_TRUE(has_indexable_term("火锅 店"));
  EXPECT_FALSE(has_indexable_term("火"));
  EXPECT_FALSE(has_indexable_term("a b"));
  EXPECT_FALSE(has_indexable_term("+-"));
  EXPECT_FALSE(has_indexable_term(""));
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证关键词被包成带双引号的短语
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R FulltextTest.WrapsPhraseInQuotes
// 备注信息     双引号让整串按字面匹配 这是 FULLTEXT 一侧最接近 LIKE 子串语义的写法
//-------------------------------------------------------------------------------------------------------------------
TEST(FulltextTest, WrapsPhraseInQuotes) {
  EXPECT_EQ(boolean_phrase("火锅"), "\"火锅\"");
  EXPECT_EQ(boolean_phrase("  火锅  "), "\"火锅\"");
  EXPECT_EQ(boolean_phrase("100%"), "\"100%\"");
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证带空白的多个词各自成短语
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R FulltextTest.SplitsWordsIntoPhrases
// 备注信息     BOOLEAN MODE 里不带 + 的多词是「命中任意一个就算」的或语义 因此结果是超集 由 LIKE 收口
//-------------------------------------------------------------------------------------------------------------------
TEST(FulltextTest, SplitsWordsIntoPhrases) {
  EXPECT_EQ(boolean_phrase("火锅 店"), "\"火锅\" \"店\"");
  EXPECT_EQ(boolean_phrase("+火锅 -店"), "\"火锅\" \"店\"");
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证没有可查的词时返回空串
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R FulltextTest.BlankWhenNothingLeft
// 备注信息     空串让调用方(MessageRepo::search)直接按无命中返回 不发空短语给 MySQL
//-------------------------------------------------------------------------------------------------------------------
TEST(FulltextTest, BlankWhenNothingLeft) {
  EXPECT_EQ(boolean_phrase("+-"), "");
  EXPECT_EQ(boolean_phrase("   "), "");
  EXPECT_EQ(boolean_phrase(""), "");
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证剥完什么都不剩时关键词为空串
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R FulltextTest.BlankKeywordWhenNothingLeft
// 备注信息     与 BlankWhenNothingLeft 一起钉住两层转义的边界 都是空串而不是残留引号或空格
//-------------------------------------------------------------------------------------------------------------------
TEST(FulltextTest, BlankKeywordWhenNothingLeft) {
  EXPECT_EQ(boolean_keyword("+-"), "");
  EXPECT_EQ(boolean_keyword("   "), "");
  EXPECT_EQ(boolean_keyword(""), "");
}
