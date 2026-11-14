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
* 文件名称          src/util/log.cpp
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
#include "util/log.h"

#include <chrono>
#include <iostream>
#include <mutex>

#include <nlohmann/json.hpp>

namespace {

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     取日志输出用的进程内互斥量
// 参数说明     无
// 返回参数     std::mutex&      全局唯一的日志锁
// 使用示例     std::lock_guard<std::mutex> lock(log_mutex());
// 备注信息     函数内 static 局部量 首次调用时构造 用于串行化 stdout 写入
//-------------------------------------------------------------------------------------------------------------------
std::mutex& log_mutex() {
  static std::mutex mutex;
  return mutex;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     取当前 Unix 毫秒时间戳
// 参数说明     无
// 返回参数     int64_t          毫秒级时间戳
// 使用示例     int64_t ts = now_ms();
// 备注信息     走 system_clock 墙钟 受系统时间调整影响 仅用作日志 ts 字段
//-------------------------------------------------------------------------------------------------------------------
int64_t now_ms() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(
             std::chrono::system_clock::now().time_since_epoch())
      .count();
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     拼一行 JSON 日志并写到 stdout
// 参数说明     level            级别字符串 info warn error
//              event            事件名
//              fields           附加键值对 同名键后者覆盖前者
// 返回参数     void             无返回值
// 使用示例     emit("info", "ws_connected", {{"uid", "12"}});
// 备注信息     先组好 json 再持锁写 stdout 单行输出 不做级别过滤
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     输出 info 级别结构化日志
// 参数说明     event            事件名
//              fields           附加键值对 默认空
// 返回参数     void             无返回值
// 使用示例     log_info("ws_connected", {{"uid", "12"}});
// 备注信息     等价于 emit("info", event, fields) 输出到 stdout
//-------------------------------------------------------------------------------------------------------------------
void log_info(std::string_view event,
              std::initializer_list<std::pair<std::string, std::string>> fields) {
  emit("info", event, fields);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     输出 warn 级别结构化日志
// 参数说明     event            事件名
//              fields           附加键值对 默认空
// 返回参数     void             无返回值
// 使用示例     log_warn("send_quota_exceeded", {{"uid", "12"}});
// 备注信息     等价于 emit("warn", event, fields) 输出到 stdout
//-------------------------------------------------------------------------------------------------------------------
void log_warn(std::string_view event,
              std::initializer_list<std::pair<std::string, std::string>> fields) {
  emit("warn", event, fields);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     输出 error 级别结构化日志
// 参数说明     event            事件名
//              fields           附加键值对 默认空
// 返回参数     void             无返回值
// 使用示例     log_error("mysql_connect_failed", {{"err", "2003"}});
// 备注信息     等价于 emit("error", event, fields) 输出到 stdout
//-------------------------------------------------------------------------------------------------------------------
void log_error(std::string_view event,
               std::initializer_list<std::pair<std::string, std::string>> fields) {
  emit("error", event, fields);
}
