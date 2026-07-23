from pathlib import Path


def test_dashboard_assets_exist_in_package():
    package_dir = Path(__file__).parents[1] / "src" / "android_control"
    static_dir = package_dir / "static"

    assert (static_dir / "index.html").is_file()
    assert (static_dir / "login.html").is_file()
    assert (static_dir / "style.css").is_file()
    assert (static_dir / "app.js").is_file()
