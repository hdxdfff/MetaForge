"""
Benchmark sparse_attn_t1.py against the PyTorch reference on representative
scaled-down and exact decode cases.

The exact prefill cases are very large for a laptop GPU, so this script keeps
prefill batch/seq smaller by default while preserving d=512, h=16 and the
important topk values.
"""

import argparse
import importlib.util
import json
import pathlib
import time

import torch


CASES = [
    ("prefill_t128_small", 1, 64, 128, 128, 16),
    ("prefill_t384_small", 1, 32, 400, 384, 16),
    ("prefill_t640_small", 1, 16, 640, 640, 16),
    ("decode_b64_t128", 64, 1, 128, 128, 16),
    ("decode_b64_t392", 64, 1, 400, 392, 16),
    ("decode_b64_t640", 64, 1, 640, 640, 16),
    ("decode_b16_t640", 16, 1, 1408, 640, 16),
    ("decode_b1_t640", 1, 1, 4480, 640, 16),
]


def load_module():
    module_path = pathlib.Path(__file__).with_name("sparse_attn_t1.py")
    spec = importlib.util.spec_from_file_location("sparse_attn_t1", module_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_case(b, m, kv_len, topk, h):
    torch.manual_seed(b * 1_000_000 + m * 10_000 + kv_len + topk)
    d = 512
    q = torch.randn(b, m, h, d, device="cuda", dtype=torch.bfloat16)
    kv = torch.randn(b, kv_len, d, device="cuda", dtype=torch.bfloat16)
    attn_sink = torch.randn(h, device="cuda", dtype=torch.float32)
    if topk == kv_len:
        base = torch.arange(kv_len, device="cuda", dtype=torch.int32)
        topk_idxs = base.expand(b, m, topk).contiguous()
    else:
        topk_idxs = torch.randint(0, kv_len, (b, m, topk), device="cuda", dtype=torch.int32)
    return q, kv, attn_sink, topk_idxs


def bench(fn, args, warmup, repeat):
    for _ in range(warmup):
        out = fn(*args)
    torch.cuda.synchronize()
    start = time.perf_counter()
    for _ in range(repeat):
        out = fn(*args)
    torch.cuda.synchronize()
    elapsed = time.perf_counter() - start
    return elapsed * 1000.0 / repeat, out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--repeat", type=int, default=20)
    parser.add_argument("--case", default=None)
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")

    mod = load_module()
    selected = [c for c in CASES if args.case in (None, c[0])]
    results = []
    for name, b, m, kv_len, topk, h in selected:
        tensors = make_case(b, m, kv_len, topk, h)
        call_args = (*tensors, 0.04419417382415922)
        fast_ms, got = bench(mod.sparse_attn, call_args, args.warmup, args.repeat)
        triton_ms, triton_out = bench(mod._launch_triton, call_args, args.warmup, args.repeat)
        torch_ms, ref = bench(mod._torch_sparse_attn, call_args, max(1, args.warmup // 2), max(3, args.repeat // 4))
        max_abs = (got.float() - ref.float()).abs().max().item()
        triton_max_abs = (triton_out.float() - ref.float()).abs().max().item()
        speedup = torch_ms / fast_ms if fast_ms else 0.0
        item = {
            "case": name,
            "shape": {"b": b, "m": m, "kv_len": kv_len, "topk": topk, "h": h, "d": 512},
            "submission_ms": fast_ms,
            "experimental_triton_ms": triton_ms,
            "torch_ms": torch_ms,
            "speedup_vs_torch": speedup,
            "max_abs": max_abs,
            "experimental_triton_max_abs": triton_max_abs,
        }
        print(json.dumps(item, ensure_ascii=False))
        results.append(item)
    pathlib.Path("benchmark_sparse_attn_results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
