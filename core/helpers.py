import re


def _split_args(text: str) -> list[str]:
    return [t.strip() for t in re.findall(r'(?:[^\s"]+|"[^"]*")+', text) if t.strip()]
