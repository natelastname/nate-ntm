from nate_ntm.runtime.runner import _LOG_CONFIG


def test_runtime_log_config_uses_one_console_format() -> None:
    formatters = _LOG_CONFIG["formatters"]

    assert formatters["default"]["format"] == "%(levelname)-8s %(name)s: %(message)s"
    assert formatters["access"]["format"] == (
        '%(levelname)-8s %(name)s: %(client_addr)s - "%(request_line)s" '
        "%(status_code)s"
    )
    assert _LOG_CONFIG["root"] == {
        "handlers": ["default"],
        "level": "INFO",
    }
