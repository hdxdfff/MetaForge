# KernelGen T1 Sparse Attention

Artifacts:

- `sparse_attn_t1.py`: contest submission candidate.
- `validate_sparse_attn_cpu.py`: import and CPU fallback correctness smoke test.

The implementation uses a Triton streaming-softmax kernel when `torch`, `triton`,
and a CUDA-like device are available. It falls back to the exact PyTorch
reference on CPU/debug paths so the file remains importable outside the contest
runner.

Current local WSL validation is limited because this Ubuntu environment has
Python 3.12 but no `torch` or `triton` installed.
