#!/usr/bin/env python3
"""Demo application for glogformat.

This script demonstrates the glog-style logging formatter with:
- Multiple log levels (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- Exception logging with tracebacks
- Automatic color detection (colors in terminal, plain text when redirected)

Usage:
    python demo_app.py              # Run with colored output
    python demo_app.py > output.log # Redirect to file (no ANSI codes)
    python demo_app.py --version    # Show version
"""

import argparse
import logging

from glogformat import setup_stderr_logging

# Set up logging before any other imports
setup_stderr_logging(logging.DEBUG)
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
    args = parse_arguments()

    # Nice logging in glog format with color!
    log.info("Starting!")
    log.debug("I'll divide by 0.")

    log.warning("Don't do it!")
    try:
        result = 1 // 0
    except ZeroDivisionError:
        log.exception("You tried to divide by 0!", exc_info=True)
        log.critical("Exiting soon!")

    log.info("Done!")


if __name__ == "__main__":
    main()
