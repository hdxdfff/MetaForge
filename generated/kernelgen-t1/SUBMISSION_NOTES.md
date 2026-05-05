# Submission Notes

Current recommended upload file:

- `sparse_attn_t1.py`

Strategy:

- `topk == kv_len`: skip `topk_idxs` gather and run full-KV attention directly.
  This targets the exact full-attention decode cases such as `kv_len=128,
  topk=128` and `kv_len=640, topk=640`.
- `topk < 384`: use a no-concat stable softmax path that avoids allocating the
  extra sink column.
- `topk >= 384` and not full-KV: use the reference-shaped PyTorch path, which is
  more stable than the current portable Triton experiment on the validation GPU.
- `_launch_triton` remains in the file as an experimental correct kernel, but it
  is not the default submission path because it recomputes score statistics per
  output-D block.

Latest local validation environment:

- WSL env: `/mnt/d/AI-Lab/wsl-ai-experiments/envs/general-ai`
- torch: `2.10.0+cu126`
- triton: `3.6.0`
- GPU: `NVIDIA GeForce RTX 4060 Laptop GPU`

Latest smoke validation:

- CPU fallback correctness: `max_abs=0`
- GPU Triton direct smoke:
  - `topk=128 kv_len=128 max_abs=0.00195312`
  - `topk=384 kv_len=400 max_abs=4.76837e-07`
  - `topk=640 kv_len=640 max_abs=1.19209e-07`

Latest short benchmark highlights:

- full-KV path improves scaled `prefill_t128_small` and `prefill_t640_small`.
- `decode_b64_t392`, `decode_b16_t640`, and `decode_b1_t640` are close to
  reference baseline.
- The current bottleneck is still true fused sparse attention for non-full
  `topk>=384`; a faster Triton version needs shared row statistics instead of
  recomputing per output-D block.
