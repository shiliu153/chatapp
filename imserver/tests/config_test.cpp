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
      {"IM_INTERNAL_SECRET", "internal"}};
  const auto cfg = Config::from_map(env);
  EXPECT_EQ(cfg.listen_ws, "127.0.0.1:9100");
  EXPECT_EQ(cfg.listen_http, "127.0.0.1:9101");
  EXPECT_EQ(cfg.io_threads, 2);
  EXPECT_EQ(cfg.max_frame, 8192u);
  EXPECT_TRUE(cfg.allowed_origins.empty());
}
