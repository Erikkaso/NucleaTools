idf_component_register(SRCS "AnimatedGIF.cpp" INCLUDE_DIRS "." REQUIRES esp_timer freertos)
target_compile_options(${COMPONENT_LIB} PRIVATE
    "-include${CMAKE_CURRENT_LIST_DIR}/gif_port.h"
    -Wno-unused-function -Wno-unused-variable)
