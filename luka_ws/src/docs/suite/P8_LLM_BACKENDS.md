# P8 LLM Runtime adapters

## Boundary

`nav_llm_agent` remains the product/action owner. The new `LLMBackend`
contract only returns text:

```python
class LLMBackend:
    def generate(self, messages, tools=None):
        ...
```

The backend package contains no `cmd_vel`, Nav2 action client or DDSM control.
Malformed output, timeout or backend crash therefore cannot directly move the
robot.

## Backends

- `ollama` — existing HTTP/OpenAI-compatible path and current default.
- `hobot_xlm` — D-Robotics S100 topic adapter.
- `hobot_llamacpp` — D-Robotics llama.cpp topic adapter.

Example target configuration after board validation:

```text
llm_backend:=hobot_xlm
llm_fallbacks:=hobot_llamacpp,ollama
```

The default remains `ollama` until board-side parity and model resource
measurements are available.

## D-Robotics topic isolation

Official runtimes use dedicated Luka topics:

```text
/luka/llm/xlm/prompt        -> hobot_xlm
/luka/llm/xlm/final         <- ai_msgs/PerceptionTargets
/luka/llm/llamacpp/prompt   -> hobot_llamacpp
/luka/llm/llamacpp/final    <- ai_msgs/PerceptionTargets
```

Their intermediate string output is routed to `/luka/llm/*/stream`, not
`/tts_text`, so a model cannot bypass Luka's response/speech policy.

## Safety/product compatibility

The existing capability registry, grounded tool routing, hotel workflows,
floor transfer, navigation cancellation and product memory remain outside the
backend. The Suite adapters are providers only.

A backend failure is caught by the ordered fallback chain. If every provider
fails, the result is an LLM error; no motion action is synthesized.
