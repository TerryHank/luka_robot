# RDK S100 Suite Baseline Inventory

Baseline source: repository evidence captured before Suite refactoring.
Branch: `feat/rdks100-suite-adaptation`.

> This file freezes known-good repository evidence. It does not claim a new live device capture was performed from GitHub. Run `bash system/scripts/capture_live_baseline.sh` on the RDK S100 before real-motion acceptance.

## Platform
- Target: RDK S100, Ubuntu ARM64, ROS 2 Humble/TROS Humble.
- Documented ROS setup: `ROS_DOMAIN_ID=87`, `ROS_LOCALHOST_ONLY=1`, CycloneDDS.
- Orbbec/Astra Pro Plus RGB-D via Orbbec SDK.
- RGB `/camera/color/image_raw`, depth `/camera/depth/image_raw`, both documented at 640x480 ~30 Hz.
- Registered optical frame: `camera_color_optical_frame`.

## Perception
- Source model: `/home/sunrise/yolo26m-objv1-seg.pt`.
- HBM: `perception/person_follow/models/bpu_yolo26/yolo26m_objv1_seg_bpu_nashe_640x640_nv12.hbm`.
- S100 BPU inference, person-only public output.
- CPU segmentation/depth postprocess retained.
- Depth method: `seg_valid_trimmed_mean`, trim ratio 0.15.
- Worker cap: 8 Hz via `CYCLE_S=.125`.

## Tracking / following
- Existing selected-person path uses Luka bounded IoU/depth tracking plus explicit selection.
- `hobot_mot` is present but not authoritative for this path.
- Appearance ReID and CPU face recognition are disabled in the documented inventory.
- Official `tros_person_following` is already used.
- Preview is dry-run. `track_id` is not permanent identity.

## Navigation / base
- Nav2 retained.
- Luka safety path includes `/nx/nav_guarded -> /nx/nav_safe`.
- `ddsm_car_control` remains authoritative for DDSM hardware.
- Hotel map, semantic map, product and memory data remain Luka-owned.

## Voice / Agent
- KWS: sherpa-onnx.
- ASR: existing SenseVoice integration.
- TTS: existing sherpa-onnx VITS/Matcha adapter.
- Agent: `nav_llm_agent` with local/OpenAI-compatible/Ollama-style backend.

## Repository evidence
- `docs/current_system_inventory.md`
- `docs/OFFICIAL_PERSON_FOLLOW_SEG_DEPTH.md`
- `docs/PERSON_PIPELINE_PERFORMANCE.md`
- `docs/MIGRATION_AND_STARTUP.md`

## Acceptance
- [x] Repository baseline frozen.
- [x] Known topics/services/actions/TF/performance recorded.
- [x] Live read-only capture script added.
- [ ] Fresh physical S100 capture pending.
- [x] No motion code introduced.
