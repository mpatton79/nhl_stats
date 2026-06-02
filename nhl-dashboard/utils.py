def fmt_season(s: str) -> str:
    """'20232024' → '2023-24'"""
    return f"{s[:4]}-{s[6:]}"
