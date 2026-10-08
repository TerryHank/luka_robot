#include "tts_api.h"
#include <cmath>
#include <fstream>
#include <iostream>
#include <json/json.h>
#include <vector>

int main(int argc, char** argv) {
  if (argc != 4) return 2;
  std::ifstream input(argv[2]);
  std::string text((std::istreambuf_iterator<char>(input)), {});
  if (text.empty() || text.size() > 600) return 3;
  int error = 0;
  void* tts = wetts_init(argv[1], "tts.flags", &error);
  if (!tts || error != ERRCODE_TTS_SUCC) return 4;
  auto info = wetts_audio_info(tts);
  if (info.max_len <= 0 || info.max_len > 128 * 1024 * 1024) return 5;
  std::vector<char> data(info.max_len);
  int count = 0;
  error = wetts_synthesis(tts, text.c_str(), 1, data.data(), &count);
  if (error != ERRCODE_TTS_SUCC || count <= 0 || count > info.max_len / 4) return 6;
  std::ofstream output(argv[3], std::ios::binary);
  const auto* floats = reinterpret_cast<const float*>(data.data());
  for (int i = 0; i < count; ++i) {
    if (!std::isfinite(floats[i])) return 7;
    // WeTTS returns float values in signed 16-bit PCM units (as used by the
    // upstream Hobot playback code), not normalized -1..1 waveform samples.
    const float sample = std::max(-32767.0f, std::min(32767.0f, floats[i]));
    int16_t pcm = static_cast<int16_t>(sample);
    output.write(reinterpret_cast<char*>(&pcm), 2);
  }
  wetts_free(tts);
  Json::Value result; result["ok"] = true; result["rate"] = info.sample_rate;
  result["channels"] = info.num_channels; result["samples"] = count;
  Json::StreamWriterBuilder writer; writer["indentation"] = "";
  std::cout << Json::writeString(writer, result) << std::endl;
}
