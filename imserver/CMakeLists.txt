cmake_minimum_required(VERSION 3.22)
project(imserver LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(Boost 1.83 REQUIRED COMPONENTS system)
find_package(OpenSSL REQUIRED)
find_package(nlohmann_json REQUIRED)
find_package(Threads REQUIRED)
find_package(PkgConfig REQUIRED)
pkg_check_modules(MYSQLCLIENT REQUIRED mysqlclient)
pkg_check_modules(HIREDIS REQUIRED hiredis)

add_library(imcore STATIC
  src/auth/token.cpp
  src/config.cpp
  src/migrate.cpp
  src/net/ws_server.cpp
  src/service/message_service.cpp
  src/service/session_registry.cpp
  src/store/blacklist_repo.cpp
  src/store/conversation_repo.cpp
  src/store/message_repo.cpp
  src/store/mysql_pool.cpp
  src/store/redis_client.cpp
  src/store/stmt.cpp
  src/store/user_repo.cpp
  src/util/log.cpp
  src/util/ratelimit.cpp
)
target_include_directories(imcore PUBLIC src ${MYSQLCLIENT_INCLUDE_DIRS} ${HIREDIS_INCLUDE_DIRS})
target_link_libraries(imcore PUBLIC
  Boost::system
  OpenSSL::Crypto
  nlohmann_json::nlohmann_json
  Threads::Threads
  ${MYSQLCLIENT_LIBRARIES}
  ${HIREDIS_LIBRARIES}
)
target_compile_options(imcore PRIVATE -Wall -Wextra -Wpedantic)

add_executable(imserver src/main.cpp)
target_link_libraries(imserver PRIVATE imcore)

enable_testing()
add_subdirectory(tests)
