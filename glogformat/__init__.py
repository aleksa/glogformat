"""Google glog-style logging formatter for Python.

This module provides formatters that match Google's glog format with
microsecond precision, automatic color detection for terminals, and robust
handling of edge cases like unavailable stderr or daemonized processes.

Key features:
- Colors enabled for TTY output, disabled when redirected to files
- No ANSI escape sequences in log files (safe for grep, viewing, archiving)
- Microsecond-precision timestamps
- Thread-safe (compatible with GIL-free Python 3.13+)

Compatible with Python 3.10+ on Linux and Mac systems.
Windows compatibility is untested and not the primary target environment.
"""

import datetime
import logging
import logging.handlers
import os
import sys
import threading
from typing import Any
from typing import Literal
from typing import Mapping
from typing import TYPE_CHECKING

__all__ = [
    "GlogFormatter",
    "ColorGlogFormatter",
    "setup_stderr_logging",
    "disable_child_propagation",
]


def _safe_stderr_write(message: str, /) -> None:
    """Write a message to stderr, ignoring any exceptions."""
    try:
        if sys.stderr:
            sys.stderr.write(message)
            sys.stderr.flush()
    except Exception:  # pylint: disable=broad-exception-caught
        pass


class RotationErrorFilter(logging.Filter):
    """Filter to emit a single warning for log rotation failures.

    Thread-safe implementation using a lock to ensure the warning is shown
    only once, even in GIL-free Python (3.13+).
    """

    def __init__(self) -> None:
        super().__init__()
        self._warning_shown: bool = False
        self._lock: threading.Lock = threading.Lock()

    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info:
            with self._lock:
                if not self._warning_shown:
                    self._warning_shown = True
                    _safe_stderr_write(
                        f"Warning: Log rotation failed: {record.getMessage()}\n"
                    )
        return True


class GlogFormatter(logging.Formatter):
    """Custom formatter that matches Google's glog format.

    Format: L<YYYYMMDD HH:MM:SS.uuuuuu> <PID> <TID> <filename>:<line>] <message>
    where:
        L = First letter of log level (D, I, W, E, C)
        YYYYMMDD = Date
        HH:MM:SS.uuuuuu = Time with microsecond precision
        PID = Process ID (decimal)
        TID = Thread ID (decimal, no padding to accommodate large IDs)
        filename:line = Source file and line number
        message = Log message

    Notes:
        - Custom log levels with multi-character names will be truncated to
          their first character by %(levelname)-.1s. For example, a custom
          "VERBOSE" level would appear as "V". Ensure custom level names don't
          conflict with standard levels (D, I, W, E, C).
        - Thread IDs on Linux can be large integers (up to 15 digits on 64-bit
          systems), so no padding is applied to avoid truncation.
        - Timestamps use local time by default (use_utc=False) to match
          standard glog. Set use_utc=True for UTC timestamps in distributed
          systems.
        - In multi-threaded applications, a threading.Lock is used to ensure
          timestamp error warnings are shown only once per formatter instance,
          preventing race conditions.
    """

    FMT: str = (
        "%(levelname)-.1s%(asctime)s "
        "%(process)d %(thread)d "
        "%(filename)s:%(lineno)d] "
        "%(message)s"
    )
    DATEFMT: str = "%Y%m%d %H:%M:%S"
    UTC_TZ: datetime.timezone = (
        datetime.timezone.utc
    )  # Cached timezone for performance

    def __init__(
        self,
        fmt: str | None = None,
        datefmt: str | None = None,
        style: Literal["%", "{", "$"] = "%",
        validate: bool = True,
        *,
        defaults: Mapping[str, Any] | None = None,
        use_utc: bool = False,
    ) -> None:
        """Initialize the glog formatter."""
        self.use_utc: bool = use_utc
        self._timestamp_warning_shown: bool = False
        self._lock: threading.Lock = threading.Lock()
        if fmt is None:
            fmt = self.FMT
        if datefmt is None:
            datefmt = self.DATEFMT
        super().__init__(fmt, datefmt, style, validate, defaults=defaults)

    def formatTime(
        self, record: logging.LogRecord, datefmt: str | None = None
    ) -> str:
        """Override formatTime to provide microsecond precision."""
        try:
            dt: datetime.datetime = datetime.datetime.fromtimestamp(
                record.created, tz=self.UTC_TZ
            )
            if not self.use_utc:
                dt = dt.astimezone()
            if datefmt:
                formatted_time: str = dt.strftime(datefmt)
                return f"{formatted_time}.{dt.microsecond:06d}"
        except (ValueError, OverflowError, OSError) as e:
            with self._lock:
                if not self._timestamp_warning_shown:
                    self._timestamp_warning_shown = True
                    _safe_stderr_write(
                        f"Warning: GlogFormatter failed to format timestamp "
                        f"(record.created={record.created}): {e}\n"
                    )
            # Return a fallback timestamp
            try:
                return super().formatTime(record, datefmt)
            except (ValueError, OverflowError, OSError):
                # If super() also fails, return a placeholder
                return "00000000 00:00:00.000000"
        return super().formatTime(record, datefmt)


if TYPE_CHECKING:
    ColorFormatterMixinBase = GlogFormatter
else:
    ColorFormatterMixinBase = object


class ColorFormatterMixin(ColorFormatterMixinBase):
    """Add ANSI color codes for Linux and Mac terminal output.

    Colors are only applied when output is to a TTY. When piped to a file
    or non-TTY stream, plain text is used to avoid ANSI escape sequences
    in log files. The color codes are standard ANSI sequences compatible
    with modern Linux and Mac terminals (e.g., xterm, GNOME Terminal, Kitty,
    Terminal.app, iTerm2). Rendering may vary slightly depending on terminal
    themes (e.g., Bright Black may appear as light or dark grey). Windows
    compatibility is untested and not the primary target.

    Attributes:
        LEVEL2COLORCODE: Mapping of log levels to ANSI color codes.
        UNKNOWN_LEVEL_COLOR: Default color for unknown log levels.
        RESET_CODE: ANSI code to reset terminal color.
    """

    LEVEL2COLORCODE: dict[int, str] = {
        logging.DEBUG: "\x1b[36m",  # Cyan
        logging.INFO: "\x1b[90m",  # Bright Black (grey)
        logging.WARNING: "\x1b[33m",  # Yellow
        logging.ERROR: "\x1b[31m",  # Red
        logging.CRITICAL: "\x1b[1;35m",  # Bold Magenta
    }
    UNKNOWN_LEVEL_COLOR: str = "\x1b[90m"  # Bright Black (grey)
    RESET_CODE: str = "\x1b[0m"

    def format(self, record: logging.LogRecord) -> str:
        """Format the specified record as text with color codes."""
        return (
            self.LEVEL2COLORCODE.get(record.levelno, self.UNKNOWN_LEVEL_COLOR)
            + super().format(record)
            + self.RESET_CODE
        )


class ColorGlogFormatter(ColorFormatterMixin, GlogFormatter):
    """Colorized formatter that matches Google's glog format."""


def disable_child_propagation(logger_name: str, /) -> None:
    """Disable propagation for a named logger to avoid duplicate logs."""
    logging.getLogger(logger_name).propagate = False


def setup_stderr_logging(
    logging_level: int | None = None,
    /,
    *,
    color: bool = True,
    clear_handlers: bool = True,
    use_utc: bool = False,
    log_file: str | None = None,
    max_bytes: int = 10_000_000,  # 10MB
    backup_count: int = 5,
) -> logging.Logger:
    """Set up logging configuration for stderr and optional file logging.

    This function configures the root logger, which affects all loggers
    in the application that propagate to it (the default behavior). To avoid
    duplicate logging or conflicts with other handlers, you may want to
    disable propagation on child loggers using disable_child_propagation().

    IMPORTANT: Call this function once at application startup (e.g., in
    main() or __main__ block), NOT at module import time, to avoid issues
    with handler accumulation or import-time side effects.

    Color Handling:
        Colors are automatically applied when stderr is a TTY (terminal) and
        disabled when redirected to a file or pipe. This ensures log files
        remain clean without ANSI escape sequences (e.g., no \\x1b[36m codes).
        File logging always uses plain text regardless of the color parameter.

    If sys.stderr is unavailable or closed (e.g., in daemonized processes
    or when stderr is explicitly closed) and no log_file is specified, this
    function falls back to a NullHandler. If log_file is specified, logs
    are written to the file with rotation, regardless of stderr availability.

    File handlers are not explicitly closed by this function, as they are
    managed by the logging system and closed when the logger is garbage-collected
    or the process exits. For long-running applications restarting logging,
    explicitly close handlers using logger.handlers[i].close().

    Environment Variables:
        LOG_LEVEL: Set logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
                   Overrides logging_level parameter if not explicitly set.
                   Invalid values default to INFO with a warning.
        LOG_COLOR: Control color output for stderr (1/true/yes or 0/false/no).
                   Overrides color parameter.
                   Invalid values use the color parameter default.

    Args:
        logging_level: Logging level (e.g., logging.DEBUG, logging.INFO).
            If None, uses LOG_LEVEL environment variable or defaults to INFO.
        color: If True, use colorized output when stderr is a TTY (terminal).
            Automatically disabled when output is redirected to files or pipes,
            preventing ANSI escape sequences in log files.
            Can be overridden by LOG_COLOR environment variable.
            File logging always uses plain text regardless of this setting.
        clear_handlers: If True, remove existing handlers from the root
            logger before adding new ones.
        use_utc: If True, timestamps are in UTC; otherwise in local time.
        log_file: If specified, write logs to this file with rotation.
            Uses RotatingFileHandler with max_bytes and backup_count.
        max_bytes: Maximum size of each log file before rotation (default: 10MB).
        backup_count: Number of backup log files to keep (default: 5).

    Returns:
        The root logger configured for stderr and/or file output, or with a
        NullHandler if neither is available.

    Example:
        if __name__ == "__main__":
            setup_stderr_logging(
                logging.DEBUG,
                color=True,
                use_utc=False,
                log_file="app.log"
            )
            log = logging.getLogger(__name__)
            log.info("Application started")
            disable_child_propagation("myapp.noisy_module")
    """
    root_logger: logging.Logger = logging.getLogger()
    handler_added: bool = False

    if logging_level is None:
        log_level_name: str = os.getenv("LOG_LEVEL", "INFO").upper()
        logging_level = getattr(logging, log_level_name, None)
        if logging_level is None:
            _safe_stderr_write(
                f"Warning: Invalid LOG_LEVEL '{log_level_name}', defaulting to INFO\n"
            )
            logging_level = logging.INFO
    root_logger.setLevel(logging_level)

    if clear_handlers:
        root_logger.handlers.clear()
    elif root_logger.handlers:
        _safe_stderr_write(
            "Warning: Adding new handlers without clearing existing ones may cause duplicate logs.\n"
        )

    if log_file:
        if not isinstance(log_file, str) or not log_file.strip():
            _safe_stderr_write(
                f"Warning: Invalid log_file '{log_file}', must be a non-empty string\n"
            )
        else:
            try:
                file_handler: logging.handlers.RotatingFileHandler = (
                    logging.handlers.RotatingFileHandler(
                        log_file, maxBytes=max_bytes, backupCount=backup_count
                    )
                )
                file_handler.addFilter(RotationErrorFilter())
                file_handler.setFormatter(GlogFormatter(use_utc=use_utc))
                root_logger.addHandler(file_handler)
                handler_added = True
            except OSError as e:
                _safe_stderr_write(
                    f"Warning: Failed to create log file '{log_file}': {e}\n"
                )

    stderr_available: bool = True
    if sys.stderr is None:
        stderr_available = False
    else:
        try:
            sys.stderr.fileno()
        except (AttributeError, ValueError, OSError):
            stderr_available = False

    if stderr_available:
        handler: logging.StreamHandler = logging.StreamHandler(sys.stderr)
        is_tty: bool = False
        try:
            is_tty = sys.stderr.isatty()
        except (AttributeError, ValueError, OSError):
            is_tty = False

        use_color: bool = color
        if "LOG_COLOR" in os.environ:
            log_color: str = os.getenv("LOG_COLOR", "").lower()
            if log_color in ("1", "true", "yes"):
                use_color = True
            elif log_color in ("0", "false", "no"):
                use_color = False
            else:
                _safe_stderr_write(
                    f"Warning: Invalid LOG_COLOR '{log_color}', using default color={color}\n"
                )

        formatter: GlogFormatter = (
            ColorGlogFormatter(use_utc=use_utc)
            if use_color and is_tty
            else GlogFormatter(use_utc=use_utc)
        )
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
        handler_added = True

    if not handler_added:
        root_logger.addHandler(logging.NullHandler())

    return root_logger
