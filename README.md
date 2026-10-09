# glogformat

A Python logging formatter implementing Google's glog format with
microsecond precision and terminal color support.

## Features

- **glog-compatible format**: Matches Google's glog format
- **Microsecond precision**: Timestamps include microseconds for precise timing
- **Automatic color detection**: Colors in terminal (TTY), plain text when
  redirected to files (no ANSI escape sequences in logs!)
- **UTC or local time**: Configurable timezone for timestamps
- **File logging**: Optional rotating file handler with error handling
- **Thread-safe**: Proper locking for multi-threaded applications (including
  GIL-free Python 3.13+)
- **Robust**: Handles edge cases like missing stderr or invalid timestamps

## Installation

```bash
pip install glogformat
```

## Quick Demo

Try the included demo application to see glogformat in action:

```bash
# Clone or download the demo
curl -O https://raw.githubusercontent.com/aleksa/glogformat/master/demo_app.py

# Run it (colored output in terminal)
python demo_app.py

# Or redirect to see plain text (no ANSI codes)
python demo_app.py &> output.log
cat output.log
```

## Quick Start

```python
import argparse
import logging

from glogformat import setup_stderr_logging

log = logging.getLogger(__name__)


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Example application using glogformat"
    )
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 1.0.0",
        help="Show program's version number and exit.",
    )
    return parser.parse_args()


def main() -> None:
    """Main function."""
    # Configure logging once at startup, not at import time.
    setup_stderr_logging(logging.DEBUG)
    parse_arguments()

    # Nice logging in glog format with color!
    log.info("Starting!")
    log.debug("I'll divide by 0.")

    log.warning("Don't do it!")
    try:
        result = 1 // 0
        log.info("Result: %d", result)
    except ZeroDivisionError:
        log.exception("You tried to divide by 0!")
        log.critical("Exiting soon!")

    log.info("Done!")


if __name__ == "__main__":
    main()
```

Output (with colors in terminal):

![Demo output with colors](https://raw.githubusercontent.com/aleksa/glogformat/master/demo_app_screenshot.png)

Format: `L<YYYYMMDD HH:MM:SS.uuuuuu> <PID> <TID> <filename>:<line>] <message>`

- **L**: Log level (D=DEBUG, I=INFO, W=WARNING, E=ERROR, C=CRITICAL)
- **YYYYMMDD**: Date
- **HH:MM:SS.uuuuuu**: Time with microseconds
- **PID**: Process ID
- **TID**: Thread ID
- **filename:line**: Source location

## Multi-Module Applications

For applications with multiple files and modules, set up logging **once** at
your application's entry point, then use `logging.getLogger(__name__)` in
each module.

### Project Structure

```
myapp/
├── main.py          # Entry point with logging setup
├── database.py      # Database module
└── api.py          # API module
```

### main.py (Entry Point)

```python
import logging

from glogformat import setup_stderr_logging

from myapp import api
from myapp import database

# Set up logging ONCE at application startup
setup_stderr_logging(logging.INFO)
log = logging.getLogger(__name__)


def main() -> None:
    """Main application entry point."""
    log.info("Application starting")

    database.connect()
    api.start_server()

    log.info("Application ready")


if __name__ == "__main__":
    main()
```

### database.py (Module)

```python
import logging

# Get logger for this module - inherits glog format from root
log = logging.getLogger(__name__)


def connect() -> None:
    """Connect to database."""
    log.info("Connecting to database")
    log.debug("Using connection pool size: 10")
    log.info("Database connected successfully")
```

### api.py (Module)

```python
import logging

# Get logger for this module - inherits glog format from root
log = logging.getLogger(__name__)


def start_server() -> None:
    """Start API server."""
    log.info("Starting API server on port 8080")
    log.debug("Loading middleware")
    log.info("API server started")
```

### Output

All modules automatically use the glog format:

```text
I20250117 14:32:15.123456 12345 67890 main.py:15] Application starting
I20250117 14:32:15.123489 12345 67890 database.py:10] Connecting to database
D20250117 14:32:15.123512 12345 67890 database.py:11] Using connection pool size: 10
I20250117 14:32:15.123535 12345 67890 database.py:12] Database connected successfully
I20250117 14:32:15.123567 12345 67890 api.py:10] Starting API server on port 8080
D20250117 14:32:15.123589 12345 67890 api.py:11] Loading middleware
I20250117 14:32:15.123612 12345 67890 api.py:12] API server started
I20250117 14:32:15.123634 12345 67890 main.py:20] Application ready
```

### Key Points

1. **Setup once**: Call `setup_stderr_logging()` only at your application's
   entry point
2. **Use `__name__`**: Each module should use `logging.getLogger(__name__)`
   to get its logger
3. **Automatic propagation**: All loggers inherit the glog format from the
   root logger
4. **Module identification**: The filename in the log output shows which
   module logged the message

### Third-Party Libraries

Third-party libraries automatically inherit the glog format through Python's
logging propagation. No special configuration needed!

```python
import logging
import requests  # Uses urllib3 internally

from glogformat import setup_stderr_logging

setup_stderr_logging(logging.DEBUG)
log = logging.getLogger(__name__)

# All logs (including from requests/urllib3) use glog format
log.info("Making HTTP request")
response = requests.get("https://api.example.com/data")
log.info("Request complete")
```

Output shows both your logs and third-party logs in glog format:

```text
I20250117 14:32:15.123456 12345 67890 main.py:10] Making HTTP request
D20250117 14:32:15.123489 12345 67890 connectionpool.py:815] Starting new HTTPS connection
D20250117 14:32:15.234567 12345 67890 connectionpool.py:945] https://api.example.com:443 "GET /data HTTP/1.1" 200 1234
I20250117 14:32:15.234890 12345 67890 main.py:12] Request complete
```

**Isolating Noisy Libraries**

If a third-party logger has its own handlers and also propagates to the root
logger, disable propagation to avoid duplicate output:

```python
from glogformat import disable_child_propagation
from glogformat import silence_logger
from glogformat import setup_stderr_logging

setup_stderr_logging(logging.INFO)

# Keep these loggers from also flowing through the root logger
disable_child_propagation("urllib3.connectionpool")
disable_child_propagation("asyncio")
```

To suppress a noisy logger entirely, set its level above `CRITICAL`:

```python
silence_logger("urllib3.connectionpool")
```

## Advanced Usage

### Named Logger Setup

Use `setup_logger()` when you want glog formatting on one logger without
modifying the root logger:

```python
import logging

from glogformat import setup_logger

log = setup_logger("myapp", logging.DEBUG)
log.info("Only the myapp logger was configured")
```

By default, `setup_logger()` disables propagation for that logger so records
are not duplicated by root handlers. Pass `propagate=True` to keep normal
logging propagation.

### Automatic Color Detection

Colors are automatically enabled for TTY (terminal) output and disabled when
redirected to files. This prevents ANSI escape sequences from polluting your
log files.

```bash
# Terminal output - colorized
python myapp.py

# File redirection - plain text, no ANSI codes (logs go to stderr)
python myapp.py 2> output.log
python myapp.py 2>&1 | tee output.log
```

**Terminal output** (colorized):
```text
[Colors shown in terminal with ANSI codes]
I20250117 14:32:15.123456 12345 67890 main.py:10] Starting!
```

**File output** (plain text):
```text
I20250117 14:32:15.123456 12345 67890 main.py:10] Starting!
```

The file contains clean, readable text without any `\x1b[36m` or `\x1b[0m`
sequences.

**Force color on/off:**

```python
from glogformat import setup_stderr_logging

# Disable colors (even in terminal)
setup_stderr_logging(logging.INFO, color=False)

# Override with environment variable
# LOG_COLOR=0 python myapp.py    # Force off
# LOG_COLOR=1 python myapp.py    # On in a terminal, even with color=False
# NO_COLOR=1 python myapp.py     # Disable color using the common convention
# FORCE_COLOR=1 python myapp.py  # Enable color even when piped (e.g. in CI)
```

### File Logging with Rotation

```python
from glogformat import setup_stderr_logging
import logging

# Log to both stderr and rotating file
setup_stderr_logging(
    logging.DEBUG,
    color=True,
    log_file="app.log",
    max_bytes=10_000_000,  # 10MB
    backup_count=5
)
```

`log_file` also accepts path-like objects such as `pathlib.Path`.

### UTC Timestamps

```python
# Use UTC timestamps for distributed systems
setup_stderr_logging(logging.INFO, use_utc=True)
```

### Environment Variables

Control logging via environment variables:

```bash
# Set log level
export LOG_LEVEL=DEBUG

# Control color output
export LOG_COLOR=1  # or 0 to disable
export NO_COLOR=1  # disable color if LOG_COLOR is unset
export FORCE_COLOR=1  # enable color, even when not a TTY, if LOG_COLOR and NO_COLOR are unset
```

Precedence is `LOG_COLOR`, then `NO_COLOR`, then `FORCE_COLOR`, then the
`color` argument. `LOG_COLOR` comes first for backwards compatibility, and
`NO_COLOR` beats `FORCE_COLOR` as in CPython's own color handling.
`LOG_COLOR=1` and `color=True` only color TTY output; `FORCE_COLOR` (any
non-empty value except `0`, `false` or `no`) also colors piped output.

### Disable Child Logger Propagation

```python
from glogformat import disable_child_propagation
from glogformat import setup_stderr_logging
import logging

setup_stderr_logging(logging.INFO)

# Prevent duplicate output from a logger that has its own handlers
disable_child_propagation("urllib3.connectionpool")
```

## Format Specification

```text
L<YYYYMMDD HH:MM:SS.uuuuuu> <PID> <TID> <filename>:<line>] <message>
```

Where:

- `L`: Log level (D=DEBUG, I=INFO, W=WARNING, E=ERROR, C=CRITICAL)
- `YYYYMMDD`: Date
- `HH:MM:SS.uuuuuu`: Time with microseconds
- `PID`: Process ID
- `TID`: Thread ID (no padding, supports large IDs)
- `filename:line`: Source location
- `message`: Log message

## API Reference

Parameters before `/` are positional-only, and parameters after `*` are
keyword-only.

### `GlogFormatter`

Formatter that produces glog-style records with microsecond timestamps.
Pass `use_utc=True` to use UTC timestamps.

### `ColorGlogFormatter`

`GlogFormatter` variant that wraps formatted records in ANSI color codes.
`setup_stderr_logging()` and `setup_logger()` choose this automatically when
color is enabled and stderr is a TTY, or when `FORCE_COLOR` is set.

### `setup_stderr_logging(logging_level=None, /, *, color=True, clear_handlers=True, use_utc=False, log_file=None, max_bytes=10_000_000, backup_count=5)`

Configures the root logger for stderr and optional rotating file logging.
`logging_level` can be an integer level, a level name string, or a numeric
string such as `"10"`. If unset, `LOG_LEVEL` is used (same formats), defaulting
to `INFO`.

### `setup_logger(logger_name, logging_level=None, /, *, color=True, clear_handlers=True, propagate=False, use_utc=False, log_file=None, max_bytes=10_000_000, backup_count=5)`

Configures a named logger without changing the root logger. Propagation is
disabled by default to avoid duplicate records when root logging is already
configured. Give it a `log_file` that no other configured logger writes to:
separate rotating handlers on one file don't coordinate rotation.

### `disable_child_propagation(logger_name, /)`

Sets `propagate=False` on a named logger. This prevents duplicate output when
that logger has its own handlers, but it does not silence child loggers.

### `silence_logger(logger_name, /)`

Sets the named logger's level above `CRITICAL`. This also silences its
descendants that are left at the default `NOTSET` level, so
`silence_logger("urllib3")` covers `urllib3.connectionpool`. A descendant with
its own explicit level still emits records.

## Requirements

- Python 3.10+
- Linux or macOS (Windows untested)

## License

MIT License - see LICENSE file for details.

## Author

Maintained by Aleksa.
