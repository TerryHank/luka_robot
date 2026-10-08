# P2 YOLO26 Runtime Adapter

The accepted Luka runtime remains the default until a physical S100 parity run
proves the pinned D-Robotics Model Zoo runtime is functionally and
performance-equivalent.

## Backend switch

```bash
# accepted default
export NX_YOLO26_RUNTIME_BACKEND=legacy

# board-only evaluation
export RDK_MODEL_ZOO_S_ROOT=/path/to/pinned/rdk_model_zoo_s
export NX_YOLO26_RUNTIME_BACKEND=drobotics
export NX_YOLO26_RUNTIME_ALLOW_FALLBACK=0
```

The D-Robotics adapter loads the official `YOLO26Seg` class from the pinned
checkout. It does not copy vendor code into Luka.

## Promotion gate

Do not change the service default to `drobotics` until same-frame tests record:
- person count parity;
- bbox IoU;
- score delta;
- mask IoU;
- Seg Depth / XYZ parity in the downstream depth test;
- preprocess / forward / postprocess timing;
- no regression to expensive all-class mask processing.

The current legacy runtime contains a person-first postprocess optimization not
present in the pinned upstream sample, so performance parity is a real gate, not
a documentation formality.
