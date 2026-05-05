import torch


try:
    register  # type: ignore[name-defined]
except NameError:
    def register(_name, _compile=False):
        def deco(fn):
            return fn
        return deco


@register("sparse_attn", False)
def sparse_attn(q, kv, attn_sink, topk_idxs, scale):
    b, m, h, d = q.shape
    topk = topk_idxs.shape[-1]
    out = torch.empty_like(q)

    # Keep the gathered KV working set bounded. The README reference gathers
    # [b, m, topk, d] at once, which can exceed memory on the official prefill
    # workloads. This chunks only the sequence dimension and keeps the exact
    # same math.
    max_gather_elems = 32 * 1024 * 1024
    denom = max(1, b * topk * d)
    block_m = max(1, min(m, max_gather_elems // denom))

    for start in range(0, m, block_m):
        end = min(start + block_m, m)
        q_blk = q[:, start:end, :, :]
        idx_blk = topk_idxs[:, start:end, :]
        bm = end - start

        flat_idx = idx_blk.long().reshape(b, bm * topk)
        gathered_kv = torch.gather(
            kv, 1, flat_idx.unsqueeze(-1).expand(-1, -1, d)
        ).reshape(b, bm, topk, d)

        scores = torch.einsum("bmhd,bmtd->bmht", q_blk.float(), gathered_kv.float()) * scale
        sink = attn_sink[None, None, :, None].expand(b, bm, h, 1)
        attn = torch.softmax(torch.cat([scores, sink], dim=-1), dim=-1)
        out[:, start:end, :, :] = torch.einsum(
            "bmht,bmtd->bmhd", attn[:, :, :, :-1], gathered_kv.float()
        ).to(q.dtype)

    return out
