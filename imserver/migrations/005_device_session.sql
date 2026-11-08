-- 多端在线(批次 K):会话版本从 im_user 单列下沉到 (user_id, client_type)。
-- 一个账号一个 App + 一个网页各一行,同端第二次登录把该行版本 +1,旧 token 随即对不上。
-- im_user.session_version 保留列但停止参与鉴权(独立清理项,本批不删)。
-- 注意:migrate.cpp 的 apply_sql 按分号切语句,注释里不能出现分号。
CREATE TABLE IF NOT EXISTS im_device_session (
  user_id BIGINT NOT NULL,
  client_type VARCHAR(8) NOT NULL,
  session_version BIGINT NOT NULL,
  PRIMARY KEY (user_id, client_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 桥接回填(不能省):老 token 没有 ct claim,按 app 兜底,它的 sv 等于 im_user.session_version,
-- 所以 app 与 web 两行必须用**同一个**值建行,否则升级瞬间老连接全部被 40101 拒掉。
INSERT IGNORE INTO im_device_session (user_id, client_type, session_version)
SELECT user_id, 'app', session_version FROM im_user WHERE session_version > 0;

INSERT IGNORE INTO im_device_session (user_id, client_type, session_version)
SELECT user_id, 'web', session_version FROM im_user WHERE session_version > 0;
