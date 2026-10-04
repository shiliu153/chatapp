-- 本地开发库与账号初始化(MySQL 8)
-- 用法: 把下面的 <YOUR_DB_PASSWORD> 换成你自己的口令(与 chatapp/.env 的 DB_PASSWORD 一致),再执行:
--   mysql -u root -p < db_setup.sql
-- 口令只存在于本文件与 .env 中;.env 不入库,本文件请勿把真实口令提交回来。

CREATE DATABASE IF NOT EXISTS chatapp_dev
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'chatapp'@'localhost' IDENTIFIED BY '<YOUR_DB_PASSWORD>';
GRANT ALL PRIVILEGES ON chatapp_dev.* TO 'chatapp'@'localhost';
-- Django 测试运行器会创建/销毁 test_ 前缀的测试库,需要单独授权
GRANT ALL PRIVILEGES ON `test_chatapp_dev`.* TO 'chatapp'@'localhost';
FLUSH PRIVILEGES;
