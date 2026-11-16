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
* 文件名称          src/util/fulltext.h
* 项目名称          chat_app / imserver
* 公司名称          个人项目（shiliu153）
* 版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
* 开发环境          CMake 3.22 + g++ (C++20) Linux x86_64
* 适用平台          Linux x86_64 服务端
* 仓库地址          https://github.com/shiliu153/chatapp
*
* 修改记录
* 日期              作者               备注
* 2026-11-16        shiliu153          新增文件 聊天搜索改 FULLTEXT 后的关键词转义
********************************************************************************************************************/
#pragma once
#include <string>
#include <string_view>

/// BOOLEAN MODE 里有语法含义、必须挡在用户输入之外的操作符(第五轮审计 M-2)。
///
/// `%` 与 `_` **不在**其中:它们在 LIKE 里是通配符,在 FULLTEXT 里只是普通字符,
/// 因此「搜索 100%」在 MATCH 下天然按字面匹配(转义责任见 `util/like.h`)。
constexpr std::string_view kBooleanOperators = "+-@\"()~*<>";

/// 剥掉 BOOLEAN MODE 操作符并去掉首尾空白,得到真正参与匹配的词。
///
/// 关键词改成走 `MATCH ... AGAINST` 之后,用户输入会直接进 BOOLEAN MODE 的语法,
/// 所以 `+ - @ " ( ) ~ * < >` 必须挡掉。换成空格而不是直接删(删会把两段独立的字
/// 粘成一个假词)。按字节遍历,UTF-8 多字节序列原样保留。
///
/// Args:
///   keyword: 用户输入的关键词(未经转义)。
///
/// Returns:
///   只剩普通字符的关键词;全被剥空时返回空串。
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     剥掉 BOOLEAN MODE 操作符并去首尾空白
// 参数说明     keyword          用户输入的关键词
// 返回参数     std::string      只剩普通字符的关键词 可能为空串
// 使用示例     boolean_keyword("+火锅 -店");
// 备注信息     操作符换成空格是为了保留词边界 boolean_phrase 再按空白切词
//-------------------------------------------------------------------------------------------------------------------
inline std::string boolean_keyword(const std::string& keyword) {
  std::string out;
  out.reserve(keyword.size() + 1);
  for (const char c : keyword) {
    out.push_back(kBooleanOperators.find(c) == std::string_view::npos ? c : ' ');
  }
  const auto first = out.find_first_not_of(" \t\r\n");
  if (first == std::string::npos) {
    return "";
  }
  const auto last = out.find_last_not_of(" \t\r\n");
  return out.substr(first, last - first + 1);
}

/// 用户关键词 → 可安全交给 `AGAINST(... IN BOOLEAN MODE)` 的查询串。
///
/// 每个以空白分开的词各自包成一条双引号短语,短语之间用空格连接。BOOLEAN MODE 里
/// 不带 `+` 的多个词是「可选」语义(命中任意一个就算),所以这个串给的是**超集**:
/// 精确与否由调用方再补一道 `LIKE` 判定 —— 这是「换实现但不改可见性」的机械保证。
///
/// 单字符的词(含单个 emoji)在 ngram 分词下建不出索引项,会被 MySQL 忽略,
/// 因此只由单字符组成的词(例如 `a b`)搜不到,属预期(§16.4)。
///
/// Args:
///   keyword: 用户输入的关键词(未经转义)。
///
/// Returns:
///   `"火锅"` 这种短语串;没有任何可查的词时返回空串。
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     关键词转成 BOOLEAN MODE 的多短语查询串
// 参数说明     keyword          用户输入的关键词
// 返回参数     std::string      "词一" "词二" 形态 无可查的词时为空串
// 使用示例     boolean_phrase("火锅 店");
// 备注信息     返回空串说明关键词里没有可交给索引的词 调用方应直接按无命中返回 别把空短语丢给 MySQL
//-------------------------------------------------------------------------------------------------------------------
inline std::string boolean_phrase(const std::string& keyword) {
  const std::string terms = boolean_keyword(keyword);
  std::string out;
  bool open = false;
  for (const char c : terms) {
    if (c == ' ' || c == '\t' || c == '\r' || c == '\n') {
      if (open) {
        out.push_back('"');
        open = false;
      }
      continue;
    }
    if (!open) {
      if (!out.empty()) {
        out.push_back(' ');
      }
      out.push_back('"');
      open = true;
    }
    out.push_back(c);
  }
  if (open) {
    out.push_back('"');
  }
  return out;
}
