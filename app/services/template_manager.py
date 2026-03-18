"""Task template manager — loads and renders task templates."""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


class TemplateManager:
    """Manages task templates with variable substitution."""

    def list_templates(self) -> list[dict]:
        """List all available templates with metadata."""
        templates = []
        for path in sorted(TEMPLATES_DIR.glob("*.md")):
            content = path.read_text(encoding="utf-8")
            # Extract first line as title
            lines = content.strip().splitlines()
            title = lines[0].lstrip("# ").strip() if lines else path.stem
            # Extract description (first non-empty line after title)
            desc = ""
            for line in lines[1:]:
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    desc = stripped
                    break

            templates.append({
                "name": path.stem,
                "title": title,
                "description": desc,
                "file": path.name,
            })
        return templates

    def get_template(self, name: str) -> Optional[str]:
        """Get raw template content by name."""
        path = TEMPLATES_DIR / f"{name}.md"
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

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
        all_vars = {**self.DEFAULTS, **variables}
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
