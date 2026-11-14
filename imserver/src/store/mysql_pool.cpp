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
* 文件名称          src/store/mysql_pool.cpp
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
#include "store/mysql_pool.h"

#include <chrono>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>

#include "store/stmt.h"
#include "util/log.h"
#include "util/metrics.h"

namespace {

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     取系统时钟当前毫秒时间戳
// 参数说明     无
// 返回参数     int64_t          毫秒时间戳
// 使用示例     int64_t t = now_ms();
// 备注信息     用 system_clock 与库里 updated_at 同口径 不保证单调
//-------------------------------------------------------------------------------------------------------------------
int64_t now_ms() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(
             std::chrono::system_clock::now().time_since_epoch())
      .count();
}

/// 连接级错误:出现这些错误码说明 socket 已经不可用,必须换一条连接。
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     判断错误码是否连接级故障
// 参数说明     code             MySQL errno
// 返回参数     bool             需要换连接返回 true
// 使用示例     is_connection_error(mysql_errno(conn));
// 备注信息     2006 服务端断开 2013 查询中丢连接 2055 连接丢失 三种都必须丢弃连接
//-------------------------------------------------------------------------------------------------------------------
bool is_connection_error(int code) {
  return code == 2006 || code == 2013 || code == 2055;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     新建一条 MySQL 连接
// 参数说明     dsn              主机 端口 账号 口令 库名
// 返回参数     MYSQL*           已建立的连接句柄
// 使用示例     MYSQL* conn = connect_one(dsn);
// 备注信息     字符集固定 utf8mb4 失败抛 std::runtime_error 且已 mysql_close 不泄漏
//-------------------------------------------------------------------------------------------------------------------
MYSQL* connect_one(const MysqlDsn& dsn) {
  MYSQL* conn = mysql_init(nullptr);
  if (conn == nullptr) {
    throw std::runtime_error("mysql_init failed");
  }
  mysql_options(conn, MYSQL_SET_CHARSET_NAME, "utf8mb4");
  if (mysql_real_connect(conn, dsn.host.c_str(), dsn.user.c_str(), dsn.password.c_str(),
                         dsn.database.c_str(), dsn.port, nullptr, 0) == nullptr) {
    const std::string error = mysql_error(conn);
    mysql_close(conn);
    throw std::runtime_error("mysql connect failed: " + error);
  }
  return conn;
}

}  // namespace

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     构造连接池 启动时建满全部连接
// 参数说明     dsn                 MySQL 连接参数
//              size                连接数 小于等于 0 抛 std::invalid_argument
//              idle_ping_ms        空闲超过该毫秒数先 ping 0 表示每次 ping 负数关闭探测
//              connect_wait_ms     启动连不上 MySQL 的最长等待毫秒数 0 表示首次失败立即抛
// 返回参数     void             无返回值
// 使用示例     MysqlPool pool(dsn, 8, 5000, 30000);
// 备注信息     连接在 connect_wait_ms 窗口内重试 中途失败先关闭已建连接再抛 构造失败析构不执行
//-------------------------------------------------------------------------------------------------------------------
MysqlPool::MysqlPool(const MysqlDsn& dsn, int size, int64_t idle_ping_ms,
                     int64_t connect_wait_ms)
    : dsn_(dsn), idle_ping_ms_(idle_ping_ms), connect_wait_ms_(connect_wait_ms), size_(size) {
  if (size_ <= 0) {
    throw std::invalid_argument("mysql pool size must be positive");
  }
  idle_.reserve(static_cast<std::size_t>(size_));
  // 启动时 DB 还没就绪是常态(容器一起拉起、MySQL 正在崩溃恢复)。
  // 直接抛会让进程退出,而 Docker 的重启退避会一路涨到 60s —— DB 恢复后还要再等一个
  // 退避周期才起得来(2026-11-01 压测实测多等 47s)。这里在窗口内重试,窗口内恢复即启动。
  const int64_t wait_ms = connect_wait_ms_ > 0 ? connect_wait_ms_ : 0;
  const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(wait_ms);
  try {
    for (int i = 0; i < size_; ++i) {
      idle_.push_back(Slot{connect_until(deadline), now_ms()});
    }
  } catch (...) {
    // 构造失败时析构函数不会执行,已建好的连接要自己关掉。
    for (const Slot& slot : idle_) {
      if (slot.conn != nullptr) {
        clear_stmt_cache(slot.conn);
        mysql_close(slot.conn);
      }
    }
    idle_.clear();
    throw;
  }
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     析构连接池 关闭全部空闲连接
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     { MysqlPool pool(dsn, 4); }  // 离开作用域关闭连接
// 备注信息     置 closed_ 后取出空闲队列 逐条清 prepared statement 缓存再 mysql_close 不等待借出未还的连接
//-------------------------------------------------------------------------------------------------------------------
MysqlPool::~MysqlPool() {
  std::vector<Slot> to_close;
  {
    const std::lock_guard<std::mutex> lock(mutex_);
    closed_ = true;
    to_close.swap(idle_);
  }
  for (const Slot& slot : to_close) {
    if (slot.conn == nullptr) {
      continue;
    }
    clear_stmt_cache(slot.conn);
    mysql_close(slot.conn);
  }
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     借出一条连接 无空闲时阻塞等待
// 参数说明     无
// 返回参数     MysqlPool::Lease     独占连接租约
// 使用示例     auto lease = pool.acquire();
// 备注信息     池关闭抛 std::runtime_error 空槽位或 ping 失败走 connect_with_retry(3) 并累加 db_wait 指标
//-------------------------------------------------------------------------------------------------------------------
MysqlPool::Lease MysqlPool::acquire() {
  const auto wait_start = std::chrono::steady_clock::now();
  MYSQL* conn = nullptr;
  {
    std::unique_lock<std::mutex> lock(mutex_);
    cv_.wait(lock, [this] { return closed_ || !idle_.empty(); });
    if (closed_) {
      throw std::runtime_error("mysql pool closed");
    }
    Slot slot = idle_.back();
    idle_.pop_back();
    lock.unlock();

    conn = slot.conn;
    if (conn == nullptr) {
      // 上一次重连失败的槽位:这里再试。
      conn = connect_with_retry(3);
    } else if (idle_ping_ms_ >= 0 && now_ms() - slot.last_used_ms >= idle_ping_ms_) {
      // MySQL 的 wait_timeout(默认 8h)会掐掉空闲连接;池里的死连接必须先 ping 掉,
      // 否则第一条 SQL 必然报 "Lost connection",而且之后每次都失败。
      if (mysql_ping(conn) != 0) {
        log_error("mysql_reconnect", {{"reason", mysql_error(conn)}});
        discard(conn);
        conn = connect_with_retry(3);
      }
    }
  }
  // 池等待时间:并发打满时这个值会先涨,是「DB 侧瓶颈」的早期信号。
  const auto waited_us = std::chrono::duration_cast<std::chrono::microseconds>(
                             std::chrono::steady_clock::now() - wait_start)
                             .count();
  metrics::db_wait_count.fetch_add(1, std::memory_order_relaxed);
  metrics::db_wait_us.fetch_add(static_cast<uint64_t>(waited_us),
                                std::memory_order_relaxed);
  return Lease(*this, conn);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     在截止时间前反复重连
// 参数说明     deadline         steady_clock 截止时刻
// 返回参数     MYSQL*           新连接 超过截止时间抛 std::runtime_error
// 使用示例     connect_until(std::chrono::steady_clock::now() + std::chrono::seconds(30));
// 备注信息     每 2 秒重试一次 超时异常文本含尝试次数 用于启动等待 DB 就绪
//-------------------------------------------------------------------------------------------------------------------
MYSQL* MysqlPool::connect_until(std::chrono::steady_clock::time_point deadline) {
  int attempt = 0;
  for (;;) {
    try {
      return connect_one(dsn_);
    } catch (const std::exception& error) {
      ++attempt;
      if (std::chrono::steady_clock::now() >= deadline) {
        throw std::runtime_error(std::string("mysql connect failed after ") +
                                 std::to_string(attempt) + " attempts: " + error.what());
      }
      log_error("mysql_connect_retry",
                {{"attempt", std::to_string(attempt)}, {"error", error.what()}});
      std::this_thread::sleep_for(std::chrono::milliseconds(2000));
    }
  }
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     有限次重连 失败返回空指针
// 参数说明     attempts         最大尝试次数
// 返回参数     MYSQL*           新连接 全部失败返回 nullptr
// 使用示例     MYSQL* conn = pool.connect_with_retry(3);
// 备注信息     退避 50*(n+1) 毫秒 不抛异常 空连接交给调用方走 2006 分支 不把死连接塞回池
//-------------------------------------------------------------------------------------------------------------------
MYSQL* MysqlPool::connect_with_retry(int attempts) {
  for (int attempt = 0; attempt < attempts; ++attempt) {
    try {
      return connect_one(dsn_);
    } catch (const std::exception& error) {
      log_error("mysql_connect_failed",
                {{"attempt", std::to_string(attempt + 1)}, {"error", error.what()}});
      std::this_thread::sleep_for(std::chrono::milliseconds(50 * (attempt + 1)));
    }
  }
  // 返回空连接:调用方拿到空 lease 后,任何 SQL 都会立刻失败并走 50001 分支,
  // 既不会把死连接塞回池里,也不会让异常逃出 DB 线程池。
  return nullptr;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     销毁不可用连接
// 参数说明     conn             要关闭的连接 允许为空
// 返回参数     void             无返回值
// 使用示例     pool.discard(conn);
// 备注信息     空指针直接返回 否则先 clear_stmt_cache 再 mysql_close 不回队列
//-------------------------------------------------------------------------------------------------------------------
void MysqlPool::discard(MYSQL* conn) {
  if (conn == nullptr) {
    return;
  }
  clear_stmt_cache(conn);
  mysql_close(conn);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     把连接放回空闲队列
// 参数说明     conn             要归还的连接 允许为空
// 返回参数     void             无返回值
// 使用示例     pool.release(conn);
// 备注信息     池已关闭就地关闭 否则带 last_used_ms 入队并 notify_one 空连接也入队由下次 acquire 重连
//-------------------------------------------------------------------------------------------------------------------
void MysqlPool::release(MYSQL* conn) {
  {
    const std::lock_guard<std::mutex> lock(mutex_);
    if (closed_) {
      if (conn != nullptr) {
        clear_stmt_cache(conn);
        mysql_close(conn);
      }
      return;
    }
    idle_.push_back(Slot{conn, now_ms()});
  }
  cv_.notify_one();
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     构造连接租约 接管一条已借出的连接
// 参数说明     pool             所属连接池
//              conn             借出的连接 允许为空
// 返回参数     void             无返回值
// 使用示例     MysqlPool::Lease lease(pool, conn);
// 备注信息     只记录指针 不做任何 I/O 由 acquire 内部调用
//-------------------------------------------------------------------------------------------------------------------
MysqlPool::Lease::Lease(MysqlPool& pool, MYSQL* conn) : pool_(&pool), conn_(conn) {}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     析构租约 把连接归还连接池
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     { auto lease = pool.acquire(); }  // 离开作用域即归还
// 备注信息     调用 release() 归还 幂等 析构不抛异常
//-------------------------------------------------------------------------------------------------------------------
MysqlPool::Lease::~Lease() { release(); }

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     移动构造 转移连接所有权
// 参数说明     other            源租约 转移后置空
// 返回参数     void             无返回值
// 使用示例     MysqlPool::Lease moved(std::move(lease));
// 备注信息     源对象 pool_ 与 conn_ 置空 其析构不会二次归还
//-------------------------------------------------------------------------------------------------------------------
MysqlPool::Lease::Lease(Lease&& other) noexcept
    : pool_(other.pool_), conn_(other.conn_) {
  other.pool_ = nullptr;
  other.conn_ = nullptr;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     移动赋值 先归还自身再接管对方连接
// 参数说明     other            源租约 转移后置空
// 返回参数     MysqlPool::Lease&     返回 *this
// 使用示例     lease = pool.acquire();
// 备注信息     自赋值保护 先 release() 归还当前连接 保证不会漏还
//-------------------------------------------------------------------------------------------------------------------
MysqlPool::Lease& MysqlPool::Lease::operator=(Lease&& other) noexcept {
  if (this != &other) {
    release();
    pool_ = other.pool_;
    conn_ = other.conn_;
    other.pool_ = nullptr;
    other.conn_ = nullptr;
  }
  return *this;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     归还连接并清空自身指针
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     lease.release();  // 也可由析构自动调用
// 备注信息     pool_ 非空才归还 之后置空两指针 幂等
//-------------------------------------------------------------------------------------------------------------------
void MysqlPool::Lease::release() {
  if (pool_ != nullptr) {
    pool_->release(conn_);
  }
  pool_ = nullptr;
  conn_ = nullptr;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     执行非预编译 SQL 并返回结果集
// 参数说明     sql              完整 SQL 文本
// 返回参数     MYSQL_RES*       结果集 调用方负责 mysql_free_result
// 使用示例     MYSQL_RES* res = lease.query("SELECT 1");
// 备注信息     连接为空抛 MysqlError(2006) 连接级错误先丢弃连接再抛 错误码取自 mysql_errno
//-------------------------------------------------------------------------------------------------------------------
MYSQL_RES* MysqlPool::Lease::query(const std::string& sql) {
  if (conn_ == nullptr) {
    throw MysqlError(2006, "mysql lease has no live connection");
  }
  if (mysql_real_query(conn_, sql.data(), sql.size()) != 0) {
    const int code = mysql_errno(conn_);
    const std::string message = mysql_error(conn_);
    if (is_connection_error(code)) {
      // 连接已死:立刻销毁,让下一次 acquire 建新连接(而不是把死连接放回池里)。
      pool_->discard(conn_);
      conn_ = nullptr;
    }
    throw MysqlError(code, "mysql query failed: " + message);
  }
  return mysql_store_result(conn_);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     转义字符串 供拼 SQL 字面量
// 参数说明     input            原始字符串
// 返回参数     std::string      已转义文本
// 使用示例     std::string lit = "'" + lease.escape(ct) + "'";
// 备注信息     连接为空抛 MysqlError(2006) 输出按需扩容到 2 倍加 1 再截断
//-------------------------------------------------------------------------------------------------------------------
std::string MysqlPool::Lease::escape(const std::string& input) const {
  if (conn_ == nullptr) {
    throw MysqlError(2006, "mysql lease has no live connection");
  }
  std::string output(input.size() * 2 + 1, '\0');
  const auto length = mysql_real_escape_string(
      conn_, output.data(), input.data(), static_cast<unsigned long>(input.size()));
  output.resize(length);
  return output;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     开启事务
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     lease.begin();
// 备注信息     失败抛 MysqlError 必须与 commit/rollback 配对
//-------------------------------------------------------------------------------------------------------------------
void MysqlPool::Lease::begin() { query("START TRANSACTION"); }
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     提交当前事务
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     lease.commit();
// 备注信息     无活动事务时 MySQL 静默成功 失败抛 MysqlError
//-------------------------------------------------------------------------------------------------------------------
void MysqlPool::Lease::commit() { query("COMMIT"); }
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     回滚当前事务
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     lease.rollback();
// 备注信息     异常路径也要调用 失败同样抛 MysqlError
//-------------------------------------------------------------------------------------------------------------------
void MysqlPool::Lease::rollback() { query("ROLLBACK"); }
