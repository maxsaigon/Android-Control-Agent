from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.template_manager import template_manager


def test_list_templates_exposes_metadata():
    templates = template_manager.list_templates()
    assert templates

    primary = templates[0]
    assert primary["name"] == "tiktok_comment"
    assert primary["is_primary"] is True
    assert primary["mode"] == "hybrid"
    assert isinstance(primary["default_vars"], dict)
    assert isinstance(primary["ui_fields"], list)
    assert isinstance(primary["capabilities"], list)
    assert isinstance(primary["limitations"], list)


def test_get_template_strips_frontmatter():
    content = template_manager.get_template("tiktok_comment")
    assert content is not None
    assert not content.startswith("---")
    assert "# TikTok Comment Videos" in content


def test_render_tiktok_comment_supports_count_aliases():
    rendered_from_count = template_manager.render("tiktok_comment", count=7)
    rendered_from_legacy = template_manager.render("tiktok_comment", max_comments=4)

    assert "7 comment đã verify" in rendered_from_count
    assert "4 comment đã verify" in rendered_from_legacy
