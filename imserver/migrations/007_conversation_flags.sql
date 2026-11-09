-- 会话置顶 / 免打扰(批次 N):只在 owner 自己那一行加两个标志位,不改既有列,
-- 旧代码不读这两列也照常跑(在线安全)。
-- pinned_at 存「置顶时刻」的毫秒时间戳而不是 bool:列表要按「置顶时间倒序」排,
-- 0 = 未置顶,这个语义与 read_seq / unread 同表同键(owner 维度)。
-- muted 只影响客户端表现(静音图标 + 未读只显示灰点),服务端不抑制任何东西 ——
-- 本项目不做离线推送,没有可抑制的通道,未读统计口径也不改。
-- 注意:migrate.cpp 的 apply_sql 按分号切语句,注释里不能出现分号。
ALTER TABLE im_conversation_state
  ADD COLUMN pinned_at BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN muted TINYINT NOT NULL DEFAULT 0;
