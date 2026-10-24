#pragma once
#include "audio_speaker.h"

enum class RecordingCue { kOn, kOff };

// Called only by the upload worker, which also owns TTS playback.
esp_err_t PlayRecordingCue(AudioSpeaker& speaker, RecordingCue cue);
