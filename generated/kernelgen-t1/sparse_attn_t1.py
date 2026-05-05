import torch
import torch.nn.functional as F


try:
    register  # type: ignore[name-defined]
except NameError:
    def register(_name, _compile=False):
        def deco(fn):
            return fn
        return deco


@register("sparse_attn", False)
def sparse_attn(q, kv, attn_sink, topk_idxs, scale):
    """
    Reference sparse attention in pure PyTorch.

    Args:
        q:          [b, m, h, d], bf16
        kv:         [b, kv_len, d], bf16
        attn_sink:  [h], fp32
        topk_idxs:  [b, m, topk], int32
        scale:      float

    Returns:
        o: [b, m, h, d], same dtype as q
    """
    b, m, h, d = q.shape
    topk = topk_idxs.shape[-1]

    flat_idx = topk_idxs.long().reshape(b, m * topk)
    gathered_kv = torch.gather(kv, 1, flat_idx.unsqueeze(-1).expand(-1, -1, d)).reshape(b, m, topk, d)

    scores = torch.einsum("bmhd,bmtd->bmht", q.float(), gathered_kv.float()) * scale

    sink = attn_sink[None, None, :, None].expand(b, m, h, 1)
    scores_with_sink = torch.cat([scores, sink], dim=-1)
    attn = torch.softmax(scores_with_sink, dim=-1)

    attn_kv = attn[:, :, :, :-1]
    o = torch.einsum("bmht,bmtd->bmhd", attn_kv, gathered_kv.float())
    return o.to(q.dtype)
