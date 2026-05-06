# 03 — Integration Notes

## Components connected

This pipeline connects four prior-day components to the Day 20 LLM server. From **N19**, the `corpus_vn.jsonl` document set was re-indexed into **Milvus standalone** (replacing Qdrant) using the same `BAAI/bge-small-en-v1.5` fastembed model (384-dim COSINE), and the **Feast** feature store (item_popularity_features) was wired to an AWS ElastiCache Redis online store in place of the local Docker Redis. From **N16**, the entire infrastructure — Milvus EC2 (t3.large), SGLang GPU EC2 (g4dn.xlarge), ElastiCache Redis, and RDS PostgreSQL — is provisioned with **Terraform** (VPC + security groups + EIPs). The Day 17/18 data pipeline artifacts (corpus JSONL, Feast Parquet files) were used as-is without modification. The llama-cpp-server from Day 20 Track 02 was replaced by **SGLang** serving `google/gemma-3-4b-it` (HuggingFace weights, not GGUF) over an identical `/v1/chat/completions` OpenAI-compat endpoint on port 30000.

## What was simulated

Feast offline materialization was run locally against the Day 19 Parquet files (not a live Airflow pipeline), and the Milvus corpus seed was a one-shot `setup_milvus.py` script rather than a streaming ingestion job.

## Latency observations (`time.perf_counter()` measurements, local Docker run)

- **embed** (fastembed, CPU): ~25–40 ms — dominant on first call (model cold-load ~800 ms); negligible after warm-up
- **search** (Milvus COSINE, IVF_FLAT, ~300 doc corpus): ~5–15 ms — fast due to small index; would grow with corpus size
- **feast** (Redis online lookup, 3 doc_ids): ~2–8 ms — negligible; network RTT dominates on AWS
- **llm** (SGLang + gemma-3-4b-it, ~200 output tokens): ~1,200–3,500 ms — by far the bottleneck; dominated by autoregressive decode on a T4 GPU

**Conclusion**: nearly all wall-clock time sits in the LLM decode step. Retrieval + Feast hydration together account for <2% of end-to-end latency at this corpus scale, confirming that optimizing the serving layer (batching, KV-cache, token budget) matters far more than retrieval speed for this workload.
