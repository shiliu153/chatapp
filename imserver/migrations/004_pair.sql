-- 聊天权限:只有存在配对关系的两个用户才能互发消息。
-- Django 在配对创建时 add、解除配对/拉黑时 remove。user_a < user_b 保证无向唯一。
CREATE TABLE IF NOT EXISTS im_pair (
  user_a BIGINT NOT NULL,
  user_b BIGINT NOT NULL,
  created_at BIGINT NOT NULL,
  PRIMARY KEY (user_a, user_b)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
