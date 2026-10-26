#include <gtest/gtest.h>

#include <map>
#include <stdexcept>

#include "config.h"

TEST(ConfigTest, ParsesMysqlDsn) {
  const auto dsn = parse_mysql_dsn("mysql://imserver:secret@127.0.0.1:13306/chatapp_im");
  EXPECT_EQ(dsn.user, "imserver");
  EXPECT_EQ(dsn.password, "secret");
  EXPECT_EQ(dsn.host, "127.0.0.1");
  EXPECT_EQ(dsn.port, 13306);
  EXPECT_EQ(dsn.database, "chatapp_im");
}

TEST(ConfigTest, RejectsMissingJwtSecret) {
  std::map<std::string, std::string> env{
      {"IM_MYSQL_DSN", "mysql://u:p@127.0.0.1:3306/db"},
      {"IM_INTERNAL_SECRET", "internal"}};
  EXPECT_THROW(Config::from_map(env), std::runtime_error);
}

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
  EXPECT_DOUBLE_EQ(cfg.auth_rate_per_sec, 1.0);
  EXPECT_DOUBLE_EQ(cfg.auth_burst, 60.0);
  EXPECT_TRUE(cfg.allowed_origins.empty());
}

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

TEST(ConfigTest, RequiresMediaPrefix) {
  std::map<std::string, std::string> env{
      {"IM_MYSQL_DSN", "mysql://u:p@127.0.0.1:3306/db"},
      {"IM_JWT_SECRET", "jwt"},
      {"IM_INTERNAL_SECRET", "internal"}};
  EXPECT_THROW(Config::from_map(env), std::runtime_error);
}

TEST(ConfigTest, ReadsMediaPrefix) {
  std::map<std::string, std::string> env{
      {"IM_MYSQL_DSN", "mysql://u:p@127.0.0.1:3306/db"},
      {"IM_JWT_SECRET", "jwt"},
      {"IM_INTERNAL_SECRET", "internal"},
      {"IM_MEDIA_PREFIX", "http://127.0.0.1:8000/media/chat/"}};
  EXPECT_EQ(Config::from_map(env).media_prefix, "http://127.0.0.1:8000/media/chat/");
}

