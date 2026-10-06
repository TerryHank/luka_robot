# P9 Object / Open-Vocabulary / Spatial Memory Capability Gate

P9 deliberately does **not** replace richer product perception with a
person-only official model.

## Preserved product modules

- `perception/yoloe26_live`
- `perception/locateanything_trial_20260907`
- `perception/spatial_memory`
- `perception/object_api/s100_object_api.py`

These remain rollback/product assets even when their original hardware backend
is not the RDK S100.

## What is officialized now

The S100 person Object API already imports `yolo26_person.Yolo26PersonSegmenter`.
P2 moved that facade behind the runtime factory, so this API can evaluate the
pinned D-Robotics YOLO26 runtime **without changing the HTTP API**.

The runtime is still legacy-by-default until P2 physical parity passes.

## What is not equivalent

A person-only YOLO26 segmentation runtime does not provide:

- arbitrary text/open-vocabulary queries;
- dynamic multi-class search;
- recorded patrol-video search;
- existing spatial-memory semantics/history.

It must therefore never be advertised as a replacement for the above product
features.

## Promotion gate

A new official provider may replace an existing capability only when all of the
following are demonstrated:

1. RDK S100 support;
2. existing API compatibility or a transparent adapter;
3. every capability required by that product path;
4. onsite accuracy not worse than the current implementation;
5. real-time performance acceptable on the S100.

For open-vocabulary replacement this explicitly includes text queries and
dynamic classes. For recorded search it additionally includes recorded-video
search.

Until those conditions are measured, the existing implementation stays
available and the official component may only be added beside it.
