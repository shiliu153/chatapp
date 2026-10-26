-- 搜索按 (user_a = ? OR user_b = ?) 过滤会话:user_a 有 uk_pair 前缀,user_b 没有索引。
ALTER TABLE im_conversation ADD KEY idx_user_b (user_b);
