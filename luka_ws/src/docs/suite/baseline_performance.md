# RDK S100 Person Pipeline Performance Baseline

Source: `docs/PERSON_PIPELINE_PERFORMANCE.md`.

- Worker loop ~7.98 FPS, capped at 8 FPS.
- 90 no-person samples: frame-age + HTTP latency median 0.144 s, max 0.357 s, zero >0.5 s.
- Median preprocessing 1.84 ms.
- Median BPU/runtime forward 20.93 ms.
- Median postprocess 2.48 ms.
- Median detector total 27.00 ms.
- Recorded optimized mask comparison: IoU 1.0 on fixtures.

Regression rules: no float64 mask regression; filter person before expensive mask reconstruction; no-person postprocess must not return to ~100 ms overhead; official runtime must pass parity before default; P10 requires fresh live measurement.
