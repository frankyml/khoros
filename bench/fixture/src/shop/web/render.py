import html

BADGE_KINDS = ("new", "low-stock")


def render_badge(kind: str) -> str:
    if kind not in BADGE_KINDS:
        raise ValueError(f"unknown badge kind: {kind}")
    label = kind.replace("-", " ").capitalize()
    return f'<span class="badge badge--{kind}">{html.escape(label)}</span>'
