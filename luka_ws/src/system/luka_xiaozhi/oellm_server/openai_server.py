import argparse
import json
import os
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional, Tuple

import ctypes
from ctypes import (
    POINTER,
    CFUNCTYPE,
    byref,
    c_bool,
    c_char_p,
    c_double,
    c_float,
    c_int32,
    c_int64,
    c_uint8,
    c_void_p,
)

class CommonParamsSampling(ctypes.Structure):
    _fields_ = [
        ("top_k", c_int32),
        ("top_p", c_float),
        ("min_p", c_float),
        ("temp", c_float),
        ("typ_p", c_float),
        ("min_keep", c_int32),
        ("penalty_last_n", c_int32),
        ("penalty_repeat", c_float),
        ("penalty_freq", c_float),
        ("penalty_present", c_float),
    ]


class XlmCommonParams(ctypes.Structure):
    _fields_ = [
        ("model_path", c_char_p),
        ("omni_visual_model_path", c_char_p),
        ("omni_audio_model_path", c_char_p),
        ("omni_text_model_path", c_char_p),
        ("omni_online_mode", c_bool),
        ("embed_tokens", c_char_p),
        ("token_config_path", c_char_p),
        ("config_path", c_char_p),
        ("k_cache_int8", c_bool),
        ("model_type", c_int32),
        ("context_size", c_int32),
        ("sampling", CommonParamsSampling),
        ("prompt_file", c_char_p),
        ("path_prompt_cache", c_char_p),
    ]


class XlmPriority(ctypes.Structure):
    _fields_ = [("type", c_int32), ("priority", c_int32)]


class XlmPpl(ctypes.Structure):
    _fields_ = [
        ("load_ckpt", c_bool),
        ("text_data_num", c_int32),
        ("max_length", c_int32),
        ("stride", c_int32),
        ("testcase_name", c_char_p),
        ("hbm_path", c_char_p),
    ]


class XlmInputToken(ctypes.Structure):
    _fields_ = [("tokens", POINTER(c_int32)), ("tokens_size", c_int32)]


class XlmInputImage(ctypes.Structure):
    _fields_ = [
        ("image_path", c_char_p),
        ("image_data", POINTER(c_uint8)),
        ("image_width", c_int32),
        ("image_height", c_int32),
        ("image_preprocess", c_int32),
    ]


class XlmInputMultiModal(ctypes.Structure):
    _fields_ = [
        ("prompt", c_char_p),
        ("image_num", c_int32),
        ("images", POINTER(XlmInputImage)),
    ]


class XlmRequestData(ctypes.Union):
    _fields_ = [
        ("prompt", c_char_p),
        ("token", XlmInputToken),
        ("multi_modal_requset", XlmInputMultiModal),
    ]


class XlmLmRequest(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = [
        ("request_id", c_int32),
        ("type", c_int32),
        ("new_chat", c_bool),
        ("prompt_json", c_char_p),
        ("data", XlmRequestData),  # exact union layout from xlm.h
        ("system_prompt", c_char_p),
        ("chat_template", c_char_p),
        ("infer_backend", c_int32),
        ("priority", XlmPriority),
        ("ppl", POINTER(XlmPpl)),
    ]


class XlmInput(ctypes.Structure):
    _fields_ = [("request_num", c_int32), ("requests", POINTER(XlmLmRequest))]


class XlmModelPerformance(ctypes.Structure):
    _fields_ = [
        ("vit_cost", c_double),
        ("prefill_token_num", c_int64),
        ("prefill_tps", c_double),
        ("decode_token_num", c_int64),
        ("decode_tps", c_double),
        ("ttft", c_double),
        ("tpot", c_double),
    ]


class XlmResult(ctypes.Structure):
    _fields_ = [("text", c_char_p), ("request_id", c_int32), ("performance", XlmModelPerformance)]


XLM_STATE_START = 0
XLM_STATE_END = 1
XLM_STATE_RUNNING = 2
XLM_STATE_ERROR = 3

XLM_INPUT_PROMPT = 0
XLM_INPUT_MULTI_MODAL = 2

def _read_text(path: str) -> Optional[str]:
    if not path:
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _normalize_env_path(raw: Optional[str], *, as_file: bool = False) -> Optional[str]:
    if raw is None:
        return None
    value = raw.strip().strip('"').strip("'")
    # Common shell typo: append ":" at the end of a path.
    value = value.rstrip(":")
    if not value:
        return None
    value = os.path.abspath(value)
    if as_file and os.path.isdir(value):
        return os.path.join(value, "libxlm.so")
    return value


def _normalize_cli_path(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    value = raw.strip().strip('"').strip("'")
    if not value:
        return None
    return os.path.abspath(value)


def _messages_to_prompt(messages: List[Dict[str, Any]]) -> Tuple[Optional[str], str]:
    parts = []
    for message in messages:
        role = message.get("role", "")
        if role not in ("system", "user", "assistant"):
            raise ValueError("unsupported message role")
        content = message.get("content") or ""
        if isinstance(content, list):
            content = "\n".join(part.get("text", "") for part in content
                                if isinstance(part, dict) and part.get("type") == "text")
        parts.append(f"<|im_start|>{role}\n{content}<|im_end|>\n")
    return None, "".join(parts) + "<|im_start|>assistant\n"


@dataclass
class ServerConfig:
    host: str
    port: int
    model_id: str
    libxlm_path: str
    model_type: int
    hbm_path: Optional[str]
    tokenizer_dir: Optional[str]
    config_path: Optional[str]
    template_path: Optional[str]
    bpu_core: int


class XlmEngine:
    def __init__(self, cfg: ServerConfig):
        self.cfg = cfg
        self._lock = threading.Lock()

        self._lib = ctypes.CDLL(cfg.libxlm_path)

        self._lib.xlm_create_default_param.restype = XlmCommonParams
        self._lib.xlm_init.argtypes = [POINTER(XlmCommonParams), c_void_p, POINTER(c_void_p)]
        self._lib.xlm_init.restype = c_int32
        self._lib.xlm_infer.argtypes = [c_void_p, POINTER(XlmInput), c_void_p]
        self._lib.xlm_infer.restype = c_int32
        self._lib.xlm_destroy.argtypes = [POINTER(c_void_p)]
        self._lib.xlm_destroy.restype = c_int32

        self._chat_template_text = _read_text(cfg.template_path) if cfg.template_path else None
        self._chat_template_bytes = self._chat_template_text.encode("utf-8") if self._chat_template_text else None

        self._handle = c_void_p()

        self._cb = CFUNCTYPE(None, POINTER(XlmResult), c_int32, c_void_p)(self._callback)
        params = self._lib.xlm_create_default_param()
        params.model_path = cfg.hbm_path.encode("utf-8") if cfg.hbm_path else None
        params.token_config_path = cfg.tokenizer_dir.encode("utf-8") if cfg.tokenizer_dir else None
        params.config_path = cfg.config_path.encode("utf-8") if cfg.config_path else None
        params.model_type = int(cfg.model_type)
        params.context_size = 1024
        if cfg.model_type == 4:  # InternLM2 in demo
            params.k_cache_int8 = True

        # reasonable defaults (match demo)
        params.sampling.min_keep = 1
        params.sampling.min_p = 0.0
        params.sampling.temp = 0.3
        params.sampling.top_k = 50
        params.sampling.top_p = 1.0
        params.sampling.typ_p = 1.0
        params.sampling.penalty_last_n = 128
        params.sampling.penalty_freq = 0.1
        params.sampling.penalty_present = 0.1
        params.sampling.penalty_repeat = 1.2

        ret = self._lib.xlm_init(byref(params), ctypes.cast(self._cb, c_void_p), byref(self._handle))
        if ret != 0:
            raise RuntimeError(f"xlm_init failed with code {ret}")

        self._active_stream_writer = None
        self._active_stream_request_id = 0

    def close(self) -> None:
        if self._handle and self._handle.value:
            h = c_void_p(self._handle.value)
            self._lib.xlm_destroy(byref(h))
            self._handle = c_void_p()

    def _callback(self, result_ptr: POINTER(XlmResult), state: int, userdata: c_void_p) -> None:
        try:
            if not userdata:
                return
            pyobj_ptr = ctypes.cast(userdata, POINTER(ctypes.py_object))
            ctx = pyobj_ptr.contents.value

            text = ""
            if result_ptr and result_ptr.contents and result_ptr.contents.text:
                try:
                    text = ctypes.cast(result_ptr.contents.text, c_char_p).value.decode("utf-8", errors="ignore")
                except Exception:
                    text = ""

            if ctx.get("stream_writer") is not None and state in (XLM_STATE_START, XLM_STATE_RUNNING):
                if text:
                    ctx["stream_writer"](text)
            else:
                if text:
                    ctx["buf"].append(text)
            if state == XLM_STATE_ERROR:
                ctx["error"] = "xlm_state_error"
        except Exception:
            # never let exceptions escape into C callback
            return

    def infer_chat(
        self,
        messages: List[Dict[str, Any]],
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        top_k: Optional[int] = None,
        presence_penalty: Optional[float] = None,
        frequency_penalty: Optional[float] = None,
        stream_writer=None,
    ) -> str:
        system_prompt, prompt = _messages_to_prompt(messages)
        if not prompt:
            prompt = " "

        with self._lock:
            req = XlmLmRequest()
            req.request_id = 0
            req.type = XLM_INPUT_PROMPT
            req.new_chat = True
            req.prompt_json = None
            prompt_bytes = prompt.encode("utf-8")
            system_prompt_bytes = system_prompt.encode("utf-8") if system_prompt else None
            req.prompt = prompt_bytes
            req.system_prompt = system_prompt_bytes
            req.chat_template = self._chat_template_bytes if self._chat_template_bytes else None
            # backend mapping: -1 any, else bpu_core -> 2..5
            if self.cfg.bpu_core < 0:
                req.infer_backend = 1
            else:
                req.infer_backend = 2 + int(self.cfg.bpu_core)
            req.priority = XlmPriority(0, 0)
            req.ppl = None

            inp = XlmInput()
            inp.request_num = 1

            req_array = (XlmLmRequest * 1)()
            req_array[0] = req
            inp.requests = ctypes.cast(req_array, POINTER(XlmLmRequest))

            ctx = {"buf": [], "error": None, "stream_writer": stream_writer}
            userdata_holder = ctypes.py_object(ctx)
            userdata_ptr = ctypes.cast(ctypes.pointer(userdata_holder), c_void_p)
            ret = self._lib.xlm_infer(self._handle, byref(inp), userdata_ptr)
            if ret != 0:
                raise RuntimeError(f"xlm_infer failed with code {ret}")
            if ctx["error"]:
                raise RuntimeError(ctx["error"])
            return "".join(ctx["buf"])


def _json_response(handler: BaseHTTPRequestHandler, status: int, obj: Any) -> None:
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _read_json_body(handler: BaseHTTPRequestHandler) -> Any:
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length) if length > 0 else b"{}"
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def _sse_headers(handler: BaseHTTPRequestHandler) -> None:
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Connection", "keep-alive")
    handler.end_headers()


def _now_unix() -> int:
    return int(time.time())


class _SingleThreadHTTPServer(HTTPServer):
    daemon_threads = True


def make_handler(engine: XlmEngine, cfg: ServerConfig):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/health":
                _json_response(self, 200, {"status": "ok"})
                return
            if self.path == "/v1/models":
                _json_response(
                    self,
                    200,
                    {
                        "object": "list",
                        "data": [
                            {
                                "id": cfg.model_id,
                                "object": "model",
                                "created": _now_unix(),
                                "owned_by": "local",
                            }
                        ],
                    },
                )
                return
            _json_response(self, 404, {"error": {"message": "not found", "type": "not_found"}})

        def do_POST(self) -> None:
            if self.path != "/v1/chat/completions":
                _json_response(self, 404, {"error": {"message": "not found", "type": "not_found"}})
                return

            try:
                req = _read_json_body(self)
            except Exception as e:
                _json_response(self, 400, {"error": {"message": f"invalid json: {e}", "type": "invalid_request_error"}})
                return

            model = req.get("model") or cfg.model_id
            if model != cfg.model_id:
                _json_response(self, 400, {"error": {"message": "model is not available", "type": "invalid_request_error"}})
                return
            messages = req.get("messages") or []
            if not isinstance(messages, list):
                _json_response(self, 400, {"error": {"message": "messages must be list", "type": "invalid_request_error"}})
                return

            stream = bool(req.get("stream", False))
            temperature = req.get("temperature")
            top_p = req.get("top_p")
            top_k = req.get("top_k")
            presence_penalty = req.get("presence_penalty")
            frequency_penalty = req.get("frequency_penalty")

            completion_id = f"chatcmpl-{int(time.time()*1000)}"
            created = _now_unix()

            if stream:
                _sse_headers(self)

                def write_delta(delta_text: str) -> None:
                    chunk = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model,
                        "choices": [{"index": 0, "delta": {"content": delta_text}, "finish_reason": None}],
                    }
                    payload = ("data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n").encode("utf-8")
                    self.wfile.write(payload)
                    self.wfile.flush()

                try:
                    engine.infer_chat(
                        messages=messages,
                        temperature=temperature,
                        top_p=top_p,
                        top_k=top_k,
                        presence_penalty=presence_penalty,
                        frequency_penalty=frequency_penalty,
                        stream_writer=write_delta,
                    )
                    done = ("data: [DONE]\n\n").encode("utf-8")
                    self.wfile.write(done)
                    self.wfile.flush()
                except Exception as e:
                    err = {
                        "error": {
                            "message": str(e),
                            "type": "server_error",
                        }
                    }
                    payload = ("data: " + json.dumps(err, ensure_ascii=False) + "\n\n").encode("utf-8")
                    self.wfile.write(payload)
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                return

            try:
                text = engine.infer_chat(
                    messages=messages,
                    temperature=temperature,
                    top_p=top_p,
                    top_k=top_k,
                    presence_penalty=presence_penalty,
                    frequency_penalty=frequency_penalty,
                    stream_writer=None,
                )
            except Exception as e:
                _json_response(self, 500, {"error": {"message": str(e), "type": "server_error"}})
                return

            resp = {
                "id": completion_id,
                "object": "chat.completion",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": text},
                        "finish_reason": "stop",
                    }
                ],
            }
            _json_response(self, 200, resp)

        def log_message(self, format: str, *args: Any) -> None:
            # keep console clean; change if you need access logs
            return

    return Handler

def parse_args() -> ServerConfig:
    parser = argparse.ArgumentParser(description="OpenAI-compatible server for oellm/xlm")
    parser.add_argument("--host", default="0.0.0.0", help="Listen host")
    parser.add_argument("--port", type=int, default=8000, help="Listen port")
    parser.add_argument("--model-id", default="oellm-local", help="Model id returned by /v1/models")
    parser.add_argument(
        "--model-type",
        type=int,
        required=True,
        choices=[0, 1, 4, 7],
        help="Model type: 0(INTERNVL), 1(DEEPSEEK), 4(InternLM2), 7(QWEN2.5)",
    )
    parser.add_argument("--hbm-path", default="", help="Path to model .hbm")
    parser.add_argument("--tokenizer-dir", default="", help="Path to tokenizer directory")
    parser.add_argument("--config-path", default="", help="Path to config file (required for model_type 0)")
    parser.add_argument("--template-path", default="", help="Path to chat template file")
    parser.add_argument("--bpu-core", type=int, default=-1, choices=[-1, 0, 1, 2, 3], help="-1 or 0~3")
    args = parser.parse_args()

    libxlm_path = _normalize_env_path(os.environ.get("LIBXLM_PATH"), as_file=True) or \
        os.path.join(_normalize_env_path(os.environ.get("LD_LIBRARY_PATH"), as_file=True), "libxlm.so")
    hbm_path = _normalize_cli_path(args.hbm_path)
    tokenizer_dir = _normalize_cli_path(args.tokenizer_dir)
    config_path = _normalize_cli_path(args.config_path)
    template_path = _normalize_cli_path(args.template_path)

    return ServerConfig(
        host=args.host,
        port=args.port,
        model_id=args.model_id,
        libxlm_path=libxlm_path,
        model_type=args.model_type,
        hbm_path=hbm_path,
        tokenizer_dir=tokenizer_dir,
        config_path=config_path,
        template_path=template_path,
        bpu_core=args.bpu_core,
    )

def main() -> None:
    cfg = parse_args()

    if not os.path.exists(cfg.libxlm_path):
        raise SystemExit(f"LIBXLM_PATH not found: {cfg.libxlm_path}")
    if os.path.isdir(cfg.libxlm_path):
        raise SystemExit(f"LIBXLM_PATH must be a .so file, got directory: {cfg.libxlm_path}")

    if cfg.model_type in (1, 4, 7) and (not cfg.hbm_path or not cfg.tokenizer_dir):
        raise SystemExit("For model_type 1/4/7 you must set HBM_PATH and TOKENIZER_DIR")
    if cfg.model_type == 0 and (not cfg.config_path):
        raise SystemExit("For model_type 0 (INTERNVL) you must set CONFIG_PATH (and handle image separately)")

    engine = XlmEngine(cfg)
    handler_cls = make_handler(engine, cfg)
    httpd = _SingleThreadHTTPServer((cfg.host, cfg.port), handler_cls)

    print(f"OpenAI-compatible server listening on http://{cfg.host}:{cfg.port}")
    try:
        httpd.serve_forever()
    finally:
        engine.close()


if __name__ == "__main__":
    main()

