"""Tagged-JSON encoding for the values the example tasks exchange."""


def encode(x):
    if x is None or isinstance(x, (bool, int, float, str)):
        return x
    if isinstance(x, tuple):
        return {"tuple": [encode(v) for v in x]}
    if isinstance(x, list):
        return [encode(v) for v in x]
    if isinstance(x, dict):
        return {"dict": [[encode(k), encode(v)] for k, v in x.items()]}
    raise TypeError(f"cannot send {type(x).__name__}")


def decode(x):
    if isinstance(x, list):
        return [decode(v) for v in x]
    if isinstance(x, dict):
        if set(x) == {"tuple"}:
            return tuple(decode(v) for v in x["tuple"])
        if set(x) == {"dict"}:
            return {decode(k): decode(v) for k, v in x["dict"]}
        raise ValueError("unknown tag")
    if x is None or isinstance(x, (bool, int, float, str)):
        return x
    raise ValueError(f"unexpected {type(x).__name__}")
