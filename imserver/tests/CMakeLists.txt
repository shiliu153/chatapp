find_package(GTest REQUIRED)
include(GoogleTest)

add_executable(im_unit_tests config_test.cpp token_test.cpp ratelimit_test.cpp hmac_test.cpp
                             media_sign_test.cpp like_test.cpp guard_test.cpp metrics_test.cpp
                             frames_fixture_test.cpp)
target_link_libraries(im_unit_tests PRIVATE imcore GTest::gtest_main)
# 跨栈协议 fixture 的绝对路径(backlog E-2):unit 测试直接读仓库里的共享样例。
# 用 CMAKE_CURRENT_SOURCE_DIR 而不是相对路径,是因为 ctest 的工作目录是 build/。
target_compile_definitions(im_unit_tests PRIVATE
                           IM_FIXTURE_DIR="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/ws")
gtest_discover_tests(im_unit_tests PROPERTIES LABELS unit)

add_executable(im_db_tests store_test.cpp message_service_test.cpp)
target_link_libraries(im_db_tests PRIVATE imcore GTest::gtest_main)
gtest_discover_tests(im_db_tests PROPERTIES LABELS db)
