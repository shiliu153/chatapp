-- 引用回复(批次 L-2):只加可空列,不改既有列,在线安全(旧代码不读这两列也照常跑)。
-- ref_snapshot 是**服务端生成的 JSON 快照**,不是客户端传的内容 —— 只存快照,
-- 历史分页时不必再回查被引用消息(它可能早已被翻到内存之外)。
-- 注意:migrate.cpp 的 apply_sql 按分号切语句,注释里不能出现分号。
ALTER TABLE im_message
  ADD COLUMN ref_msg_id BIGINT UNSIGNED NULL,
  ADD COLUMN ref_snapshot TEXT NULL;
