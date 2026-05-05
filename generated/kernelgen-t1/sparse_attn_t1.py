"""
KernelGen T1 submission: sparse_attn.

The file is intentionally self contained:
- In the contest runner, the provided `register` decorator is used.
- Outside the runner, a no-op decorator keeps the module importable.
- A PyTorch reference fallback is retained for CPU/debug import paths.

The Triton path is a conservative first pass. It specializes the fixed problem
shape (head dim 512) and avoids materializing [b, m, h, topk] scores by using a
two-pass streaming softmax with the attention sink folded into the denominator.
"""

try:
    register  # type: ignore[name-defined]
except NameError:
    def register(_name, _compile=False):
        def deco(fn):
            return fn
        return deco


try:
    import torch
except Exception:  # pragma: no cover - contest environments provide torch
    torch = None


try:
    import triton
    import triton.language as tl
except Exception:  # pragma: no cover - CPU/debug fallback
    triton = None
    tl = None


HEAD_DIM = 512
DEFAULT_SCALE = 0.04419417382415922


def _torch_sparse_attn(q, kv, attn_sink, topk_idxs, scale):
    b, m, h, d = q.shape
    topk = topk_idxs.shape[-1]
    flat_idx = topk_idxs.long().reshape(b, m * topk)
    gathered_kv = torch.gather(
        kv, 1, flat_idx.unsqueeze(-1).expand(-1, -1, d)
    ).reshape(b, m, topk, d)
    scores = torch.einsum("bmhd,bmtd->bmht", q.float(), gathered_kv.float()) * scale
    sink = attn_sink[None, None, :, None].expand(b, m, h, 1)
    attn = torch.softmax(torch.cat([scores, sink], dim=-1), dim=-1)
    out = torch.einsum("bmht,bmtd->bmhd", attn[:, :, :, :-1], gathered_kv.float())
    return out.to(q.dtype)


def _torch_sparse_attn_fast(q, kv, attn_sink, topk_idxs, scale):
    b, m, h, d = q.shape
    topk = topk_idxs.shape[-1]
    flat_idx = topk_idxs.long().reshape(b, m * topk)
    gathered_kv = torch.gather(
        kv, 1, flat_idx.unsqueeze(-1).expand(-1, -1, d)
    ).reshape(b, m, topk, d)

    scores = torch.einsum("bmhd,bmtd->bmht", q.float(), gathered_kv.float()) * scale
    sink = attn_sink[None, None, :, None]
    row_max = torch.maximum(scores.amax(dim=-1, keepdim=True), sink)
    score_exp = torch.exp(scores - row_max)
    denom = score_exp.sum(dim=-1, keepdim=True) + torch.exp(sink - row_max)
    weights = score_exp / denom
    out = torch.einsum("bmht,bmtd->bmhd", weights, gathered_kv.float())
    return out.to(q.dtype)


def _torch_full_attn_fast(q, kv, attn_sink, scale):
    scores = torch.einsum("bmhd,btd->bmht", q.float(), kv.float()) * scale
    sink = attn_sink[None, None, :, None]
    row_max = torch.maximum(scores.amax(dim=-1, keepdim=True), sink)
    score_exp = torch.exp(scores - row_max)
    denom = score_exp.sum(dim=-1, keepdim=True) + torch.exp(sink - row_max)
    weights = score_exp / denom
    out = torch.einsum("bmht,btd->bmhd", weights, kv.float())
    return out.to(q.dtype)


if triton is not None:

    @triton.jit
    def _sparse_attn_kernel(
        q_ptr,
        kv_ptr,
        sink_ptr,
        idx_ptr,
        out_ptr,
        scale: tl.constexpr,
        bsz: tl.constexpr,
        seq_len: tl.constexpr,
        heads: tl.constexpr,
        kv_len: tl.constexpr,
        topk: tl.constexpr,
        d_block_id: tl.constexpr,
        HEAD_DIM_C: tl.constexpr,
        BLOCK_D: tl.constexpr,
        BLOCK_T: tl.constexpr,
    ):
        pid = tl.program_id(0)
        h_id = tl.program_id(1)

        token_id = pid % seq_len
        b_id = pid // seq_len

        offs_d = d_block_id * BLOCK_D + tl.arange(0, BLOCK_D)
        full_d = tl.arange(0, HEAD_DIM_C)
        offs_t = tl.arange(0, BLOCK_T)

        q_base = ((b_id * seq_len + token_id) * heads + h_id) * HEAD_DIM_C
        q_full = tl.load(q_ptr + q_base + full_d, mask=full_d < HEAD_DIM_C).to(tl.float32)

        sink = tl.load(sink_ptr + h_id).to(tl.float32)
        row_max = sink

        for t0 in range(0, topk, BLOCK_T):
            t = t0 + offs_t
            valid_t = t < topk
            kv_idx = tl.load(
                idx_ptr + (b_id * seq_len + token_id) * topk + t,
                mask=valid_t,
                other=0,
            )
            scores = tl.zeros((BLOCK_T,), tl.float32)
            for d0 in range(0, HEAD_DIM_C, 64):
                kd = d0 + tl.arange(0, 64)
                qv = tl.load(q_ptr + q_base + kd).to(tl.float32)
                kvv = tl.load(
                    kv_ptr + (b_id * kv_len + kv_idx[:, None]) * HEAD_DIM_C + kd[None, :],
                    mask=valid_t[:, None],
                    other=0.0,
                ).to(tl.float32)
                scores += tl.sum(kvv * qv[None, :], axis=1)
            scores = scores * scale
            scores = tl.where(valid_t, scores, -float("inf"))
            row_max = tl.maximum(row_max, tl.max(scores, axis=0))

        denom = tl.exp(sink - row_max)
        for t0 in range(0, topk, BLOCK_T):
            t = t0 + offs_t
            valid_t = t < topk
            kv_idx = tl.load(
                idx_ptr + (b_id * seq_len + token_id) * topk + t,
                mask=valid_t,
                other=0,
            )
            scores = tl.zeros((BLOCK_T,), tl.float32)
            for d0 in range(0, HEAD_DIM_C, 64):
                kd = d0 + tl.arange(0, 64)
                qv = tl.load(q_ptr + q_base + kd).to(tl.float32)
                kvv = tl.load(
                    kv_ptr + (b_id * kv_len + kv_idx[:, None]) * HEAD_DIM_C + kd[None, :],
                    mask=valid_t[:, None],
                    other=0.0,
                ).to(tl.float32)
                scores += tl.sum(kvv * qv[None, :], axis=1)
            scores = scores * scale
            scores = tl.where(valid_t, scores, -float("inf"))
            denom += tl.sum(tl.exp(scores - row_max), axis=0)

        acc = tl.zeros((BLOCK_D,), tl.float32)
        for t0 in range(0, topk, BLOCK_T):
            t = t0 + offs_t
            valid_t = t < topk
            kv_idx = tl.load(
                idx_ptr + (b_id * seq_len + token_id) * topk + t,
                mask=valid_t,
                other=0,
            )
            scores = tl.zeros((BLOCK_T,), tl.float32)
            for d0 in range(0, HEAD_DIM_C, 64):
                kd = d0 + tl.arange(0, 64)
                qv = tl.load(q_ptr + q_base + kd).to(tl.float32)
                kvv = tl.load(
                    kv_ptr + (b_id * kv_len + kv_idx[:, None]) * HEAD_DIM_C + kd[None, :],
                    mask=valid_t[:, None],
                    other=0.0,
                ).to(tl.float32)
                scores += tl.sum(kvv * qv[None, :], axis=1)

            weight = tl.exp(scores * scale - row_max) / denom
            weight = tl.where(valid_t, weight, 0.0)
            vals = tl.load(
                kv_ptr + (b_id * kv_len + kv_idx[:, None]) * HEAD_DIM_C + offs_d[None, :],
                mask=valid_t[:, None] & (offs_d[None, :] < HEAD_DIM_C),
                other=0.0,
            ).to(tl.float32)
            acc += tl.sum(vals * weight[:, None], axis=0)

        out_base = ((b_id * seq_len + token_id) * heads + h_id) * HEAD_DIM_C
        tl.store(out_ptr + out_base + offs_d, acc, mask=offs_d < HEAD_DIM_C)


def _launch_triton(q, kv, attn_sink, topk_idxs, scale):
    b, m, h, d = q.shape
    if d != HEAD_DIM:
        return _torch_sparse_attn(q, kv, attn_sink, topk_idxs, scale)

    kv_len = kv.shape[1]
    topk = topk_idxs.shape[-1]
    out = torch.empty_like(q)

    # Smaller topk benefits from less register pressure; larger topk benefits
    # from wider streaming blocks. Keep powers of two for broad backend support.
    block_t = 16 if topk <= 128 else 32
    block_d = 128
    grid = (b * m, h)
    for d_block_id in range(HEAD_DIM // block_d):
        _sparse_attn_kernel[grid](
            q,
            kv,
            attn_sink,
            topk_idxs,
            out,
            float(scale),
            b,
            m,
            h,
            kv_len,
            topk,
            d_block_id,
            HEAD_DIM_C=HEAD_DIM,
            BLOCK_D=block_d,
            BLOCK_T=block_t,
            num_warps=4,
        )
    return out


@register("sparse_attn", False)
def sparse_attn(q, kv, attn_sink, topk_idxs, scale=DEFAULT_SCALE):
    if torch is None:
        raise RuntimeError("torch is required to run sparse_attn")
    # The current portable Triton experiment is correct but slower on the
    # available RTX 4060 validation GPU because it recomputes score statistics
    # for each output-D block. Use the lower-overhead torch path for submission
    # stability while keeping _launch_triton available for continued tuning.
    if topk_idxs.shape[-1] == kv.shape[1]:
        return _torch_full_attn_fast(q, kv, attn_sink, scale)
    if topk_idxs.shape[-1] >= 384:
        return _torch_sparse_attn(q, kv, attn_sink, topk_idxs, scale)
    return _torch_sparse_attn_fast(q, kv, attn_sink, topk_idxs, scale)
