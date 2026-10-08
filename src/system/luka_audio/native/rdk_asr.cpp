#include "sense-voice.h"
#include <fstream>
#include <iostream>
#include <json/json.h>

int main(int argc, char** argv) {
  if (argc != 3) return 2;
  std::ifstream input(argv[2], std::ios::binary);
  std::vector<double> samples;
  int16_t value;
  while (input.read(reinterpret_cast<char*>(&value), 2)) samples.push_back(value);
  if (samples.empty() || samples.size() > 16000 * 15) return 3;
  auto cp = sense_voice_context_default_params();
  cp.use_gpu = false; cp.use_itn = true; cp.cb_eval = nullptr; cp.cb_eval_user_data = nullptr;
  auto* ctx = sense_voice_small_init_from_file_with_params(argv[1], cp);
  if (!ctx) return 4;
  ctx->language_id = sense_voice_lang_id("zh");
  auto params = sense_voice_full_default_params(SENSE_VOICE_SAMPLING_GREEDY);
  params.language = "zh"; params.n_threads = 4;
  params.print_progress = false; params.print_timestamps = false;
  if (sense_voice_full_parallel(ctx, params, samples, samples.size(), 1) != 0) return 5;
  std::string text;
  for (size_t i = 4; i < ctx->state->ids.size(); ++i) {
    const int id = ctx->state->ids[i];
    if (id && id != ctx->state->ids[i - 1]) text += ctx->vocab.id_to_token[id];
  }
  Json::Value result; result["ok"] = true; result["text"] = text;
  Json::StreamWriterBuilder writer; writer["indentation"] = "";
  std::cout << Json::writeString(writer, result) << std::endl;
  // One bounded request per process; OS reclaims the upstream context.
}
