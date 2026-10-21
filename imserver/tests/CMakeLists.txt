find_package(GTest REQUIRED)
include(GoogleTest)

add_executable(im_unit_tests config_test.cpp token_test.cpp)
target_link_libraries(im_unit_tests PRIVATE imcore GTest::gtest_main)
gtest_discover_tests(im_unit_tests PROPERTIES LABELS unit)

add_executable(im_db_tests store_test.cpp)
target_link_libraries(im_db_tests PRIVATE imcore GTest::gtest_main)
gtest_discover_tests(im_db_tests PROPERTIES LABELS db)
