-- CI 等价依赖容器的初始化脚本。
-- 业务库 chatapp_dev 由 compose 里的 MYSQL_DATABASE 自动创建;这里只补「测试库授权」,
-- 与 .github/workflows/backend.yml「给测试库授权」那一步等价。
-- 理由:Django 测试运行器会自行 CREATE DATABASE test_<DB_NAME>,而 MYSQL_USER 建出的
-- 账号只有 MYSQL_DATABASE 一个库的权限,建库会 1044 被拒。
GRANT ALL PRIVILEGES ON `test_chatapp_dev`.* TO 'chatapp'@'%';
FLUSH PRIVILEGES;
