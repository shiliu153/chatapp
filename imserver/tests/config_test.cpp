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

TEST(ConfigTest, ReadsSensitiveWordsFile) {
  std::map<std::string, std::string> env{
      {"IM_MYSQL_DSN", "mysql://u:p@127.0.0.1:3306/db"},
      {"IM_JWT_SECRET", "jwt"},
      {"IM_INTERNAL_SECRET", "internal"},
      {"IM_MEDIA_PREFIX", "http://cdn/media/chat/"},
      {"IM_SENSITIVE_WORDS_FILE", "/etc/imserver/words.txt"}};
  EXPECT_EQ(Config::from_map(env).sensitive_words_file, "/etc/imserver/words.txt");
}

TEST(ConfigTest, ReadsInstanceIdForMultiNode) {
  std::map<std::string, std::string> env{
      {"IM_MYSQL_DSN", "mysql://u:p@127.0.0.1:3306/db"},
      {"IM_JWT_SECRET", "jwt"},
      {"IM_INTERNAL_SECRET", "internal"},
      {"IM_MEDIA_PREFIX", "http://cdn/media/chat/"},
      {"IM_INSTANCE_ID", "edge"}};
  EXPECT_EQ(Config::from_map(env).instance_id, "edge");
}

TEST(ConfigTest, EmptyInstanceIdMeansSingleNode) {
  // 显式给空串 = 单实例:不写 owner 键、不订阅跨节点频道(行为与 #288 之前一致)。
  std::map<std::string, std::string> env{
      {"IM_MYSQL_DSN", "mysql://u:p@127.0.0.1:3306/db"},
      {"IM_JWT_SECRET", "jwt"},
      {"IM_INTERNAL_SECRET", "internal"},
      {"IM_MEDIA_PREFIX", "http://cdn/media/chat/"},
      {"IM_INSTANCE_ID", ""}};
  EXPECT_TRUE(Config::from_map(env).instance_id.empty());
}
