#include "net/guard.h"

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <stdexcept>

namespace net_guard {
namespace {

using boost::asio::ip::address;
using boost::asio::ip::address_v4;
using boost::asio::ip::address_v6;

std::string lower_ascii(std::string value) {
  std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
    return static_cast<char>(std::tolower(c));
  });
  return value;
}

std::string trim_ascii(const std::string& input) {
  const auto begin = input.find_first_not_of(" \t\r\n");
  if (begin == std::string::npos) {
    return "";
  }
  const auto end = input.find_last_not_of(" \t\r\n");
  return input.substr(begin, end - begin + 1);
}

std::string strip_trailing_slashes(std::string value) {
  while (!value.empty() && value.back() == '/') {
    value.pop_back();
  }
  return value;
}

/// host[:port] 的归一化结果;`:80` / `:443` 一律视为「没有写端口」。
struct Authority {
  std::string host;
  std::string port;
};

Authority parse_authority(const std::string& raw) {
  Authority out;
  std::string rest = trim_ascii(raw);
  if (const auto scheme_end = rest.find("://"); scheme_end != std::string::npos) {
    rest = rest.substr(scheme_end + 3);
  }
  rest = strip_trailing_slashes(rest);
  if (const auto slash = rest.find('/'); slash != std::string::npos) {
    rest = rest.substr(0, slash);
  }
  if (const auto at = rest.rfind('@'); at != std::string::npos) {
    rest = rest.substr(at + 1);
  }
  if (!rest.empty() && rest.front() == '[') {
    const auto close = rest.find(']');
    if (close == std::string::npos) {
      return out;
    }
    out.host = lower_ascii(rest.substr(1, close - 1));
    if (close + 1 < rest.size() && rest[close + 1] == ':') {
      out.port = rest.substr(close + 2);
    }
  } else if (const auto colon = rest.rfind(':'); colon != std::string::npos) {
    out.host = lower_ascii(rest.substr(0, colon));
    out.port = rest.substr(colon + 1);
  } else {
    out.host = lower_ascii(rest);
  }
  if (out.port == "80" || out.port == "443") {
    out.port.clear();
  }
  return out;
}

/// 把 IPv4-mapped IPv6(`::ffff:127.0.0.1`)还原成 IPv4,否则规则表要写两份。
address normalize_peer(const address& peer) {
  if (peer.is_v6()) {
    const auto v6 = peer.to_v6();
    if (v6.is_v4_mapped()) {
      return address(v6.to_v4());
    }
  }
  return peer;
}

bool cidr_contains(const address& base, int bits, const address& peer) {
  if (base.is_v4() != peer.is_v4()) {
    return false;
  }
  if (peer.is_v4()) {
    const auto base_bits = base.to_v4().to_uint();
    const auto peer_bits = peer.to_v4().to_uint();
    if (bits <= 0) {
      return true;
    }
    const std::uint32_t mask =
        bits >= 32 ? 0xFFFFFFFFu : (0xFFFFFFFFu << (32 - bits));
    return (base_bits & mask) == (peer_bits & mask);
  }
  const auto base_bytes = base.to_v6().to_bytes();
  const auto peer_bytes = peer.to_v6().to_bytes();
  int remaining = bits;
  for (std::size_t i = 0; i < base_bytes.size() && remaining > 0; ++i) {
    const int take = std::min(8, remaining);
    const auto mask = static_cast<std::uint8_t>(take >= 8 ? 0xFF : (0xFF << (8 - take)) & 0xFF);
    if ((base_bytes[i] & mask) != (peer_bytes[i] & mask)) {
      return false;
    }
    remaining -= take;
  }
  return true;
}

}  // namespace

ListenAddr parse_listen(const std::string& raw) {
  const auto colon = raw.rfind(':');
  if (colon == std::string::npos || colon == 0 || colon + 1 >= raw.size()) {
    throw std::invalid_argument("invalid listen address: " + raw);
  }
  int port = 0;
  try {
    port = std::stoi(raw.substr(colon + 1));
  } catch (const std::exception&) {
    throw std::invalid_argument("invalid listen port: " + raw);
  }
  if (port < 0 || port > 65535) {
    throw std::invalid_argument("listen port out of range: " + raw);
  }
  boost::system::error_code ec;
  const auto host = raw.substr(0, colon);
  const auto address = boost::asio::ip::make_address(host, ec);
  if (ec) {
    throw std::invalid_argument("invalid listen host: " + host);
  }
  ListenAddr out;
  out.address = address;
  out.port = static_cast<unsigned short>(port);
  return out;
}

bool is_loopback(const address& value) { return value.is_loopback(); }

ProxyTrust ProxyTrust::loopback_only() {
  ProxyTrust trust;
  trust.rules_.push_back({boost::asio::ip::make_address("127.0.0.1"), 32});
  trust.rules_.push_back({boost::asio::ip::make_address("::1"), 128});
  return trust;
}

ProxyTrust ProxyTrust::from_list(const std::vector<std::string>& entries) {
  ProxyTrust trust;
  for (const auto& raw : entries) {
    const auto entry = trim_ascii(raw);
    if (entry.empty()) {
      continue;
    }
    const auto slash = entry.find('/');
    const auto host = slash == std::string::npos ? entry : entry.substr(0, slash);
    boost::system::error_code ec;
    const auto base = boost::asio::ip::make_address(host, ec);
    if (ec) {
      throw std::invalid_argument("invalid trusted proxy: " + entry);
    }
    int bits = base.is_v4() ? 32 : 128;
    if (slash != std::string::npos) {
      try {
        bits = std::stoi(entry.substr(slash + 1));
      } catch (const std::exception&) {
        throw std::invalid_argument("invalid trusted proxy prefix: " + entry);
      }
      const int max_bits = base.is_v4() ? 32 : 128;
      if (bits < 0 || bits > max_bits) {
        throw std::invalid_argument("trusted proxy prefix out of range: " + entry);
      }
    }
    trust.rules_.push_back({base, bits});
  }
  return trust;
}

bool ProxyTrust::trusted(const address& peer) const {
  const auto normalized = normalize_peer(peer);
  return std::any_of(rules_.begin(), rules_.end(), [&normalized](const Rule& rule) {
    return cidr_contains(rule.base, rule.bits, normalized);
  });
}

std::string client_ip(const address& peer, const std::string& real_ip_header,
                      const ProxyTrust& trust) {
  if (trust.trusted(peer)) {
    const auto header = trim_ascii(real_ip_header);
    boost::system::error_code ec;
    const auto parsed = boost::asio::ip::make_address(header, ec);
    if (!ec) {
      return parsed.to_string();
    }
  }
  return peer.to_string();
}

bool origin_allowed(const std::string& origin, const std::string& host,
                    const std::vector<std::string>& allowed) {
  const auto value = strip_trailing_slashes(trim_ascii(origin));
  if (value.empty()) {
    // 原生 App / 压测脚本不发 Origin;浏览器一定会发。
    return true;
  }
  if (!allowed.empty()) {
    const auto normalized = lower_ascii(value);
    return std::any_of(allowed.begin(), allowed.end(), [&normalized](const std::string& item) {
      return lower_ascii(strip_trailing_slashes(trim_ascii(item))) == normalized;
    });
  }
  // 未配置白名单时按同源兜底:攻击者的页面在自己的域名下,Host 对不上就拒。
  const auto from_origin = parse_authority(value);
  const auto from_host = parse_authority(host);
  if (from_origin.host.empty() || from_host.host.empty()) {
    return false;
  }
  return from_origin.host == from_host.host && from_origin.port == from_host.port;
}

}  // namespace net_guard
