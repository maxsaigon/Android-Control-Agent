"""Task template manager — loads and renders task templates."""

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


class TemplateManager:
    """Manages task templates with variable substitution."""

    _STATUS_RANK = {
        "primary": 0,
        "active": 1,
        "beta": 2,
        "planned": 3,
    }

    def _parse_scalar(self, raw: str) -> Any:
        raw = raw.strip()
        if not raw:
            return ""

        if raw[0] in "[{":
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass

        lower = raw.lower()
        if lower in {"true", "false"}:
            return lower == "true"
        if lower in {"null", "none"}:
            return None

        if (raw.startswith('"') and raw.endswith('"')) or (
            raw.startswith("'") and raw.endswith("'")
        ):
            return raw[1:-1]

        if re.fullmatch(r"-?\d+", raw):
            try:
                return int(raw)
            except ValueError:
                return raw

        if re.fullmatch(r"-?\d+\.\d+", raw):
            try:
                return float(raw)
            except ValueError:
                return raw

        return raw

    def _split_frontmatter(self, content: str) -> tuple[dict[str, Any], str]:
        match = re.match(r"^---\n(.*?)\n---\n?(.*)$", content, re.DOTALL)
        if not match:
            return {}, content

        raw_meta, body = match.groups()
        meta: dict[str, Any] = {}
        for line in raw_meta.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            key, sep, value = stripped.partition(":")
            if not sep:
                continue
            meta[key.strip()] = self._parse_scalar(value.strip())
        return meta, body

    def _read_template_parts(self, path: Path) -> tuple[dict[str, Any], str]:
        content = path.read_text(encoding="utf-8")
        meta, body = self._split_frontmatter(content)
        return meta, body

    def _extract_title(self, body: str, fallback: str) -> str:
        lines = body.strip().splitlines()
        return lines[0].lstrip("# ").strip() if lines else fallback

    def _extract_description(self, body: str) -> str:
        lines = body.strip().splitlines()
        for line in lines[1:]:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                return stripped
        return ""

    def _normalize_meta(self, path: Path, meta: dict[str, Any], body: str) -> dict[str, Any]:
        title = meta.get("title") or self._extract_title(body, path.stem)
        description = meta.get("description") or self._extract_description(body)
        platform = meta.get("platform") or (
            path.stem.split("_", 1)[0] if "_" in path.stem else "general"
        )
        mode = meta.get("mode") or "ai"
        status = meta.get("status") or "active"
        default_vars = meta.get("default_vars") or {}
        ui_fields = meta.get("ui_fields") or []
        capabilities = meta.get("capabilities") or []
        limitations = meta.get("limitations") or []

        if not isinstance(default_vars, dict):
            default_vars = {}
        if not isinstance(ui_fields, list):
            ui_fields = []
        if not isinstance(capabilities, list):
            capabilities = []
        if not isinstance(limitations, list):
            limitations = []

        return {
            "name": path.stem,
            "title": title,
            "description": description,
            "file": path.name,
            "platform": platform,
            "mode": mode,
            "status": status,
            "is_primary": bool(meta.get("is_primary", False)),
            "implemented": bool(meta.get("implemented", True)),
            "default_vars": default_vars,
            "ui_fields": ui_fields,
            "capabilities": capabilities,
            "limitations": limitations,
            "risk_level": meta.get("risk_level", "medium"),
            "fallback_behavior": meta.get("fallback_behavior", ""),
            "sort_order": int(meta.get("sort_order", 999)),
        }

    def _normalize_variables(self, name: str, variables: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(variables)
        if name == "tiktok_comment":
            if "count" in normalized and "max_comments" not in normalized:
                normalized["max_comments"] = normalized["count"]
            if "max_comments" in normalized and "count" not in normalized:
                normalized["count"] = normalized["max_comments"]
        return normalized

    def list_templates(self) -> list[dict]:
        """List all available templates with metadata."""
        templates = []
        for path in sorted(TEMPLATES_DIR.glob("*.md")):
            meta, body = self._read_template_parts(path)
            templates.append(self._normalize_meta(path, meta, body))

        templates.sort(
            key=lambda item: (
                0 if item["is_primary"] else 1,
                self._STATUS_RANK.get(item["status"], 9),
                item["sort_order"],
                item["title"].lower(),
            )
        )
        return templates

    def get_template(self, name: str) -> Optional[str]:
        """Get raw template content by name."""
        path = TEMPLATES_DIR / f"{name}.md"
        if not path.exists():
            return None
        _, body = self._read_template_parts(path)
        return body.strip()

    def get_template_meta(self, name: str) -> Optional[dict]:
        """Get normalized metadata for a single template."""
        path = TEMPLATES_DIR / f"{name}.md"
        if not path.exists():
            return None
        meta, body = self._read_template_parts(path)
        return self._normalize_meta(path, meta, body)

    # Default values for common template variables
    DEFAULTS = {
        "repeat_count": "5",
        "duration": "10",
        "react_count": "5",
        "max_steps": "20",
        # TikTok-specific defaults
        "session_count": "3",
        "like_count": "10",
        "like_chance": "0.3",
        "max_comments": "5",
        "follow_count": "5",
        "follow_style": "from_feed",
        "comment_pool": "",
        "caption": "",
        "hashtags": "",
        "display_name": "",
        "bio": "",
        "avatar_path": "",
    }

    def render(self, name: str, **variables) -> str:
        """
        Load a template and substitute variables.

        Variables use {{var_name}} syntax in templates.
        """
        content = self.get_template(name)
        if content is None:
            raise FileNotFoundError(f"Template not found: {name}")

        # Apply defaults first, then user variables override
        meta = self.get_template_meta(name) or {}
        normalized_variables = self._normalize_variables(name, variables)
        all_vars = {
            **self.DEFAULTS,
            **meta.get("default_vars", {}),
            **normalized_variables,
        }
        for key, value in all_vars.items():
            content = content.replace(f"{{{{{key}}}}}", str(value))

        # Remove any remaining unresolved {{var}} placeholders
        import re
        content = re.sub(r"\{\{[^}]+\}\}", "", content)

        return content

    def render_command(
        self, name: str, base_command: str, variables: dict | None = None
    ) -> str:
        """
        Build final command from template + base command + variables.

        If template exists, render it and prepend to the command.
        If not, return just the command.
        """
        if not name:
            return base_command

        try:
            template_content = self.render(name, **(variables or {}))
            # Combine template instructions with the user command
            return f"{template_content}\n\n---\nUser command: {base_command}"
        except FileNotFoundError:
            logger.warning(f"Template '{name}' not found, using raw command")
            return base_command


# Singleton
template_manager = TemplateManager()
