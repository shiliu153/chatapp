-- 会话版本:登录时 Django 递增并同步过来,WS 鉴权比对 token 里的 sv。
-- 默认 0 表示「尚未同步」,旧 token(sv=0)在过渡期内仍然放行。
ALTER TABLE im_user ADD COLUMN session_version BIGINT NOT NULL DEFAULT 0;
