# KernelGen T1 Sparse Attention

Artifacts:

- `sparse_attn_t1.py`: contest submission candidate.
- `validate_sparse_attn_cpu.py`: import and CPU fallback correctness smoke test.
- `validate_sparse_attn_gpu.py`: Triton smoke test for topk 128/384/640.
- `benchmark_sparse_attn.py`: small benchmark against the PyTorch reference.
- `check_env.py`: torch/triton/CUDA environment probe.

The implementation uses a Triton streaming-softmax kernel when `torch`, `triton`,
and a CUDA-like device are available. It falls back to the exact PyTorch
reference on CPU/debug paths so the file remains importable outside the contest
runner.

AI-Lab WSL environment:

```bash
source /mnt/d/AI-Lab/wsl-ai-experiments/envs/general-ai/bin/activate
cd "/mnt/d/AI-Lab/KernelGen 24 Hour Challenge – Registration"
python check_env.py
python validate_sparse_attn_cpu.py
python validate_sparse_attn_gpu.py
python benchmark_sparse_attn.py --repeat 10
```

Observed environment: `torch 2.10.0+cu126`, `triton 3.6.0`, CUDA available on
NVIDIA GeForce RTX 4060 Laptop GPU.
