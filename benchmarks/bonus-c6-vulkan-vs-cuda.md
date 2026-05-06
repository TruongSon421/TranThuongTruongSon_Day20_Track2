# Bonus C6 - Vulkan vs CUDA on the Same Machine

**Author:** TranThuongTruongSon  
**GPU:** NVIDIA GeForce GTX 1650 (sm_75, Turing, 3.7 GB VRAM usable)  
**Model:** `gemma-4-E2B-it-UD-Q4_K_XL.gguf` (2.95 GiB, 4.65B params)  
**llama.cpp build:** `b9029-2bacb1eb7`

---

## 1) Build configuration

### CUDA build
```bash
cmake -B build -G Ninja \
  -DGGML_CUDA=ON \
  -DCMAKE_CUDA_ARCHITECTURES=75
cmake --build build --config Release -j$(nproc)
```

### CUDA + MMQ build (optimization attempt)
```bash
cmake -B build-cuda-opt -G Ninja \
  -DGGML_CUDA=ON \
  -DCMAKE_CUDA_ARCHITECTURES=75 \
  -DGGML_CUDA_FORCE_MMQ=ON
cmake --build build-cuda-opt --config Release -j$(nproc)
```

### Vulkan build
```bash
sudo apt install -y libvulkan-dev vulkan-tools glslang-tools spirv-tools
sudo apt install -y vulkan-sdk

cmake -B build-vulkan -G Ninja \
  -DGGML_VULKAN=ON \
  -DGGML_CUDA=OFF
cmake --build build-vulkan --config Release -j$(nproc)
```

---

## 2) Benchmark results

**Command:**
```bash
llama-bench -m <model> -p 512 -n 128 -r 3 -ngl 99
```

| Backend | pp512 (tokens/s) | tg128 (tokens/s) |
|---|---:|---:|
| CUDA sm_75 | 273.45 +- 0.06 | **67.23 +- 0.20** |
| CUDA sm_75 + MMQ | 273.22 +- 0.09 | 66.99 +- 0.05 |
| **Vulkan (GTX 1650)** | **621.19 +- 0.56** | 59.17 +- 0.12 |

**Ratios:**
- `pp512`: Vulkan / CUDA = **2.27x** (Vulkan faster, unexpected vs challenge expectation)
- `tg128`: CUDA / Vulkan = **1.14x** (CUDA faster, expected direction)

---

## 3) Why the result differs from the "CUDA should be faster" expectation

On this machine, the result is mixed: Vulkan is much faster in prompt processing, while CUDA is slightly faster in token generation.

### 3.1 GTX 1650 is a tricky CUDA target for int4/int8 LLM kernels

GTX 1650 is Turing (`sm_75`). In practice for llama.cpp quantized inference, this often behaves like a "middle" generation:

- It does not provide the same low-bit Tensor Core path advantages seen on newer datacenter GPUs (Ampere/Hopper).
- Many kernels in modern inference stacks are primarily tuned for newer architectures.
- For this model + quant format, forcing MMQ (`GGML_CUDA_FORCE_MMQ=ON`) did not improve throughput, suggesting the active kernel path is not gaining from that switch here.

This does not mean CUDA is bad in general; it means this specific GPU/quant/kernel combination is not in the most favorable CUDA regime.

### 3.2 Why Vulkan can win in prompt processing (pp)

`pp512` is a large batched compute phase. A plausible explanation for the 2.27x gain:

1. The Vulkan path for this workload maps better to GTX 1650's actual execution profile.
2. NVIDIA's Vulkan driver/compiler may produce shader scheduling/tiling choices that happen to be better for this case.
3. CUDA path on `sm_75` for this quantized prompt workload may be less optimized than on newer GPUs.

Without Nsight/driver-level profiling, this should be treated as an evidence-based hypothesis, not a universal rule.

### 3.3 Why CUDA still wins in token generation (tg)

`tg128` is decode-like, small-step repeated execution with heavy weight/KV traffic on GDDR memory. CUDA still leads by 1.14x, likely because:

- Runtime and kernel stack are mature for low-latency step-wise execution.
- Memory access behavior for this phase is slightly better on the CUDA path in this setup.

The win is real but modest, consistent with a memory-sensitive regime where neither backend has a huge structural advantage on this GPU.

---

## 4) Why production stacks (vLLM/SGLang/TRT-LLM) still center on CUDA

This local result does **not** contradict production choices.

### 4.1 Different target hardware

Production systems typically target A100/H100-class GPUs where CUDA kernels exploit architecture-specific features aggressively. On those GPUs, vendor-optimized kernels usually deliver much larger gains than cross-vendor baseline paths.

### 4.2 Kernel control and fusion depth

State-of-the-art attention and serving kernels rely on architecture-specific scheduling, fusion, and memory movement strategies. In current practice, CUDA ecosystems expose and optimize these paths earlier and more deeply than Vulkan-based inference stacks.

### 4.3 Cost model

At production scale, even single-digit throughput gains are significant in cost. Backend choices are made for fleet-level efficiency on target accelerators, not for one consumer GPU configuration.

---

## 5) Conclusion

For this exact setup (GTX 1650 + Q4_K_XL + llama.cpp b9029):

- Vulkan is **2.27x faster** in prompt processing.
- CUDA is **1.14x faster** in token generation.
- `GGML_CUDA_FORCE_MMQ` does not help on this model/hardware pair.

**Main insight:** CUDA is not automatically faster than Vulkan on every NVIDIA GPU. The outcome depends on the interaction between GPU generation, quant format, and kernel maturity for the active code path.
