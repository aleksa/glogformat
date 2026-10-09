"""Google glog-style logging formatter for Python.

This module provides formatters that match Google's glog format with
microsecond precision, automatic color detection for terminals, and robust
handling of edge cases like unavailable stderr or daemonized processes.

Key features:
- Colors enabled for TTY output, disabled when redirected to files (unless
  FORCE_COLOR is set)
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
import time
from typing import Any
from typing import Iterable
from typing import Literal
from typing import Mapping
from typing import TYPE_CHECKING

__all__ = [
    "GlogFormatter",
    "ColorGlogFormatter",
    "setup_logger",
    "setup_stderr_logging",
    "disable_child_propagation",
    "silence_logger",
]

LogLevel = int | str


def _safe_stderr_write(message: str, /) -> None:
    """Write a message to stderr, ignoring any exceptions."""
    try:
        if sys.stderr:
            sys.stderr.write(message)
            sys.stderr.flush()
    except Exception:  # pylint: disable=broad-exception-caught
        pass


def _close_handlers(
    logger: logging.Logger,
    handlers: Iterable[logging.Handler] | None = None,
    /,
) -> None:
    """Remove and close selected handlers from a logger.

    Args:
        logger: Logger to remove handlers from.
        handlers: Handlers to remove and close. If None, all handlers currently
            attached to logger are removed and closed.
    """
    if handlers is None:
        handlers = logger.handlers[:]

    for handler in handlers:
        logger.removeHandler(handler)
        handler.close()


def _level_from_name(level_name: str, /) -> int | None:
    """Look up a registered logging level by name.

    Module attributes that aren't levels, such as BASIC_FORMAT, are rejected.
    On Python 3.11+ custom levels added with logging.addLevelName() are also
    accepted.

    Args:
        level_name: Level name, e.g. "DEBUG".

    Returns:
        The numeric level, or None if no level has that name.
    """
    if sys.version_info >= (3, 11):
        # Pylint running on 3.10 doesn't honor the version guard.
        mapping = logging.getLevelNamesMapping()  # pylint: disable=no-member
        return mapping.get(level_name)
    level_value: object = getattr(logging, level_name, None)
    return level_value if isinstance(level_value, int) else None


def _parse_level_string(level_text: str, /) -> int | None:
    """Parse a level given as a name ("debug") or a number ("10").

    Args:
        level_text: Level name in any case, or a non-negative integer.

    Returns:
        The numeric level, or None if the text is neither.
    """
    level_text = level_text.strip()
    # isdecimal() rather than isdigit(): it rejects "²", which int() can't parse.
    if level_text.isdecimal():
        return int(level_text)
    return _level_from_name(level_text.upper())


def _coerce_logging_level(logging_level: LogLevel | None, /) -> int:
    """Resolve and validate a logging level, falling back to INFO.

    Args:
        logging_level: Explicit logging level. Strings are level names such
            as "DEBUG" or numbers such as "10". If None, LOG_LEVEL is used.

    Returns:
        A valid integer logging level.
    """
    if logging_level is None:
        env_level: str = os.getenv("LOG_LEVEL", "INFO")
        level_value = _parse_level_string(env_level)
        if level_value is not None:
            return level_value
        _safe_stderr_write(
            f"Warning: Invalid LOG_LEVEL '{env_level}', defaulting to INFO\n"
        )
        return logging.INFO

    # bool is an int subclass, but True/False are never intended as levels.
    if isinstance(logging_level, int) and not isinstance(logging_level, bool):
        return logging_level

    if isinstance(logging_level, str):
        level_value = _parse_level_string(logging_level)
        if level_value is not None:
            return level_value

    _safe_stderr_write(
        f"Warning: Invalid logging_level '{logging_level}', defaulting to INFO\n"
    )
    return logging.INFO


def _resolve_color(color: bool, is_tty: bool, /) -> bool:
    """Decide whether stderr output should be colorized.

    Precedence: LOG_COLOR, then NO_COLOR, then FORCE_COLOR, then the color
    argument. NO_COLOR beating FORCE_COLOR matches CPython's own color
    handling. LOG_COLOR and the color argument only apply to TTYs, while
    FORCE_COLOR also colors non-TTY output (e.g. CI logs).

    Args:
        color: Default color setting.
        is_tty: Whether stderr is a TTY.

    Returns:
        True if stderr output should be colorized; otherwise False.
    """
    if "LOG_COLOR" in os.environ:
        log_color: str = os.getenv("LOG_COLOR", "").lower()
        if log_color in ("1", "true", "yes"):
            return is_tty
        if log_color in ("0", "false", "no"):
            return False
        _safe_stderr_write(
            f"Warning: Invalid LOG_COLOR '{log_color}', ignoring\n"
        )

    if os.getenv("NO_COLOR"):
        return False
    if os.getenv("FORCE_COLOR", "").lower() not in ("", "0", "false", "no"):
        return True
    return color and is_tty


def _create_file_handler(
    log_file: str | os.PathLike[str],
    /,
    *,
    max_bytes: int,
    backup_count: int,
    use_utc: bool,
) -> logging.handlers.RotatingFileHandler | None:
    """Create a configured rotating file handler.

    Args:
        log_file: File path for log output.
        max_bytes: Maximum size of each log file before rotation.
        backup_count: Number of backup log files to keep.
        use_utc: If True, use UTC timestamps.

    Returns:
        A configured file handler, or None if the file path is invalid or the
        handler could not be created.
    """
    if isinstance(log_file, os.PathLike):
        log_file = os.fspath(log_file)

    if not isinstance(log_file, str) or not log_file.strip():
        _safe_stderr_write(
            f"Warning: Invalid log_file '{log_file}', must be a non-empty path\n"
        )
        return None

    try:
        file_handler: logging.handlers.RotatingFileHandler = (
            _WarningRotatingFileHandler(
                log_file, max_bytes=max_bytes, backup_count=backup_count
            )
        )
        file_handler.setFormatter(GlogFormatter(use_utc=use_utc))
        return file_handler
    except OSError as e:
        _safe_stderr_write(
            f"Warning: Failed to create log file '{log_file}': {e}\n"
        )
        return None


def _create_stderr_handler(
    *,
    color: bool,
    use_utc: bool,
) -> logging.StreamHandler | None:
    """Create a configured stderr handler if stderr is available.

    Args:
        color: If True, use colorized output when stderr is a TTY.
        use_utc: If True, use UTC timestamps.

    Returns:
        A configured stderr handler, or None if stderr is unavailable.
    """
    stderr_available: bool = (
        sys.stderr is not None
        and hasattr(sys.stderr, "write")
        and getattr(sys.stderr, "closed", False) is not True
    )
    if not stderr_available:
        return None

    handler: logging.StreamHandler = logging.StreamHandler(sys.stderr)
    is_tty: bool = False
    try:
        is_tty = sys.stderr.isatty()
    except (AttributeError, ValueError, OSError):
        is_tty = False

    formatter: GlogFormatter = (
        ColorGlogFormatter(use_utc=use_utc)
        if _resolve_color(color, is_tty)
        else GlogFormatter(use_utc=use_utc)
    )
    handler.setFormatter(formatter)
    return handler


def _configure_logger(
    logger: logging.Logger,
    logging_level: LogLevel | None,
    /,
    *,
    color: bool,
    clear_handlers: bool,
    use_utc: bool,
    log_file: str | os.PathLike[str] | None,
    max_bytes: int,
    backup_count: int,
) -> logging.Logger:
    """Configure a logger with stderr and optional file handlers.

    Args:
        logger: Logger to configure.
        logging_level: Logging level or None to use environment/defaults.
        color: If True, use colorized stderr output when possible.
        clear_handlers: If True, remove and close existing logger handlers.
        use_utc: If True, use UTC timestamps.
        log_file: Optional rotating log file path.
        max_bytes: Maximum size of each log file before rotation.
        backup_count: Number of backup log files to keep.

    Returns:
        The configured logger.
    """
    logger.setLevel(_coerce_logging_level(logging_level))

    if clear_handlers:
        _close_handlers(logger)
    elif logger.handlers:
        _safe_stderr_write(
            "Warning: Adding new handlers without clearing existing ones may cause duplicate logs.\n"
        )

    handler_added: bool = False
    if log_file:
        file_handler = _create_file_handler(
            log_file,
            max_bytes=max_bytes,
            backup_count=backup_count,
            use_utc=use_utc,
        )
        if file_handler is not None:
            logger.addHandler(file_handler)
            handler_added = True

    stderr_handler = _create_stderr_handler(color=color, use_utc=use_utc)
    if stderr_handler is not None:
        logger.addHandler(stderr_handler)
        handler_added = True

    if not handler_added:
        logger.addHandler(logging.NullHandler())

    return logger


class _WarningRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """Rotating file handler that emits one warning for handler failures.

    ``RotatingFileHandler`` reports rollover and write failures via
    ``handleError``. Emitting the warning there avoids confusing application
    exceptions logged with ``logger.exception()`` for rotation failures.
    """

    def __init__(
        self,
        filename: str | os.PathLike[str],
        *,
        max_bytes: int = 0,
        backup_count: int = 0,
    ) -> None:
        """Initialize the warning file handler.

        Args:
            filename: File path for log output.
            max_bytes: Maximum size of each log file before rotation. Zero
                disables rotation.
            backup_count: Number of backup log files to keep.
        """
        super().__init__(
            filename, maxBytes=max_bytes, backupCount=backup_count
        )
        self._warning_shown: bool = False

    def handleError(self, record: logging.LogRecord) -> None:
        """Handle a file handler error and emit one warning.

        Only OSErrors (write or rollover failures) count toward the warning.
        Other errors, such as a record whose args don't match its format
        string, are the caller's bug and must not use up the one-shot warning.
        The record is deliberately not formatted here: for those errors
        record.getMessage() raises again.

        No extra lock is needed: Handler.handle() holds the handler's lock
        while emit() runs, and emit() is the only caller of this method.

        Args:
            record: Log record being handled when the file handler failed.
        """
        error: BaseException | None = sys.exc_info()[1]
        if isinstance(error, OSError) and not self._warning_shown:
            self._warning_shown = True
            _safe_stderr_write(
                f"Warning: Log file handler failed for {self.baseFilename}: "
                f"{type(error).__name__}: {error}\n"
            )
        super().handleError(record)


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
        if use_utc:
            # Used by logging.Formatter.formatTime(), which this class falls
            # back to when datefmt is empty or timestamp formatting fails.
            self.converter = time.gmtime
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

    This mixin always adds color codes. setup_stderr_logging() and
    setup_logger() only select it when stderr is a TTY or FORCE_COLOR is set,
    so log files and piped output stay free of ANSI escape sequences by
    default. The color codes are standard ANSI sequences compatible
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
    """Disable propagation for a named logger to avoid duplicate logs.

    Args:
        logger_name: Name of the logger to update.
    """
    logging.getLogger(logger_name).propagate = False


def silence_logger(logger_name: str, /) -> None:
    """Suppress records from a named logger and its descendants.

    Descendant loggers left at the default NOTSET level inherit the
    suppressing level, so silencing "urllib3" also silences
    "urllib3.connectionpool". A descendant with its own explicit level still
    emits records.

    Args:
        logger_name: Name of the logger to silence.
    """
    logging.getLogger(logger_name).setLevel(logging.CRITICAL + 1)


def setup_stderr_logging(
    logging_level: LogLevel | None = None,
    /,
    *,
    color: bool = True,
    clear_handlers: bool = True,
    use_utc: bool = False,
    log_file: str | os.PathLike[str] | None = None,
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
        disabled when redirected to a file or pipe, unless FORCE_COLOR is
        set. This keeps redirected output free of ANSI escape sequences
        (e.g., no \\x1b[36m codes). File logging always uses plain text
        regardless of the color parameter or environment variables.

    If sys.stderr is unavailable or closed (e.g., in daemonized processes
    or when stderr is explicitly closed) and no log_file is specified, this
    function falls back to a NullHandler. If log_file is specified, logs
    are written to the file with rotation, regardless of stderr availability.

    When clear_handlers=True, existing root handlers are removed and closed
    before new handlers are added. Handlers added by this function are then
    managed by the logging system and closed when the process exits.

    Environment Variables:
        LOG_LEVEL: Set logging level by name (DEBUG, INFO, WARNING, ERROR,
                   CRITICAL) or number (e.g. 10).
                   Overrides logging_level parameter if not explicitly set.
                   Invalid values default to INFO with a warning.
        LOG_COLOR: Control color output for stderr (1/true/yes or 0/false/no).
                   Overrides color parameter and other color environment
                   variables; color still requires a TTY. Invalid values are
                   ignored with a warning.
        NO_COLOR: Any non-empty value disables color if LOG_COLOR is unset.
        FORCE_COLOR: Any non-empty value other than 0/false/no enables color,
                     even when stderr is not a TTY, if LOG_COLOR and NO_COLOR
                     are unset.

    Args:
        logging_level: Logging level (e.g., logging.DEBUG, logging.INFO, or
            "INFO"). If None, uses LOG_LEVEL environment variable or defaults
            to INFO.
        color: If True, use colorized output when stderr is a TTY (terminal).
            Automatically disabled when output is redirected to files or pipes,
            preventing ANSI escape sequences in log files, unless FORCE_COLOR
            is set. Can be overridden by LOG_COLOR, FORCE_COLOR, and NO_COLOR.
            File logging always uses plain text regardless of this setting.
        clear_handlers: If True, remove existing handlers from the root
            logger before adding new ones.
        use_utc: If True, timestamps are in UTC; otherwise in local time.
        log_file: If specified, write logs to this file with rotation.
            Accepts a string path or os.PathLike object. Uses
            RotatingFileHandler with max_bytes and backup_count.
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
    return _configure_logger(
        logging.getLogger(),
        logging_level,
        color=color,
        clear_handlers=clear_handlers,
        use_utc=use_utc,
        log_file=log_file,
        max_bytes=max_bytes,
        backup_count=backup_count,
    )


def setup_logger(
    logger_name: str,
    logging_level: LogLevel | None = None,
    /,
    *,
    color: bool = True,
    clear_handlers: bool = True,
    propagate: bool = False,
    use_utc: bool = False,
    log_file: str | os.PathLike[str] | None = None,
    max_bytes: int = 10_000_000,
    backup_count: int = 5,
) -> logging.Logger:
    """Set up stderr and optional file logging on a named logger.

    Unlike setup_stderr_logging(), this function does not configure the root
    logger. By default it disables propagation on the named logger so records
    are handled only by the handlers added here.

    Use a log_file that no other configured logger writes to. Each call
    creates its own rotating handler, and two handlers on the same file don't
    coordinate: after one rotates the file, the other keeps writing to the
    renamed backup.

    Args:
        logger_name: Name of the logger to configure.
        logging_level: Logging level (e.g., logging.DEBUG or "DEBUG"). If
            None, uses LOG_LEVEL environment variable or defaults to INFO.
        color: If True, use colorized output when stderr is a TTY.
        clear_handlers: If True, remove existing handlers from the logger
            before adding new ones.
        propagate: Propagation setting for the configured logger.
        use_utc: If True, timestamps are in UTC; otherwise in local time.
        log_file: If specified, write logs to this file with rotation.
        max_bytes: Maximum size of each log file before rotation.
        backup_count: Number of backup log files to keep.

    Returns:
        The configured named logger.
    """
    logger = logging.getLogger(logger_name)
    logger.propagate = propagate
    return _configure_logger(
        logger,
        logging_level,
        color=color,
        clear_handlers=clear_handlers,
        use_utc=use_utc,
        log_file=log_file,
        max_bytes=max_bytes,
        backup_count=backup_count,
    )
