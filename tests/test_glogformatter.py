"""Tests for GlogFormatter class."""

import datetime
import io
import logging
import os
import re
import threading
import time
import unittest

from glogformat import GlogFormatter


class TestGlogFormatter(unittest.TestCase):
    """Test cases for GlogFormatter."""

    def setUp(self):
        """Set up test fixtures."""
        self.formatter = GlogFormatter()
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)

        # Create a string stream handler for capturing output
        self.stream = io.StringIO()
        self.handler = logging.StreamHandler(self.stream)
        self.handler.setFormatter(self.formatter)
        self.logger.addHandler(self.handler)
        self.logger.propagate = False

    def tearDown(self):
        """Clean up test fixtures."""
        self.logger.removeHandler(self.handler)
        self.handler.close()

    def test_basic_format(self):
        """Test that formatter produces glog format output."""
        self.logger.info("Test message")
        output = self.stream.getvalue()

        # Format: L<YYYYMMDD HH:MM:SS.uuuuuu> <PID> <TID> <filename>:<line>] <message>
        pattern = r"^I\d{8} \d{2}:\d{2}:\d{2}\.\d{6} \d+ \d+ .+:\d+\] Test message\n$"
        self.assertRegex(output, pattern)

    def test_log_levels(self):
        """Test that all log levels are formatted correctly."""
        test_cases = [
            (logging.DEBUG, "D"),
            (logging.INFO, "I"),
            (logging.WARNING, "W"),
            (logging.ERROR, "E"),
            (logging.CRITICAL, "C"),
        ]

        for level, expected_prefix in test_cases:
            with self.subTest(level=level):
                self.stream.truncate(0)
                self.stream.seek(0)
                self.logger.log(
                    level, f"Message at {logging.getLevelName(level)}"
                )
                output = self.stream.getvalue()
                self.assertTrue(output.startswith(expected_prefix))

    def test_microsecond_precision(self):
        """Test that timestamps include microseconds."""
        self.logger.info("Test microseconds")
        output = self.stream.getvalue()

        # Check for microseconds (6 digits after the decimal point)
        self.assertRegex(output, r"\d{2}:\d{2}:\d{2}\.\d{6}")

    def test_process_and_thread_ids(self):
        """Test that process and thread IDs are included."""
        self.logger.info("Test IDs")
        output = self.stream.getvalue()

        # Extract PID and TID from output
        match = re.search(
            r"I\d{8} \d{2}:\d{2}:\d{2}\.\d{6} (\d+) (\d+)", output
        )
        self.assertIsNotNone(match)

        pid = int(match.group(1))
        tid = int(match.group(2))

        self.assertEqual(pid, os.getpid())
        self.assertGreater(tid, 0)

    def test_filename_and_lineno(self):
        """Test that filename and line number are included."""
        self.logger.info("Test location")
        output = self.stream.getvalue()

        # Should contain filename:lineno
        self.assertRegex(output, r"test_glogformatter\.py:\d+\]")

    def test_multiline_message(self):
        """Test formatting of multiline messages."""
        message = "Line 1\nLine 2\nLine 3"
        self.logger.info(message)
        output = self.stream.getvalue()

        # The message should be preserved
        self.assertIn("Line 1\nLine 2\nLine 3", output)

    def test_utc_timestamps(self):
        """Test UTC timestamp mode."""
        utc_formatter = GlogFormatter(use_utc=True)
        self.handler.setFormatter(utc_formatter)

        before_utc = datetime.datetime.now(datetime.timezone.utc)
        self.logger.info("UTC test")
        after_utc = datetime.datetime.now(datetime.timezone.utc)

        output = self.stream.getvalue()

        # Extract timestamp
        match = re.search(r"I(\d{8}) (\d{2}):(\d{2}):(\d{2})\.(\d{6})", output)
        self.assertIsNotNone(match)

        date_str = match.group(1)
        hour = int(match.group(2))
        minute = int(match.group(3))
        second = int(match.group(4))

        # Parse date
        year = int(date_str[:4])
        month = int(date_str[4:6])
        day = int(date_str[6:8])

        # Verify it's close to UTC time
        log_dt = datetime.datetime(
            year,
            month,
            day,
            hour,
            minute,
            second,
            tzinfo=datetime.timezone.utc,
        )

        self.assertGreaterEqual(log_dt, before_utc.replace(microsecond=0))
        self.assertLessEqual(
            log_dt,
            after_utc.replace(microsecond=0) + datetime.timedelta(seconds=1),
        )

    def test_local_timestamps(self):
        """Test local timestamp mode (default)."""
        local_formatter = GlogFormatter(use_utc=False)
        self.handler.setFormatter(local_formatter)

        before_local = datetime.datetime.now()
        self.logger.info("Local test")
        after_local = datetime.datetime.now()

        output = self.stream.getvalue()

        # Extract timestamp
        match = re.search(r"I(\d{8}) (\d{2}):(\d{2}):(\d{2})\.(\d{6})", output)
        self.assertIsNotNone(match)

        date_str = match.group(1)
        hour = int(match.group(2))
        minute = int(match.group(3))
        second = int(match.group(4))
        microsecond = int(match.group(5))

        # Parse the logged timestamp
        log_dt = datetime.datetime.strptime(date_str, "%Y%m%d").replace(
            hour=hour, minute=minute, second=second, microsecond=microsecond
        )

        # Should be within a reasonable time window (allowing for slow systems)
        self.assertGreaterEqual(
            log_dt, before_local - datetime.timedelta(seconds=1)
        )
        self.assertLessEqual(
            log_dt, after_local + datetime.timedelta(seconds=1)
        )

    def test_invalid_timestamp_warning(self):
        """Test handling of invalid timestamps."""
        # Create a log record with an invalid timestamp
        record = logging.LogRecord(
            name=__name__,
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="Test",
            args=(),
            exc_info=None,
        )
        # Set an invalid timestamp (too large for datetime)
        record.created = 1e20

        # Should not raise exception, should return fallback
        result = self.formatter.format(record)
        self.assertIsNotNone(result)
        self.assertIn("Test", result)

    def test_thread_safety_of_warnings(self):
        """Test that timestamp warnings are shown only once across threads."""
        warning_count = [0]
        original_stderr_write = __import__("glogformat")._safe_stderr_write

        def mock_stderr_write(msg):
            if "Warning: GlogFormatter failed" in msg:
                warning_count[0] += 1

        # Monkey patch
        import glogformat

        glogformat._safe_stderr_write = mock_stderr_write

        try:
            formatter = GlogFormatter()

            def log_invalid():
                record = logging.LogRecord(
                    name=__name__,
                    level=logging.INFO,
                    pathname=__file__,
                    lineno=1,
                    msg="Test",
                    args=(),
                    exc_info=None,
                )
                record.created = 1e20
                formatter.format(record)

            # Create multiple threads that all trigger the warning
            threads = [threading.Thread(target=log_invalid) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # Should only see one warning despite multiple threads
            self.assertEqual(warning_count[0], 1)
        finally:
            glogformat._safe_stderr_write = original_stderr_write

    def test_custom_format_not_overridden(self):
        """Test that custom format can be provided."""
        custom_formatter = GlogFormatter(fmt="CUSTOM: %(message)s")
        self.handler.setFormatter(custom_formatter)

        self.logger.info("Test custom")
        output = self.stream.getvalue()

        self.assertIn("CUSTOM: Test custom", output)

    def test_message_with_special_characters(self):
        """Test messages with special characters."""
        special_chars = "Test with special: !@#$%^&*()_+-=[]{}|;':\",./<>?"
        self.logger.info(special_chars)
        output = self.stream.getvalue()

        self.assertIn(special_chars, output)

    def test_empty_message(self):
        """Test logging empty message."""
        self.logger.info("")
        output = self.stream.getvalue()

        # Should still have the glog prefix and structure
        self.assertRegex(output, r"^I\d{8} \d{2}:\d{2}:\d{2}\.\d{6}")


if __name__ == "__main__":
    unittest.main()
