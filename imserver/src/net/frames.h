#pragma once
#include <nlohmann/json.hpp>

#include <string>

#include "service/message_service.h"

inline std::string kind_name(int kind) {
  switch (kind) {
    case 2:
      return "custom";
    case 3:
      return "image";
    default:
      return "text";
  }
}

// 按 kind 拼推送帧:text 带 text,custom 带 custom,image 带 image
inline std::string build_message_frame(const SendResult& result, const SendRequest& request) {
  nlohmann::json data = {
      {"msg_id", std::to_string(result.msg_id)},
      {"seq", result.seq},
      {"from", "u" + std::to_string(request.from)},
      {"to", "u" + std::to_string(request.to)},
      {"kind", kind_name(request.kind)},
      {"ts", result.ts},
      {"revoked", false},
      {"from_profile",
       {{"nickname", result.from_nickname}, {"avatar", result.from_avatar}}}};
  if (request.kind == 2) {
    data["custom"] = request.custom;
  } else if (request.kind == 3) {
    data["image"] = request.image;
  } else {
    data["text"] = request.text;
  }
  return nlohmann::json{{"v", 1}, {"type", "message"}, {"data", data}}.dump();
}
