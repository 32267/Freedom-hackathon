"""Цены за 1M токенов (USD), первая сторона Anthropic API. Обновлять при смене модели."""
PRICES = {
    "claude-opus-5-5": (4.00, 20.00, 0.20),      # input, output, cache read
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
}


def cost_usd(model: str, input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0) -> float:
    inp, out, cached = PRICES.get(model, (0.0, 0.0, 0.0))
    return round((input_tokens * inp + cache_write * inp * 1.25 + cache_read * cached + output_tokens * out) / 1e6, 6)
