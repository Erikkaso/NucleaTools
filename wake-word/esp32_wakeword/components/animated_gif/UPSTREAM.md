# AnimatedGIF

Source: https://github.com/bitbank2/AnimatedGIF
Commit: c2478eca7aa2f3b7a09bdc583e5a4a43d03ac0d9
License: Apache-2.0 (LICENSE included).

AnimatedGIF.cpp, AnimatedGIF.h and gif.inl are unmodified upstream files.
CMakeLists.txt and gif_port.h supply the ESP-IDF clock/task adapter.
Playback uses playFrame(false); timing belongs to the display task.
