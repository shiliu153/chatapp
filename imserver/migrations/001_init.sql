CREATE TABLE IF NOT EXISTS im_schema_version (
  version INT NOT NULL PRIMARY KEY,
  applied_at BIGINT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS im_user (
  user_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  nickname VARCHAR(64) NOT NULL DEFAULT '',
  avatar_url VARCHAR(512) NOT NULL DEFAULT '',
  updated_at BIGINT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS im_conversation (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_a BIGINT UNSIGNED NOT NULL,
  user_b BIGINT UNSIGNED NOT NULL,
  last_seq BIGINT UNSIGNED NOT NULL DEFAULT 0,
  last_msg_id BIGINT UNSIGNED NULL,
  last_msg_at BIGINT NOT NULL DEFAULT 0,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uk_pair (user_a, user_b)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS im_conversation_state (
  owner_id BIGINT UNSIGNED NOT NULL,
  conv_id BIGINT UNSIGNED NOT NULL,
  unread INT UNSIGNED NOT NULL DEFAULT 0,
  read_seq BIGINT UNSIGNED NOT NULL DEFAULT 0,
  deleted TINYINT NOT NULL DEFAULT 0,
  updated_at BIGINT NOT NULL,
  PRIMARY KEY (owner_id, conv_id),
  KEY idx_owner_updated (owner_id, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS im_message (
  msg_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  conv_id BIGINT UNSIGNED NOT NULL,
  seq BIGINT UNSIGNED NOT NULL,
  from_id BIGINT UNSIGNED NOT NULL,
  to_id BIGINT UNSIGNED NOT NULL,
  kind TINYINT NOT NULL,
  body TEXT NOT NULL,
  client_msg_id VARCHAR(64) NOT NULL,
  created_at BIGINT NOT NULL,
  revoked_at BIGINT NULL,
  UNIQUE KEY uk_conv_seq (conv_id, seq),
  UNIQUE KEY uk_from_client (from_id, client_msg_id),
  KEY idx_conv_msg (conv_id, msg_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS im_blacklist (
  owner_id BIGINT UNSIGNED NOT NULL,
  peer_id BIGINT UNSIGNED NOT NULL,
  created_at BIGINT NOT NULL,
  PRIMARY KEY (owner_id, peer_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT IGNORE INTO im_user (user_id, nickname, avatar_url, updated_at)
VALUES (0, '系统通知', '', 0);
