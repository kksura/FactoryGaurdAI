"""Dashboard smoke test: the Streamlit script must run without raising.

Uses streamlit's AppTest harness (headless script execution). When no
evaluation reports exist (e.g. CI), the script takes its warning path and
stops — that is a valid run, not a failure.
"""

from streamlit.testing.v1 import AppTest


def test_dashboard_script_runs_clean() -> None:
    at = AppTest.from_file("apps/dashboard/main.py", default_timeout=30)
    at.run()
    assert not at.exception, f"dashboard raised: {at.exception}"
