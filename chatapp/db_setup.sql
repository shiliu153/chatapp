CREATE DATABASE IF NOT EXISTS chatapp_dev
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'chatapp'@'localhost' IDENTIFIED BY '<YOUR_DB_PASSWORD>';
GRANT ALL PRIVILEGES ON chatapp_dev.* TO 'chatapp'@'localhost';
-- Django 测试运行器会创建/销毁 test_ 前缀的测试库,需要单独授权
GRANT ALL PRIVILEGES ON `test_chatapp_dev`.* TO 'chatapp'@'localhost';
FLUSH PRIVILEGES;
