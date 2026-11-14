/*********************************************************************************************************************
* chat_app 自建 IM 服务端（imserver）是本项目唯一的 IM 后端，C++20 实现，对外提供 WebSocket :9100 与 HTTP :9101
* Copyright (c) 2026 shiliu153
*
* 本文件是 chat_app 自建 IM 服务端的一部分
*
* 额外注明：
* 本文件使用 MIT 开源许可证协议 许可申明英文版见仓库根目录 LICENSE 文件
* 欢迎各位使用并传播本程序 但修改内容时必须保留作者的版权声明（即本声明）
*
* 文件名称          src/net/guard.cpp
* 项目名称          chat_app / imserver
* 公司名称          个人项目（shiliu153）
* 版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
* 开发环境          CMake 3.22 + g++ (C++20) Linux x86_64
* 适用平台          Linux x86_64 服务端
* 仓库地址          https://github.com/shiliu153/chatapp
*
* 修改记录
* 日期              作者               备注
* 2026-11-14        shiliu153          补齐文件头与函数注释
********************************************************************************************************************/
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     把字符串就地转成小写 ASCII
// 参数说明     value            待转换串 按值传入
// 返回参数     std::string      全小写的副本
// 使用示例     const auto host = lower_ascii("Example.COM");
// 备注信息     只折叠 ASCII 字母 非 ASCII 字节原样保留 host 与 Origin 的大小写无关比较靠它
//-------------------------------------------------------------------------------------------------------------------
std::string lower_ascii(std::string value) {
  std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
    return static_cast<char>(std::tolower(c));
  });
  return value;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     去掉字符串两端的 ASCII 空白
// 参数说明     input            原始串
// 返回参数     std::string      去掉首尾空格 制表符 CR LF 后的副本
// 使用示例     const auto header = trim_ascii(real_ip_header);
// 备注信息     全空白输入返回空串 不处理中间空白 也不动其他控制字符
//-------------------------------------------------------------------------------------------------------------------
std::string trim_ascii(const std::string& input) {
  const auto begin = input.find_first_not_of(" \t\r\n");
  if (begin == std::string::npos) {
    return "";
  }
  const auto end = input.find_last_not_of(" \t\r\n");
  return input.substr(begin, end - begin + 1);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     去掉字符串末尾的所有斜杠
// 参数说明     value            待处理串 按值传入
// 返回参数     std::string      去掉结尾 / 的副本
// 使用示例     const auto origin = strip_trailing_slashes("https://a.com/");
// 备注信息     白名单与 Origin 两侧都要归一 否则 https://a.com/ 与 https://a.com 会被判不等
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     解析 host[:port] 归一化出主机与端口
// 参数说明     raw              可能带 scheme userinfo 路径 结尾斜杠的 authority 串
// 返回参数     Authority        host 已转小写 端口 80 / 443 一律视为未写
// 使用示例     const auto authority = parse_authority("https://Example.com:443/");
// 备注信息     IPv6 必须写成 [::1]:9100 方括号形式 括号不闭合时返回空 host 由调用方拒绝
//-------------------------------------------------------------------------------------------------------------------
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
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     把 IPv4-mapped IPv6 还原成 IPv4
// 参数说明     peer             原始对端地址
// 返回参数     address          归一后的地址 其他情况原样返回
// 使用示例     const auto peer = normalize_peer(endpoint.address());
// 备注信息     ::ffff:127.0.0.1 不归一则规则表要为同一网段写两份
//-------------------------------------------------------------------------------------------------------------------
address normalize_peer(const address& peer) {
  if (peer.is_v6()) {
    const auto v6 = peer.to_v6();
    if (v6.is_v4_mapped()) {
      return address(v6.to_v4());
    }
  }
  return peer;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     判定地址是否落在给定 CIDR 网段内
// 参数说明     base             网段基地址
//              bits             前缀长度 IPv4 0..32 IPv6 0..128
//              peer             待判定地址
// 返回参数     bool             落在网段内返回 true
// 使用示例     const bool hit = cidr_contains(base, 8, peer);
// 备注信息     地址族不同直接返回 false bits 小于等于 0 视为全匹配
//              IPv4 按整型掩码 IPv6 按字节逐段掩码 逐段只取剩余位数
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     解析 host:port 形式的监听地址
// 参数说明     raw              形如 127.0.0.1:9101 或 [::1]:9100 的串
// 返回参数     ListenAddr       解析出的地址与端口
// 使用示例     const auto listen = net_guard::parse_listen("127.0.0.1:9101");
// 备注信息     端口取最后一个冒号之后 因此 IPv6 必须写成 [::1]:9100
//              缺冒号 端口非数字 端口越界 host 非法都抛 std::invalid_argument
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     判定地址是否为回环地址
// 参数说明     value            待判定的对端地址
// 返回参数     bool             是回环返回 true
// 使用示例     net_guard::is_loopback(listen.address);
// 备注信息     直接转调 boost::asio 的 is_loopback 不做 IPv4-mapped 归一
//-------------------------------------------------------------------------------------------------------------------
bool is_loopback(const address& value) { return value.is_loopback(); }

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     构造只信任本机的默认代理表
// 参数说明     无
// 返回参数     ProxyTrust       含 127.0.0.1/32 与 ::1/128 两条规则
// 使用示例     auto trust = net_guard::ProxyTrust::loopback_only();
// 备注信息     默认部署下 nginx 与本服务同机 客户端 IP 只可能由本机代理写入
//-------------------------------------------------------------------------------------------------------------------
ProxyTrust ProxyTrust::loopback_only() {
  ProxyTrust trust;
  trust.rules_.push_back({boost::asio::ip::make_address("127.0.0.1"), 32});
  trust.rules_.push_back({boost::asio::ip::make_address("::1"), 128});
  return trust;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     从配置项解析可信代理网段表
// 参数说明     entries          形如 127.0.0.1 或 10.0.0.0/8 的条目列表 空串跳过
// 返回参数     ProxyTrust       解析后的规则表
// 使用示例     auto allow = net_guard::ProxyTrust::from_list({"10.0.0.0/8"});
// 备注信息     未写 / 时 IPv4 按 32 位 IPv6 按 128 位 即单个主机
//              地址非法或前缀越界抛 std::invalid_argument 由启动流程直接失败
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     判定直连对端是否命中可信代理表
// 参数说明     peer             直连对端地址
// 返回参数     bool             命中任一规则返回 true
// 使用示例     trust.trusted(peer_addr);
// 备注信息     先归一 IPv4-mapped IPv6 再逐条 cidr_contains 规则条数很少 线性扫描即可
//-------------------------------------------------------------------------------------------------------------------
bool ProxyTrust::trusted(const address& peer) const {
  const auto normalized = normalize_peer(peer);
  return std::any_of(rules_.begin(), rules_.end(), [&normalized](const Rule& rule) {
    return cidr_contains(rule.base, rule.bits, normalized);
  });
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     计算用于限流的客户端 IP
// 参数说明     peer             直连对端地址
//              real_ip_header     X-Real-IP 头的原始值 可为空
//              trust            可信代理表
// 返回参数     std::string      客户端 IP 文本
// 使用示例     const auto ip = net_guard::client_ip(peer, header, trust);
// 备注信息     对端不可信直接返回对端地址 头里不是合法单 IP 同样回退
//              限流 key 取这个结果 所以绝不能把伪造串放进去
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     校验浏览器 WebSocket 握手的 Origin
// 参数说明     origin           Origin 头的原始值 空串表示没发
//              host             Host 头的原始值
//              allowed          IM_ALLOWED_ORIGINS 白名单 为空表示未配置
// 返回参数     bool             放行返回 true
// 使用示例     net_guard::origin_allowed(origin, host, cfg.allowed_origins);
// 备注信息     无 Origin 放行 原生 App 与压测脚本不发这个头
//              白名单非空时按整串比较 忽略大小写与结尾 /
//              未配白名单按同源兜底 host 任一为空即拒 只比 host 与非默认端口
//-------------------------------------------------------------------------------------------------------------------
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
