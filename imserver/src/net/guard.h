#pragma once
#include <boost/asio/ip/address.hpp>

#include <cstddef>
#include <string>
#include <vector>

/// 入口守卫:监听地址解析、可信代理判定与浏览器 Origin 校验(审计项 L9)。
///
/// 背景:WS 连接默认从 `X-Real-IP` 取客户端 IP 用于「单 IP 连接数」和「鉴权令牌桶」,
/// 一旦 9100 端口被绕过 nginx 直连,这个头就能被伪造,限流形同虚设。这里把「谁有资格
/// 写这个头」收敛成显式的可信代理列表(默认只有回环),并把 Origin 校验从「配了才管」
/// 改成「没配也按同源兜底」。
namespace net_guard {

/// 监听地址 `host:port` 的解析结果。
struct ListenAddr {
  boost::asio::ip::address address;
  unsigned short port = 0;
};

/// 解析 `host:port`(host 支持 IPv4、IPv6 字面量);非法输入抛 `std::invalid_argument`。
ListenAddr parse_listen(const std::string& raw);

/// 是否为回环地址(`127.0.0.0/8` 与 `::1`)。
bool is_loopback(const boost::asio::ip::address& address);

/// 可信代理网段表。只有直连对端命中这里的地址,才采信它带来的 `X-Real-IP`。
class ProxyTrust {
 public:
  /// 默认策略:只信任本机(容器 `network_mode: host` + nginx 反代即属此类)。
  static ProxyTrust loopback_only();

  /// 从配置项解析,支持单个 IP 与 CIDR(`10.0.0.0/8`、`fd00::/8`);
  /// 任何一项非法都抛 `std::invalid_argument`(宁可启动失败,也不静默放宽)。
  static ProxyTrust from_list(const std::vector<std::string>& entries);

  bool trusted(const boost::asio::ip::address& peer) const;

  /// 规则条数(启动日志与测试用)。
  std::size_t size() const { return rules_.size(); }

 private:
  struct Rule {
    boost::asio::ip::address base;
    int bits = 0;
  };

  std::vector<Rule> rules_;
};

/// 计算客户端 IP:对端可信且头里是合法单 IP 时采用该头,否则一律用对端地址。
///
/// 头里出现逗号(多级代理拼接)、空白或非 IP 文本时同样回退到对端地址,避免把
/// 伪造串塞进限流 key。
std::string client_ip(const boost::asio::ip::address& peer, const std::string& real_ip_header,
                      const ProxyTrust& trust);

/// 浏览器 WS 的 Origin 校验。
///
/// - 没有 `Origin`(原生 App、压测脚本)→ 放行;
/// - 配置了 `IM_ALLOWED_ORIGINS` → 必须在白名单内(忽略大小写与结尾 `/`);
/// - 未配置白名单 → 退化为同源校验:`Origin` 的 host[:port] 必须等于 `Host` 头。
///
/// 同源比较只比 authority(host + 非默认端口),不比较 scheme —— `Host` 头里没有
/// scheme,强行比较会把正常请求误杀。
bool origin_allowed(const std::string& origin, const std::string& host,
                    const std::vector<std::string>& allowed);

}  // namespace net_guard
