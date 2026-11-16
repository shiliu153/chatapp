-- 聊天搜索(第五轮审计 M-2):给 im_message.body 建 ngram 分词的 FULLTEXT 索引。
-- 改之前搜索是前导通配 LIKE '%关键词%',任何索引都用不上,单次成本与「我参与的全部
-- 文本消息总量」成正比(口径见 docs/ops/imserver.md §16.4)。
-- 改成 MATCH(m.body) AGAINST(... IN BOOLEAN MODE) 之后先由本索引收窄候选行,
-- 再交给 LIKE 做精确判定 —— 扫描量因此从「我的全部消息」降到「关键词命中的消息」。
-- ngram_token_size 用 MySQL 8 默认值 2:两字及以上关键词才有索引项,单字搜不到属预期。
-- 注意:迁移执行器按分号切语句,本文件注释里不能出现分号。
ALTER TABLE im_message ADD FULLTEXT KEY ft_message_body (body) WITH PARSER ngram;
