-- 多选删除(批次 T):只记「谁不想再看到哪条」,不碰消息本体、不通知对端。
-- 主键 (user_id, msg_id) 正好服务「我的历史里排除我隐藏的」这个唯一读法,
-- 反向索引给「注销账号时按 msg_id 清理」用。
-- 不加外键(与既有表一致,靠应用层清理)。
-- 注意:migrate.cpp 的 apply_sql 按分号切语句,注释里不能出现分号。
CREATE TABLE IF NOT EXISTS im_message_hidden (
  user_id BIGINT UNSIGNED NOT NULL,
  msg_id BIGINT UNSIGNED NOT NULL,
  created_at BIGINT NOT NULL,
  PRIMARY KEY (user_id, msg_id),
  KEY idx_hidden_msg (msg_id, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
