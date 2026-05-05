"""
CPU smoke/correctness harness for generated/kernelgen-t1/sparse_attn_t1.py.

This validates the import path and the PyTorch fallback. GPU/Triton performance
must be validated in a contest-like environment with torch+triton installed.
"""

import importlib.util
import pathlib


def main():
    try:
        import torch
    except Exception as exc:
        print(f"SKIP: torch is not installed: {exc!r}")
        return 0

    module_path = pathlib.Path(__file__).with_name("sparse_attn_t1.py")
    spec = importlib.util.spec_from_file_location("sparse_attn_t1", module_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    torch.manual_seed(0)
    b, m, h, d = 2, 3, 4, 512
    kv_len, topk = 17, 5
    q = torch.randn(b, m, h, d, dtype=torch.bfloat16)
    kv = torch.randn(b, kv_len, d, dtype=torch.bfloat16)
    attn_sink = torch.randn(h, dtype=torch.float32)
    topk_idxs = torch.randint(0, kv_len, (b, m, topk), dtype=torch.int32)
    scale = 0.04419417382415922

    got = mod.sparse_attn(q, kv, attn_sink, topk_idxs, scale).float()
    ref = mod._torch_sparse_attn(q, kv, attn_sink, topk_idxs, scale).float()
    max_abs = (got - ref).abs().max().item()
    print(f"max_abs={max_abs:.6g}")
    assert max_abs == 0.0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
