find_package(GTest REQUIRED)
include(GoogleTest)

add_executable(im_unit_tests config_test.cpp)
target_link_libraries(im_unit_tests PRIVATE imcore GTest::gtest_main)
gtest_discover_tests(im_unit_tests PROPERTIES LABELS unit)
