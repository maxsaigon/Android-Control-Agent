"""Shared helpers for stable cloud-device identity."""


def cloud_display_name(base_name: str, device_id: int) -> str:
    """Build a readable cloud-device label that remains unique in the UI."""
    clean = (base_name or "Cloud Device").strip()
    suffix = f" #{device_id}"
    if clean.endswith(suffix):
        clean = clean[: -len(suffix)]
    return f"{clean}{suffix}"
