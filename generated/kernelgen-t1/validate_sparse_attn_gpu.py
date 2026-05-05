"""
GPU/Triton smoke test for sparse_attn_t1.py.

Run from WSL:
    source /mnt/d/AI-Lab/wsl-ai-experiments/envs/general-ai/bin/activate
    cd "/mnt/d/AI-Lab/KernelGen 24 Hour Challenge – Registration"
    python validate_sparse_attn_gpu.py
"""

import importlib.util
import pathlib

import torch


def load_module():
    module_path = pathlib.Path(__file__).with_name("sparse_attn_t1.py")
    spec = importlib.util.spec_from_file_location("sparse_attn_t1", module_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_case(mod, topk, kv_len):
    torch.manual_seed(topk)
    b, m, h, d = 1, 2, 16, 512
    q = torch.randn(b, m, h, d, device="cuda", dtype=torch.bfloat16)
    kv = torch.randn(b, kv_len, d, device="cuda", dtype=torch.bfloat16)
    attn_sink = torch.randn(h, device="cuda", dtype=torch.float32)
    if topk == kv_len:
        topk_idxs = torch.arange(kv_len, device="cuda", dtype=torch.int32).expand(b, m, topk).contiguous()
    else:
        topk_idxs = torch.randint(0, kv_len, (b, m, topk), device="cuda", dtype=torch.int32)
    scale = 0.04419417382415922

    got = mod._launch_triton(q, kv, attn_sink, topk_idxs, scale)
    torch.cuda.synchronize()
    ref = mod._torch_sparse_attn(q, kv, attn_sink, topk_idxs, scale)
    max_abs = (got.float() - ref.float()).abs().max().item()
    print(f"topk={topk} kv_len={kv_len} max_abs={max_abs:.6g}")
    assert max_abs <= 0.002


def main():
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this GPU smoke test")
    mod = load_module()
    for topk, kv_len in [(128, 128), (384, 400), (640, 640)]:
        run_case(mod, topk, kv_len)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
