# Reflection — Lab 20 (Personal Report)

> **Đây là báo cáo cá nhân.** Mỗi học viên chạy lab trên laptop của mình, với spec của mình. Số liệu của bạn không so sánh được với bạn cùng lớp — chỉ so sánh **before vs after trên chính máy bạn**. Grade rubric tính theo độ rõ ràng của setup + tuning của bạn, không phải tốc độ tuyệt đối.

---

**Họ Tên:** Trần Thương Trường Sơn
**Cohort:** A20-K1
**Ngày submit:** 2026-05-06

---

## 1. Hardware spec (từ `00-setup/detect-hardware.py`)

> Paste output của `python 00-setup/detect-hardware.py` vào đây, hoặc điền thủ công:

- **OS:** Ubuntu 24.04 (Linux 6.17.0)
- **CPU:** AMD Ryzen 5 4600H with Radeon Graphics
- **Cores:** 12 physical / 12 logical
- **CPU extensions:** AVX2 (no AVX-512, no NEON)
- **RAM:** 22.8 GB
- **Accelerator:** NVIDIA GeForce GTX 1650, 4 GB VRAM (CUDA compute 7.5)
- **llama.cpp backend đã chọn:** CUDA (`-DGGML_CUDA=on`, build từ source tại `/home/son/llama.cpp`)
- **Recommended model tier:** Llama-3.2-3B-Instruct (Q4_K_M) — thực tế dùng gemma-4-E2B-it Q4_K_XL + Q2_K_XL (~2.95 GB và ~1.7 GB)

**Setup story** (≤ 80 chữ): Build llama.cpp từ source với CUDA backend vì binary `llama-server` không có trong PATH mặc định — cần thêm path thủ công vào `start-server.sh`. Model Gemma-4 dùng ISWA nên cần flag `--kv-unified` để record-metrics.py đọc được KV cache usage. GTX 1650 chỉ có 4 GB VRAM nên model fit vừa với Q4_K_XL (2.95 GB).

---

## 2. Track 01 — Quickstart numbers (từ `benchmarks/01-quickstart-results.md`)

> Paste bảng từ `benchmarks/01-quickstart-results.md` xuống đây (auto-generated bởi `python 01-llama-cpp-quickstart/benchmark.py`).

| Model | Load (ms) | TTFT P50/P95 (ms) | TPOT P50/P95 (ms) | E2E P50/P95/P99 (ms) | Decode rate (tok/s) |
|---|--:|--:|--:|--:|--:|
| gemma-4-E2B Q4_K_XL | 2717 | 74 / 138 | 15.5 / 16.2 | 1046 / 1106 / 1131 | 64.5 |
| gemma-4-E2B Q2_K_XL | 2401 | 76 / 120 | 17.6 / 18.4 | 1187 / 1234 / 1235 | 56.6 |

**Một quan sát** (≤ 50 chữ): Q4_K_XL nhanh hơn Q2_K_XL (~14% decode rate cao hơn: 64.5 vs 56.6 tok/s) — điều này ngược kỳ vọng thông thường. Lý do: Q2_K có file nhỏ hơn nhưng decode chậm hơn vì GGUF Q2 cần dequantize nhiều hơn per-token, còn GTX 1650 đủ VRAM để fit cả Q4 nên bandwidth gap không có lợi. Q4 chất lượng cao hơn và nhanh hơn trên máy này — không cần đánh đổi.

---

## 3. Track 02 — llama-server load test

> Chạy 2 lần locust ở concurrency 10 và 50, paste tóm tắt bên dưới.

| Concurrency | Total reqs | RPS | E2E P50 (ms) | E2E P95 (ms) | E2E P99 (ms) | Failures | KV ratio peak |
|--:|--:|--:|--:|--:|--:|--:|--:|
| 10 | 62 | 0.86 | 9,500 | 16,000 | 17,000 | 0% | 0.05 |
| 50 | 62 | 0.86 | 22,000 | 46,000 | 52,000 | 0% | 0.05 |

**KV-cache observation** (từ `record-metrics.py`): peak `llamacpp:kv_cache_usage_ratio` ở cả u=10 và u=50 đều là **0.05** (5%). Điều này cho thấy bottleneck không phải KV memory mà là **slot queue**: server chỉ có 4 parallel slots, khi u=50 thì `requests_deferred` tăng lên **46** (46 requests xếp hàng chờ), trong khi 4 slot đang chạy chỉ dùng <5% context window vì prompt ngắn (~80 tokens / 512 ctx/slot). E2E P95 tăng từ 16s → 46s (+188%) chủ yếu do queuing latency, không phải KV cache pressure. Tăng `--parallel` hoặc giảm `max_tokens` sẽ cải thiện nhiều hơn là tăng ctx size.

---

## 4. Track 03 — Milestone integration

- **N16 (Cloud/IaC):** stub: localhost only — llama-server chạy trực tiếp trên máy, không dùng k8s/docker-compose
- **N17 (Data pipeline):** stub: in-memory TOY_DOCS list — không có Airflow DAG hay batch ingestion
- **N18 (Lakehouse):** stub: không có Delta/Iceberg — documents được hard-code trong pipeline.py
- **N19 (Vector + Feature Store):** stub: keyword overlap scoring thay cho vector index (Qdrant/FAISS) — `retrieve()` tính term overlap đơn giản

**Nơi tốn nhiều ms nhất** trong pipeline (đo bằng `time.perf_counter` trong `pipeline.py`):

- embed/retrieve: ~0.0–0.1 ms (keyword overlap, in-memory)
- llama-server: ~3,500–3,800 ms (dominant, >99.9% total time)

**Reflection** (≤ 60 chữ): Bottleneck hoàn toàn ở llama-server (~3.7s/query). Khớp với kỳ vọng: GTX 1650 4GB decode ở ~60 tok/s, 200 max_tokens = ~3s decode time. Retrieve in-memory nhanh đến mức negligible (0.1ms). Trong production với vector DB thật (Qdrant network call), retrieve sẽ thêm 10–50ms — vẫn không đáng kể so với LLM latency.

---

## 5. Bonus — The single change that mattered most

> **Most important section.** Pick **một** thay đổi từ bonus track (build flag, thread sweep, quant pick, GPU offload, KV-cache quantization, speculative decoding, bất cứ challenge nào trong `BONUS-llama-cpp-optimization/CHALLENGES.md`) đã tạo ra speedup lớn nhất trên máy bạn.

**Change:** Build llama.cpp từ source với CUDA backend (`-DGGML_CUDA=on`) thay vì dùng `python -m llama_cpp.server` (CPU-only Python binding mặc định)

**Before vs after:**

```
before: llama_cpp.server (CPU fallback) — decode ~18 tok/s, E2E ~5,500ms/query
after:  llama-server binary (CUDA, GTX 1650) — decode ~64 tok/s, E2E ~1,050ms/query
speedup: ~3.6× decode rate, ~5.2× E2E latency improvement
```

**Tại sao nó work:** GTX 1650 có 896 CUDA cores và 128 GB/s memory bandwidth, so với Ryzen 5 4600H chỉ có ~40 GB/s DDR4 bandwidth. LLM decode là memory-bandwidth-bound — mỗi decode step phải load toàn bộ model weights từ memory. Với Q4_K_XL (~2.95 GB), GPU có thể load weights nhanh gấp 3× so với CPU, trực tiếp giải thích speedup ~3.6×.

Điều thú vị là Q2_K (nhỏ hơn, nên băng thông cần ít hơn) lại *chậm hơn* Q4 trên GPU: 56.6 vs 64.5 tok/s. Lý do là Q2 dequantization overhead trên GPU cao hơn lợi ích từ file nhỏ hơn — GPU đủ VRAM để fit Q4 nên không có pressure, trong khi Q2 thêm compute để unpack 2-bit weights. Đây là bằng chứng rằng "quant nhỏ hơn = nhanh hơn" chỉ đúng khi bị memory-constrained, không phải khi VRAM dư.

**Bonus deep-dive (C6: Vulkan vs CUDA trên cùng máy):** Với cùng model `gemma-4-E2B-it-UD-Q4_K_XL.gguf`, benchmark `llama-bench -p 512 -n 128 -r 3 -ngl 99` cho thấy Vulkan thắng mạnh ở prefill (`pp512`: 621.19 tok/s vs CUDA 273.45 tok/s, ~2.27x), nhưng CUDA vẫn nhỉnh hơn ở decode (`tg128`: 67.23 tok/s vs Vulkan 59.17 tok/s, ~1.14x). Kết quả này cho thấy backend tối ưu phụ thuộc workload phase (prefill vs decode), không có "one backend wins all". Chi tiết tại `benchmarks/bonus-c6-vulkan-vs-cuda.md`.

---

## 6. (Optional) Điều ngạc nhiên nhất

Gemma-4 với ISWA (Interleaved Sliding Window Attention) không expose `kv_cache_usage_ratio` trong `/metrics` ở llama.cpp b9029 — metric này bị remove cho non-unified KV models. Phải patch `record-metrics.py` để tính thủ công từ `/slots`. Điều này nhắc nhở rằng observability tools cũng "break" khi model architecture thay đổi, không chỉ code.

---

## 7. Self-graded checklist

- [x] `hardware.json` đã commit
- [x] `models/active.json` đã commit (hoặc paste path snapshot vào section 1)
- [x] `benchmarks/01-quickstart-results.md` đã commit
- [x] `benchmarks/02-server-metrics-u10.csv` và `benchmarks/02-server-metrics-u50.csv` đã commit
- [x] `benchmarks/bonus-*.md` đã commit (ít nhất 1 sweep)
- [x] Ít nhất 6 screenshots trong `submission/screenshots/` (xem `submission/screenshots/README.md`)
- [x] `make verify` exit 0 (chạy ngay trước khi push)
- [x] Repo trên GitHub ở chế độ **public**
- [x] Đã paste public repo URL vào VinUni LMS

---

**Quan trọng:** repo phải **public** đến khi điểm được công bố. Nếu private, grader không xem được → 0 điểm.
