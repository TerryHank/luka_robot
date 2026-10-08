#include "AIUI.h"
#include "aiui_error_policy.h"
#include <chrono>
#include <condition_variable>
#include <cstring>
#include <fstream>
#include <iostream>
#include <json/json.h>
#include <map>
#include <mutex>
#include <thread>
using namespace aiui;

class Listener : public AIUIListener {
 public:
  mutable std::mutex mutex;
  mutable std::condition_variable changed;
  mutable bool done = false, failed = false;
  mutable int error_code = 0;
  mutable int ignored_nlp_errors = 0;
  mutable std::string error_scope;
  mutable bool connected = false;
  mutable std::map<int, std::string> parts;
  mutable std::string audio;
  std::string operation;
  explicit Listener(std::string op) : operation(std::move(op)) {}
  void onEvent(const IAIUIEvent& event) const override {
    std::lock_guard<std::mutex> lock(mutex);
    if (done) return;
    if (event.getEventType() == AIUIConstant::EVENT_CONNECTED_TO_SERVER) {
      connected = true; changed.notify_all(); return;
    }
    if (event.getEventType() == AIUIConstant::EVENT_ERROR) {
      const std::string detail = event.getInfo() ? event.getInfo() : "";
      if (ignore_aiui_error(operation, detail)) {
        ++ignored_nlp_errors;
        return;
      }
      error_code = event.getArg1();
      error_scope = is_aiui_nlp_error(detail) ? "nlp" : "other";
      failed = done = true; changed.notify_all(); return;
    }
    if (event.getEventType() != AIUIConstant::EVENT_RESULT || !event.getData()) return;
    Json::Value meta; Json::Reader reader;
    if (!reader.parse(event.getInfo(), meta)) return;
    for (const auto& item : meta["data"]) {
      const auto sub = item["params"]["sub"].asString();
      for (const auto& content : item["content"]) {
        int length = 0;
        const char* data = event.getData()->getBinary(content["cnt_id"].asCString(), &length);
        if (!data || length <= 0) continue;
        if (operation == "asr" && sub == "iat") {
          Json::Value result;
          if (!reader.parse(std::string(data, length), result)) continue;
          const auto& text = result["text"];
          std::string words;
          for (const auto& word : text["ws"]) words += word["cw"][0]["w"].asString();
          if (text["pgs"].asString() == "rpl") {
            for (int i = text["rg"][0].asInt(); i <= text["rg"][1].asInt(); ++i) parts.erase(i);
          }
          parts[text["sn"].asInt()] = words;
          done = text["ls"].asBool();
        } else if (operation == "chat" && sub == "nlp") {
          Json::Value result;
          if (!reader.parse(std::string(data, length), result)) continue;
          if (result.isMember("intent")) {
            const auto& intent = result["intent"];
            const std::string answer = intent["answer"]["text"].asString();
            if (intent["rc"].asInt() == 0 && !answer.empty()) parts[0] = answer;
            else failed = true;
            done = true;
          } else if (result.isMember("nlp")) {
            const auto& nlp = result["nlp"];
            const std::string text = nlp["text"].asString();
            Json::Value nested;
            if (reader.parse(text, nested) && nested.isMember("intent")) {
              parts[0] = nested["intent"]["answer"]["text"].asString();
              failed = parts[0].empty(); done = true;
            } else {
              parts[nlp["seq"].asInt()] = text;
              done = nlp["status"].asInt() == 2;
            }
          }
        } else if (operation == "tts" && sub == "tts") {
          if (content["url"].asString() == "1") { failed = done = true; }
          else {
            audio.append(data, length);
            const int dts = content["dts"].asInt();
            done = dts == AIUIConstant::DTS_BLOCK_LAST || dts == AIUIConstant::DTS_ONE_BLOCK;
          }
        }
      }
    }
    if (done) changed.notify_all();
  }
};

void send(IAIUIAgent* agent, int type, int arg, const std::string& params, const std::string& data = "") {
  Buffer* buffer = nullptr;
  if (!data.empty()) { buffer = Buffer::alloc(data.size()); std::memcpy(buffer->data(), data.data(), data.size()); }
  auto* message = IAIUIMessage::create(type, arg, 0, params.c_str(), buffer);
  agent->sendMessage(message); message->destroy();
}

int main(int argc, char** argv) {
  if (argc != 5) return 2;
  const std::string op = argv[1];
  if (op != "asr" && op != "tts" && op != "chat") return 2;
  std::ifstream config_file(argv[2]); Json::Value config; Json::Reader reader;
  if (!reader.parse(config_file, config)) return 3;
  for (const auto key : {"appid", "key"}) {
    const auto value = config["login"][key].asString();
    if (value.empty() || value.find("YOUR_") != std::string::npos) return 3;
  }
  config["speech"]["data_source"] = "user";
  config["speech"]["wakeup_mode"] = "off";
  config["speech"]["interact_mode"] = "oneshot";
  config["iat"]["sample_rate"] = "16000";
  config["tts"]["sample_rate"] = "16000";
  config["tts"]["format"] = "raw";
  config["log"]["debug_log"] = "0"; config["log"]["save_datalog"] = "0";
  config.removeMember("ivw");
  AIUISetting::setAIUIDir("./AIUI/");
  Listener listener(op);
  Json::StreamWriterBuilder writer; writer["indentation"] = "";
  std::string sn = config.get("device_sn", "").asString();
  if (sn.empty()) {
    std::ifstream identity("/etc/machine-id"); identity >> sn;
  }
  if (sn.empty()) return 3;
  AIUISetting::setSystemInfo("sn", sn.c_str());
  auto* agent = IAIUIAgent::createAgent(Json::writeString(writer, config).c_str(), &listener, sn.c_str());
  std::ifstream input(argv[3], std::ios::binary);
  std::string payload((std::istreambuf_iterator<char>(input)), {});
  if (payload.empty()) { agent->destroy(); return 4; }
  send(agent, AIUIConstant::CMD_START, 0, "");
  send(agent, AIUIConstant::CMD_WAKEUP, 0, "clear_data=true");
  if (op == "chat" || op == "tts") {
    // Text requests have no real-time audio feeding delay. Wait for the SDK's
    // network event before sending text, rather than assuming createAgent is ready.
    std::unique_lock<std::mutex> lock(listener.mutex);
    listener.changed.wait_for(lock, std::chrono::seconds(3), [&] { return listener.connected || listener.failed; });
  }
  if (op == "asr") {
    if (payload.size() > 16000 * 2 * 15) { agent->destroy(); return 4; }
    for (size_t offset = 0; offset < payload.size(); offset += 1280) {
      send(agent, AIUIConstant::CMD_WRITE, 0, "data_type=audio", payload.substr(offset, 1280));
      std::this_thread::sleep_for(std::chrono::milliseconds(40));
    }
    send(agent, AIUIConstant::CMD_STOP_WRITE, 0, "data_type=audio");
  } else if (op == "chat") send(agent, AIUIConstant::CMD_WRITE, 0, "data_type=text,need_wakeup=false", payload);
  else send(agent, AIUIConstant::CMD_TTS, AIUIConstant::START,
              "vcn=x4_lingxiaoying_em_v2,engine_type=cloud,sample_rate=16000,aue=raw", payload);
  bool ok;
  Json::Value result;
  {
    std::unique_lock<std::mutex> lock(listener.mutex);
    listener.changed.wait_for(lock, std::chrono::seconds(12), [&] { return listener.done; });
    ok = listener.done && !listener.failed;
    result["ok"] = ok;
    result["error_code"] = listener.error_code;
    result["error_scope"] = listener.error_scope;
    result["connected"] = listener.connected;
    result["timed_out"] = !listener.done;
    result["ignored_nlp_errors"] = listener.ignored_nlp_errors;
    std::string text; for (const auto& part : listener.parts) text += part.second;
    result["text"] = text;
    if (op == "tts" && ok) {
      std::ofstream output(argv[4], std::ios::binary); output.write(listener.audio.data(), listener.audio.size());
      ok = output.good() && !listener.audio.empty();
      result["rate"] = 16000; result["channels"] = 1;
    }
  }
  agent->destroy();
  result["ok"] = ok;
  std::cout << Json::writeString(writer, result) << std::endl;
  if (!ok) return 5;
}
