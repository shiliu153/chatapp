#pragma once
#include <string>
#include <string_view>

std::string hmac_sha256_hex(std::string_view key, std::string_view data);
