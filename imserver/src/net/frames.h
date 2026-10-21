#pragma once
#include <nlohmann/json.hpp>

#include <string>

#include "service/message_service.h"

inline std::string build_message_frame(const SendResult& result, uint64_t from, uint64_t to,
                                       const std::string& kind, const std::string& text,
                                       const nlohmann::json& custom) {
  nlohmann::json data = {
      {"msg_id", std::to_string(result.msg_id)},
      {"seq", result.seq},
      {"from", "u" + std::to_string(from)},
      {"to", "u" + std::to_string(to)},
      {"kind", kind},
      {"ts", result.ts},
      {"revoked", false},
      {"from_profile",
       {{"nickname", result.from_nickname}, {"avatar", result.from_avatar}}}};
  if (kind == "text") {
    data["text"] = text;
  } else {
    data["custom"] = custom;
  }
  return nlohmann::json{{"v", 1}, {"type", "message"}, {"data", data}}.dump();
}
