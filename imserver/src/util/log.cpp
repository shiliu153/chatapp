#include "util/log.h"

#include <chrono>
#include <iostream>
#include <mutex>

#include <nlohmann/json.hpp>

namespace {

std::mutex& log_mutex() {
  static std::mutex mutex;
  return mutex;
}

int64_t now_ms() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(
             std::chrono::system_clock::now().time_since_epoch())
      .count();
}

void emit(const char* level, std::string_view event,
          std::initializer_list<std::pair<std::string, std::string>> fields) {
  nlohmann::json line = {{"ts", now_ms()}, {"level", level}, {"event", event}};
  for (const auto& [key, value] : fields) {
    line[key] = value;
  }
  const std::lock_guard<std::mutex> lock(log_mutex());
  std::cout << line.dump() << std::endl;
}

}  // namespace

void log_info(std::string_view event,
              std::initializer_list<std::pair<std::string, std::string>> fields) {
  emit("info", event, fields);
}

void log_error(std::string_view event,
               std::initializer_list<std::pair<std::string, std::string>> fields) {
  emit("error", event, fields);
}
