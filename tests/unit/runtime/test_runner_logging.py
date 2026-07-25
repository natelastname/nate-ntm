from nate_ntm.runtime.runner import _UVICORN_LOG_CONFIG


def test_uvicorn_log_config_uses_project_console_format() -> None:
    formatters = _UVICORN_LOG_CONFIG["formatters"]

    assert formatters["default"]["format"] == "%(levelname)-8s %(name)s: %(message)s"
    assert formatters["access"]["format"] == (
        '%(levelname)-8s %(name)s: %(client_addr)s - "%(request_line)s" '
        "%(status_code)s"
    )
