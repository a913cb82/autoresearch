"""Improve-step prompt. Plain Python: edit freely, keep the signature."""


def render(
    *,
    parent_code: str | None,
    parent_score: str | None,
    current_code: str,
    current_score: str,
    read_paths: list[str],
) -> str:
    parent = ""
    if parent_code is not None:
        parent = (
            f"Parent score: {parent_score}\n\nParent code:\n```\n{parent_code}\n```\n"
        )
    refs = ""
    if read_paths:
        bullets = "\n".join(f"- {p}" for p in read_paths)
        refs = (
            "You may read these reference files with read_approved"
            f" (read-only, nothing else):\n{bullets}\n"
        )
    return (
        "Rewrite the code below to score higher. Higher is better.\n"
        "\n"
        f"{parent}Current score: {current_score}\n"
        "\n"
        "Current code:\n"
        "```\n"
        f"{current_code}\n"
        "```\n"
        f"{refs}Use write_candidate to save the complete improved file.\n"
    )
