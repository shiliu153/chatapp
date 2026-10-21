#pragma once
#include <initializer_list>
#include <string>
#include <string_view>
#include <utility>

void log_info(std::string_view event,
              std::initializer_list<std::pair<std::string, std::string>> fields = {});
void log_error(std::string_view event,
               std::initializer_list<std::pair<std::string, std::string>> fields = {});
