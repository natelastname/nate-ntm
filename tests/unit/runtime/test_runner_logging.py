import logging

from uvicorn.logging import AccessFormatter

from nate_ntm.runtime.runner import _LOG_CONFIG


def test_runtime_log_config_uses_one_console_format() -> None:
    formatters = _LOG_CONFIG["formatters"]

    assert formatters["default"]["format"] == "%(levelname)-8s %(name)s: %(message)s"
    assert formatters["access"] == {
        "()": "uvicorn.logging.AccessFormatter",
        "format": '%(levelname)-8s %(name)s: %(client_addr)s - "%(request_line)s" %(status_code)s',
        "use_colors": False,
    }
    assert _LOG_CONFIG["root"] == {
        "handlers": ["default"],
        "level": "INFO",
    }


def test_access_formatter_handles_uvicorn_access_record() -> None:
    formatter = AccessFormatter(
        _LOG_CONFIG["formatters"]["access"]["format"],
        use_colors=False,
    )
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:51742", "POST", "/api", "1.1", 404),
        exc_info=None,
    )

    assert formatter.format(record) == (
        'INFO     uvicorn.access: 127.0.0.1:51742 - "POST /api HTTP/1.1" 404 Not Found'
    )
