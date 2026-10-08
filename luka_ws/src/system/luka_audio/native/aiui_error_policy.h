#pragma once
#include <algorithm>
#include <cctype>
#include <string>

inline bool is_aiui_nlp_error(std::string detail) {
  std::transform(detail.begin(), detail.end(), detail.begin(),
                 [](unsigned char c) { return std::tolower(c); });
  return detail.find("nlp") != std::string::npos;
}

inline bool ignore_aiui_error(const std::string& operation, const std::string& detail) {
  // Vendor SDK's ARM build disables NLP replies by default. An NLP error is
  // unrelated to an ASR or TTS request; other errors must still cause fallback.
  return (operation == "asr" || operation == "tts") && is_aiui_nlp_error(detail);
}
