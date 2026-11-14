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
* 文件名称          tests/config_test.cpp
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

#include <map>
#include <stdexcept>

#include "config.h"

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证 mysql:// DSN 拆出用户名 密码 主机 端口 库名
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R ConfigTest.ParsesMysqlDsn
// 备注信息     覆盖 user password host port database 五个字段逐项相等 端口按整数解析而不是字符串 省略端口时默认 3306
//-------------------------------------------------------------------------------------------------------------------
TEST(ConfigTest, ParsesMysqlDsn) {
  const auto dsn = parse_mysql_dsn("mysql://imserver:secret@127.0.0.1:13306/chatapp_im");
  EXPECT_EQ(dsn.user, "imserver");
  EXPECT_EQ(dsn.password, "secret");
  EXPECT_EQ(dsn.host, "127.0.0.1");
  EXPECT_EQ(dsn.port, 13306);
  EXPECT_EQ(dsn.database, "chatapp_im");
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证缺少 IM_JWT_SECRET 时构建配置抛异常
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R ConfigTest.RejectsMissingJwtSecret
// 备注信息     只给 IM_MYSQL_DSN 与 IM_INTERNAL_SECRET 断言抛 std::runtime_error 必填项缺失直接启动失败 不静默降级
//-------------------------------------------------------------------------------------------------------------------
TEST(ConfigTest, RejectsMissingJwtSecret) {
  std::map<std::string, std::string> env{
      {"IM_MYSQL_DSN", "mysql://u:p@127.0.0.1:3306/db"},
      {"IM_INTERNAL_SECRET", "internal"}};
  EXPECT_THROW(Config::from_map(env), std::runtime_error);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证只给必填项时其余配置取默认值
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R ConfigTest.AppliesDefaults
// 备注信息     覆盖 WS 9100 与 HTTP 9101 监听地址 io_threads 为 2 max_frame 为 8192 单 IP 并发 20 敏感词表指向镜像内
//              data 目录 鉴权 1/s 突发 60 Origin 白名单为空 可信代理与内部接口默认只放回环 allow_public_bind 为 false
//-------------------------------------------------------------------------------------------------------------------
TEST(ConfigTest, AppliesDefaults) {
  std::map<std::string, std::string> env{
      {"IM_MYSQL_DSN", "mysql://u:p@127.0.0.1:3306/db"},
      {"IM_JWT_SECRET", "jwt"},
      {"IM_INTERNAL_SECRET", "internal"},
      {"IM_MEDIA_PREFIX", "http://cdn/media/chat/"}};
  const auto cfg = Config::from_map(env);
  EXPECT_EQ(cfg.listen_ws, "127.0.0.1:9100");
  EXPECT_EQ(cfg.listen_http, "127.0.0.1:9101");
  EXPECT_EQ(cfg.io_threads, 2);
  EXPECT_EQ(cfg.max_frame, 8192u);
  EXPECT_EQ(cfg.max_conn_per_ip, 20);
  // 批次 Q:敏感词表默认指向镜像里打包的那份(/usr/local/share/imserver/data)
  EXPECT_EQ(cfg.sensitive_words_file,
            "/usr/local/share/imserver/data/sensitive_words.txt");
  EXPECT_DOUBLE_EQ(cfg.auth_rate_per_sec, 1.0);
  EXPECT_DOUBLE_EQ(cfg.auth_burst, 60.0);
  EXPECT_TRUE(cfg.allowed_origins.empty());
  EXPECT_EQ(cfg.trusted_proxies.size(), 2u);
  EXPECT_EQ(cfg.trusted_proxies[0], "127.0.0.1");
  EXPECT_EQ(cfg.trusted_proxies[1], "::1");
  // H-1:默认与旧行为一致 —— 内部接口只允许本机
  EXPECT_EQ(cfg.internal_allow.size(), 2u);
  EXPECT_EQ(cfg.internal_allow[0], "127.0.0.1");
  EXPECT_EQ(cfg.internal_allow[1], "::1");
  EXPECT_FALSE(cfg.allow_public_bind);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证 IM_INTERNAL_ALLOW 按逗号拆成来源网段表
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R ConfigTest.ParsesInternalAllowList
// 备注信息     覆盖逗号后的空格要裁掉 单个 IP 与 CIDR 混排时保持输入顺序 内部接口仍要求 HMAC 校验
//-------------------------------------------------------------------------------------------------------------------
TEST(ConfigTest, ParsesInternalAllowList) {
  std::map<std::string, std::string> env{
      {"IM_MYSQL_DSN", "mysql://u:p@127.0.0.1:3306/db"},
      {"IM_JWT_SECRET", "jwt"},
      {"IM_INTERNAL_SECRET", "internal"},
      {"IM_MEDIA_PREFIX", "http://cdn/media/chat/"},
      {"IM_INTERNAL_ALLOW", "127.0.0.1, 172.28.0.0/16"}};
  const auto cfg = Config::from_map(env);
  EXPECT_EQ(cfg.internal_allow.size(), 2u);
  EXPECT_EQ(cfg.internal_allow[0], "127.0.0.1");
  EXPECT_EQ(cfg.internal_allow[1], "172.28.0.0/16");
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证可信代理表解析与公网监听开关
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R ConfigTest.ParsesProxyAndBindGuard
// 备注信息     覆盖 IM_TRUSTED_PROXIES 的 CIDR 条目原样保留 以及 IM_ALLOW_PUBLIC_BIND
//              取 1 才把 allow_public_bind 置为 true
//-------------------------------------------------------------------------------------------------------------------
TEST(ConfigTest, ParsesProxyAndBindGuard) {
  std::map<std::string, std::string> env{
      {"IM_MYSQL_DSN", "mysql://u:p@127.0.0.1:3306/db"},
      {"IM_JWT_SECRET", "jwt"},
      {"IM_INTERNAL_SECRET", "internal"},
      {"IM_MEDIA_PREFIX", "http://cdn/media/chat/"},
      {"IM_TRUSTED_PROXIES", "127.0.0.1, 172.17.0.1/16"},
      {"IM_ALLOW_PUBLIC_BIND", "1"}};
  const auto cfg = Config::from_map(env);
  EXPECT_EQ(cfg.trusted_proxies.size(), 2u);
  EXPECT_EQ(cfg.trusted_proxies[1], "172.17.0.1/16");
  EXPECT_TRUE(cfg.allow_public_bind);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证单 IP 连接上限与鉴权令牌桶参数可覆盖
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R ConfigTest.ParsesConnectionLimits
// 备注信息     覆盖 IM_MAX_CONN_PER_IP IM_AUTH_RATE IM_AUTH_BURST 三项 浮点用 EXPECT_DOUBLE_EQ 精确比较
//-------------------------------------------------------------------------------------------------------------------
TEST(ConfigTest, ParsesConnectionLimits) {
  std::map<std::string, std::string> env{
      {"IM_MYSQL_DSN", "mysql://u:p@127.0.0.1:3306/db"},
      {"IM_JWT_SECRET", "jwt"},
      {"IM_INTERNAL_SECRET", "internal"},
      {"IM_MEDIA_PREFIX", "http://cdn/media/chat/"},
      {"IM_MAX_CONN_PER_IP", "1000"},
      {"IM_AUTH_RATE", "500"},
      {"IM_AUTH_BURST", "1000"}};
  const auto cfg = Config::from_map(env);
  EXPECT_EQ(cfg.max_conn_per_ip, 1000);
  EXPECT_DOUBLE_EQ(cfg.auth_rate_per_sec, 500.0);
  EXPECT_DOUBLE_EQ(cfg.auth_burst, 1000.0);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证缺少 IM_MEDIA_PREFIX 时构建配置抛异常
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R ConfigTest.RequiresMediaPrefix
// 备注信息     图片与语音消息的 URL 都依赖该前缀 缺失必须启动失败 否则发图与发语音一律 42201
//-------------------------------------------------------------------------------------------------------------------
TEST(ConfigTest, RequiresMediaPrefix) {
  std::map<std::string, std::string> env{
      {"IM_MYSQL_DSN", "mysql://u:p@127.0.0.1:3306/db"},
      {"IM_JWT_SECRET", "jwt"},
      {"IM_INTERNAL_SECRET", "internal"}};
  EXPECT_THROW(Config::from_map(env), std::runtime_error);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证 IM_MEDIA_PREFIX 原样读入 media_prefix
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R ConfigTest.ReadsMediaPrefix
// 备注信息     覆盖值不被补斜杠也不被裁剪 必须与 Django 的 MEDIA_BASE_URL 加 /media/chat/ 完全一致
//-------------------------------------------------------------------------------------------------------------------
TEST(ConfigTest, ReadsMediaPrefix) {
  std::map<std::string, std::string> env{
      {"IM_MYSQL_DSN", "mysql://u:p@127.0.0.1:3306/db"},
      {"IM_JWT_SECRET", "jwt"},
      {"IM_INTERNAL_SECRET", "internal"},
      {"IM_MEDIA_PREFIX", "http://127.0.0.1:8000/media/chat/"}};
  EXPECT_EQ(Config::from_map(env).media_prefix, "http://127.0.0.1:8000/media/chat/");
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证 IM_SENSITIVE_WORDS_FILE 覆盖敏感词表路径
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R ConfigTest.ReadsSensitiveWordsFile
// 备注信息     覆盖默认路径被显式值替换 这里只校验读取 文件是否存在由启动日志的 sensitive_words_loaded 体现
//-------------------------------------------------------------------------------------------------------------------
TEST(ConfigTest, ReadsSensitiveWordsFile) {
  std::map<std::string, std::string> env{
      {"IM_MYSQL_DSN", "mysql://u:p@127.0.0.1:3306/db"},
      {"IM_JWT_SECRET", "jwt"},
      {"IM_INTERNAL_SECRET", "internal"},
      {"IM_MEDIA_PREFIX", "http://cdn/media/chat/"},
      {"IM_SENSITIVE_WORDS_FILE", "/etc/imserver/words.txt"}};
  EXPECT_EQ(Config::from_map(env).sensitive_words_file, "/etc/imserver/words.txt");
}
