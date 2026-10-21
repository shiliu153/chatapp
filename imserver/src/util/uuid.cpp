#include "util/uuid.h"

#include <random>

std::string random_uuid() {
  std::random_device device;
  std::mt19937_64 engine(device());
  const uint64_t high = engine();
  const uint64_t low = engine();
  static constexpr char kHex[] = "0123456789abcdef";
  std::string output(32, '0');
  for (int i = 0; i < 16; ++i) {
    const uint64_t value = i < 8 ? high : low;
    const int shift = (7 - (i % 8)) * 8;
    const auto byte = static_cast<unsigned char>((value >> shift) & 0xFF);
    output[static_cast<std::size_t>(i * 2)] = kHex[byte >> 4];
    output[static_cast<std::size_t>(i * 2 + 1)] = kHex[byte & 0xF];
  }
  return output;
}
