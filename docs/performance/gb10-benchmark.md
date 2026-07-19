# GB10 Performance Benchmark

Measured 2026-07-19 on the target hardware (torch 2.9.1+cu130, device: NVIDIA GB10).

## Torch compute (OI-1: capability 12.1 forward-compat sanity)
- 4096² matmul: CPU 0.1984s · GPU 0.0078s (speedup ×25.4) — GPU kernels run correctly via PTX forward compatibility; no per-op failures observed.

## TS 1D-CNN encoder
- fit (2000×2×128, 5 epochs, cuda): 1.02s
- embed throughput: 316789 units/s

## DINOv2-small embedding
- 256 images in 0.163s → 1566.2 images/s (cuda)

## Prediction service (in-process, full pipeline incl. root cause + retrieval)
- P50 42.6ms · P95 56.4ms · P99 56.7ms · ~23.5 predictions/s single-threaded

## ONNX runtime (OI-2)
- {'installed': False, 'note': 'onnxruntime is not in the pinned environment — ONNX export remains optional (OI-2); torch-native serving is the working path'}

## Verdict
- OI-1: GPU path is functional and fast on GB10 despite the capability warning; the NGC-container fallback (ADR-0002) was not needed.
- OI-2: ONNX export stays optional/unexecuted; torch-native serving meets the local latency budget by a wide margin.
