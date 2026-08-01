from sfttrain.records import Example


def make_example(i=0, response="ok", quality=0.9, flags=None, thought=None, messages=None):
    return Example(
        id=f"ex-{i}",
        source="unit",
        messages=messages if messages is not None else [{"role": "user", "content": f"question {i}"}],
        response=response,
        thought=thought,
        quality=quality,
        flags=list(flags or []),
    )
