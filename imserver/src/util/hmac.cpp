#include "util/hmac.h"

#include <openssl/evp.h>
#include <openssl/hmac.h>

#include <array>
#include <stdexcept>

std::string hmac_sha256_hex(std::string_view key, std::string_view data) {
  std::array<unsigned char, EVP_MAX_MD_SIZE> digest{};
  unsigned int length = 0;
  if (HMAC(EVP_sha256(), key.data(), static_cast<int>(key.size()),
           reinterpret_cast<const unsigned char*>(data.data()), data.size(), digest.data(),
           &length) == nullptr) {
    throw std::runtime_error("hmac failed");
  }
  static constexpr char kHex[] = "0123456789abcdef";
  std::string output;
  output.reserve(length * 2);
  for (unsigned int i = 0; i < length; ++i) {
    output.push_back(kHex[digest[i] >> 4]);
    output.push_back(kHex[digest[i] & 0xF]);
  }
  return output;
}
