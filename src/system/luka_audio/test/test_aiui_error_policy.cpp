#include "../native/aiui_error_policy.h"
#include <iostream>

int main() {
  if (!ignore_aiui_error("asr", "sub=nlp")) return 1;
  if (!ignore_aiui_error("tts", "sub=NLP")) return 2;
  if (!ignore_aiui_error("asr", "{\"sub\":\"nlp\"}")) return 3;
  if (ignore_aiui_error("chat", "sub=nlp")) return 4;
  if (ignore_aiui_error("asr", "sub=iat,error=20001")) return 5;
  if (ignore_aiui_error("tts", "sub=tts,error=20001")) return 6;
  if (ignore_aiui_error("asr", "")) return 7;
  std::cout << "PASS: unsupported NLP does not fail speech; actual speech errors remain fatal\n";
}
