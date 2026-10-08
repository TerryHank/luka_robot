"""Build the offline CPU TTS engines used by the voice gateway."""

from pathlib import Path


def _required_file(directory: Path, name: str) -> str:
    path = directory / name
    if not path.is_file():
        raise FileNotFoundError(f"TTS file is missing: {path}")
    return str(path)


def _required_directory(directory: Path, name: str) -> str:
    path = directory / name
    if not path.is_dir():
        raise FileNotFoundError(f"TTS directory is missing: {path}")
    return str(path)


def _is_lfs_pointer(path: Path) -> bool:
    # Some release archives contain the tiny Git LFS manifest instead of the
    # weight binary. Never send that manifest to ONNX Runtime as a model.
    with path.open("rb") as stream:
        return stream.read(256).lstrip(b"\xef\xbb\xbf \t\r\n").startswith(
            b"version https://git-lfs.github.com/spec/v1"
        )


def _required_model_file(directory: Path, name: str) -> str:
    path = Path(_required_file(directory, name))
    if _is_lfs_pointer(path):
        raise ValueError(f"TTS weights have not been downloaded; Git LFS pointer: {path}")
    return str(path)


def _model_file(directory: Path) -> str:
    # The packaged Kokoro models use these names. Older VITS packages use
    # a model-specific filename; accept that only when it is unambiguous.
    for name in ("model.int8.onnx", "model.onnx"):
        path = directory / name
        if path.is_file() and not _is_lfs_pointer(path):
            return str(path)
    candidates = sorted(path for path in directory.glob("*.onnx") if path.is_file())
    models = [path for path in candidates if not _is_lfs_pointer(path)]
    if candidates and not models:
        raise ValueError(
            f"TTS weights have not been downloaded; only Git LFS pointers in {directory}"
        )
    if len(models) != 1:
        raise ValueError(f"Expected one TTS ONNX model in {directory}, found {len(models)}")
    return str(models[0])


def create_tts(engine: str, model_dir: str, threads: int = 4):
    """Return a sherpa-onnx TTS instance without opening an audio device.

    All engines remain on CPU. Model files are local; this function neither
    downloads weights nor falls back to a network speech service.

    The matcha-icefall-zh-baker package is an isolated audition candidate.
    Its upstream README restricts the training dataset to non-commercial use;
    this adapter does not grant permission to ship those weights in a product.
    """
    engine = str(engine).strip().lower()
    if engine not in ("vits", "kokoro", "matcha"):
        raise ValueError(f"Unsupported TTS engine: {engine!r}")
    directory = Path(model_dir)
    model = (_required_model_file(directory, "model-steps-3.onnx")
             if engine == "matcha" else _model_file(directory))
    tokens = _required_file(directory, "tokens.txt")
    dict_dir = _required_directory(directory, "dict")

    import sherpa_onnx

    if engine == "vits":
        backend = sherpa_onnx.OfflineTtsVitsModelConfig(
            model=model,
            lexicon=_required_file(directory, "lexicon.txt"),
            tokens=tokens,
            dict_dir=dict_dir,
        )
    elif engine == "kokoro":
        # Use the Chinese lexicon first and one English pronunciation set.
        # Loading both US and GB lexicons would duplicate English entries.
        lexicons = [_required_file(directory, "lexicon-zh.txt")]
        for name in ("lexicon-us-en.txt", "lexicon-gb-en.txt"):
            if (directory / name).is_file():
                lexicons.append(str(directory / name))
                break
        backend = sherpa_onnx.OfflineTtsKokoroModelConfig(
            model=model,
            voices=_required_file(directory, "voices.bin"),
            tokens=tokens,
            data_dir=_required_directory(directory, "espeak-ng-data"),
            dict_dir=dict_dir,
            lexicon=",".join(lexicons),
        )
    else:
        # Keep the acoustic model separate from the vocoder: both are ONNX
        # files, so selecting an arbitrary *.onnx here could swap their roles.
        backend = sherpa_onnx.OfflineTtsMatchaModelConfig(
            acoustic_model=model,
            vocoder=_required_model_file(directory, "vocos-22khz-univ.onnx"),
            lexicon=_required_file(directory, "lexicon.txt"),
            tokens=tokens,
            dict_dir=dict_dir,
            noise_scale=1.0,
            length_scale=1.0,
        )

    fsts = []
    # Kokoro/Matcha samples apply phone normalization before generic
    # numbers. Preserve the existing VITS ordering for its current package.
    rules = ("phone", "date", "number") if engine != "vits" else ("date", "number", "phone")
    for rule in rules:
        names = (f"{rule}-zh.fst", f"{rule}.fst") if engine == "kokoro" else (
            f"{rule}.fst", f"{rule}-zh.fst"
        )
        for name in names:
            if (directory / name).is_file():
                fsts.append(str(directory / name))
                break
    config = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            **{engine: backend}, num_threads=max(1, int(threads)), provider="cpu"
        ),
        rule_fsts=",".join(fsts),
        max_num_sentences=1,
    )
    if not config.validate():
        raise ValueError(f"Invalid {engine} TTS configuration in {directory}")
    return sherpa_onnx.OfflineTts(config)


def validate_speaker_id(tts, sid: int) -> int:
    """Reject invalid voice IDs before warming or playing any speech."""
    sid = int(sid)
    count = int(tts.num_speakers)
    if not 0 <= sid < count:
        raise ValueError(f"TTS speaker ID {sid} is outside 0..{count - 1}")
    return sid
