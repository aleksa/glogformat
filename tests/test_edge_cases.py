"""Tests for edge cases and error handling."""

import contextlib
import glob
import io
import logging
import pathlib
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock
from unittest.mock import patch

import glogformat
from glogformat import RotationErrorFilter
from glogformat import _safe_stderr_write
from glogformat import setup_stderr_logging


class TestSafeStderrWrite(unittest.TestCase):
    """Test cases for _safe_stderr_write function."""

    def test_normal_write(self) -> None:
        """Test normal write to stderr."""
        output: io.StringIO = io.StringIO()

        with patch.object(sys, "stderr", output):
            _safe_stderr_write("Test message\n")

            self.assertEqual(output.getvalue(), "Test message\n")

    def test_none_stderr(self) -> None:
        """Test that function handles None stderr gracefully."""
        with patch.object(sys, "stderr", None):
            # Should not raise exception
            _safe_stderr_write("Test message\n")

    def test_closed_stderr(self) -> None:
        """Test that function handles closed stderr gracefully."""
        # Create a closed StringIO
        closed_stream: io.StringIO = io.StringIO()
        closed_stream.close()

        with patch.object(sys, "stderr", closed_stream):
            # Should not raise exception
            _safe_stderr_write("Test message\n")

    def test_stderr_write_exception(self) -> None:
        """Test that function handles write exceptions gracefully."""
        # Create mock that raises on write
        mock_stderr: Mock = Mock()
        mock_stderr.write.side_effect = IOError("Mock write error")

        with patch.object(sys, "stderr", mock_stderr):
            # Should not raise exception
            _safe_stderr_write("Test message\n")

    def test_stderr_flush_exception(self) -> None:
        """Test that function handles flush exceptions gracefully."""
        # Create mock that raises on flush
        mock_stderr: Mock = Mock()
        mock_stderr.flush.side_effect = IOError("Mock flush error")

        with patch.object(sys, "stderr", mock_stderr):
            # Should not raise exception
            _safe_stderr_write("Test message\n")


class TestRotationErrorFilter(unittest.TestCase):
    """Test cases for RotationErrorFilter."""

    def test_first_error_shows_warning(self) -> None:
        """Test that first error shows warning."""
        filter_obj: RotationErrorFilter = RotationErrorFilter()

        # Create a log record with exception
        record: logging.LogRecord = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="Rotation failed",
            args=(),
            exc_info=(ValueError, ValueError("Test error"), None),
        )

        with patch("glogformat._safe_stderr_write") as mock_write:
            result: bool = filter_obj.filter(record)

            # Should return True to allow the record
            self.assertTrue(result)
            # Should have written warning
            mock_write.assert_called_once()
            call_args: str = str(mock_write.call_args)
            self.assertIn("Warning: Log rotation failed", call_args)

    def test_subsequent_errors_no_warning(self) -> None:
        """Test that subsequent errors don't show warning."""
        filter_obj: RotationErrorFilter = RotationErrorFilter()

        # Create log records with exceptions
        record1: logging.LogRecord = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="First error",
            args=(),
            exc_info=(ValueError, ValueError("Test error 1"), None),
        )
        record2: logging.LogRecord = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="Second error",
            args=(),
            exc_info=(ValueError, ValueError("Test error 2"), None),
        )

        with patch("glogformat._safe_stderr_write") as mock_write:
            # First record should trigger warning
            filter_obj.filter(record1)
            self.assertEqual(mock_write.call_count, 1)

            # Second record should not trigger warning
            filter_obj.filter(record2)
            self.assertEqual(mock_write.call_count, 1)  # Still 1

    def test_record_without_exception(self) -> None:
        """Test filtering record without exception info."""
        filter_obj: RotationErrorFilter = RotationErrorFilter()

        # Create a log record without exception
        record: logging.LogRecord = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="Normal message",
            args=(),
            exc_info=None,
        )

        with patch("glogformat._safe_stderr_write") as mock_write:
            result: bool = filter_obj.filter(record)

            # Should return True to allow the record
            self.assertTrue(result)
            # Should not write warning
            mock_write.assert_not_called()

    def test_filter_always_returns_true(self) -> None:
        """Test that filter always returns True to allow records through."""
        filter_obj: RotationErrorFilter = RotationErrorFilter()

        # Test various scenarios
        test_cases: list[logging.LogRecord] = [
            # With exception
            logging.LogRecord(
                name="test",
                level=logging.ERROR,
                pathname=__file__,
                lineno=1,
                msg="Error",
                args=(),
                exc_info=(ValueError, ValueError("Error"), None),
            ),
            # Without exception
            logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname=__file__,
                lineno=1,
                msg="Info",
                args=(),
                exc_info=None,
            ),
        ]

        for record in test_cases:
            result: bool = filter_obj.filter(record)
            self.assertTrue(result)


class TestEdgeCasesIntegration(unittest.TestCase):
    """Integration tests for edge cases."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.original_handlers = logging.root.handlers[:]
        self.original_level = logging.root.level

    def tearDown(self) -> None:
        """Clean up test fixtures."""
        logging.root.handlers = self.original_handlers
        logging.root.level = self.original_level

    def test_large_thread_ids(self) -> None:
        """Test formatting with large thread IDs (Linux 64-bit)."""
        formatter: glogformat.GlogFormatter = glogformat.GlogFormatter()

        # Create a log record with a large thread ID
        record: logging.LogRecord = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="Test large TID",
            args=(),
            exc_info=None,
        )
        # Simulate large Linux thread ID
        record.thread = 140737354018816  # Typical large Linux TID

        result: str = formatter.format(record)

        # Should include the large thread ID without truncation
        self.assertIn(str(140737354018816), result)

    def test_very_long_messages(self) -> None:
        """Test formatting very long messages."""
        formatter: glogformat.GlogFormatter = glogformat.GlogFormatter()
        long_message: str = "A" * 10000

        record: logging.LogRecord = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg=long_message,
            args=(),
            exc_info=None,
        )

        result: str = formatter.format(record)

        # Should contain the full message
        self.assertIn(long_message, result)

    def test_unicode_messages(self) -> None:
        """Test formatting messages with unicode characters."""
        formatter: glogformat.GlogFormatter = glogformat.GlogFormatter()
        unicode_message: str = "Hello 世界 🌍 Привет мир"

        record: logging.LogRecord = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg=unicode_message,
            args=(),
            exc_info=None,
        )

        result: str = formatter.format(record)

        # Should preserve unicode characters
        self.assertIn(unicode_message, result)

    def test_exception_logging(self) -> None:
        """Test logging with exception info."""
        formatter: glogformat.GlogFormatter = glogformat.GlogFormatter()

        try:
            raise ValueError("Test exception")
        except ValueError:
            record: logging.LogRecord = logging.LogRecord(
                name="test",
                level=logging.ERROR,
                pathname=__file__,
                lineno=1,
                msg="Exception occurred",
                args=(),
                exc_info=sys.exc_info(),
            )

            result: str = formatter.format(record)

            # Should contain exception info
            self.assertIn("Exception occurred", result)
            # Default formatter should handle exc_info

    def test_file_rotation_on_size_limit(self) -> None:
        """Test that file rotation happens at size limit."""
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".log"
        ) as fh:
            log_file: str = fh.name

        try:
            # Set very small size limit (configure logging for side effect)
            _ = setup_stderr_logging(
                logging.INFO,
                log_file=log_file,
                max_bytes=100,  # Very small
                backup_count=2,
            )

            test_logger: logging.Logger = logging.getLogger("test_rotation")

            # Write enough to trigger rotation
            for i in range(20):
                test_logger.info(
                    f"Message {i} with enough text to fill the file"
                )

            # Should have created backup files
            backup_files: list[str] = glob.glob(f"{log_file}.*")

            # Should have at least one backup
            self.assertGreater(len(backup_files), 0)
        finally:
            # Clean up
            for file_path in glob.glob(f"{log_file}*"):
                with contextlib.suppress(FileNotFoundError, OSError):
                    pathlib.Path(file_path).unlink()

    def test_concurrent_logging(self) -> None:
        """Test thread-safe concurrent logging."""
        # Use a file instead of StringIO for better thread safety
        with tempfile.NamedTemporaryFile(
            mode="w+", delete=False, suffix=".log"
        ) as fh:
            log_file: str = fh.name

        try:
            logger: logging.Logger = setup_stderr_logging(
                logging.INFO, log_file=log_file, clear_handlers=True
            )

            test_logger: logging.Logger = logging.getLogger("test_concurrent")
            messages_per_thread: int = 50
            num_threads: int = 5

            def log_messages(thread_id: int) -> None:
                for i in range(messages_per_thread):
                    test_logger.info(f"Thread {thread_id} message {i}")

            threads: list[threading.Thread] = [
                threading.Thread(target=log_messages, args=(i,))
                for i in range(num_threads)
            ]

            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # Flush handlers
            for handler in logger.handlers:
                handler.flush()

            # Check that all messages were logged
            output_text: str = pathlib.Path(log_file).read_text()

            total_expected: int = messages_per_thread * num_threads
            actual_lines: int = len(
                [line for line in output_text.split("\n") if line]
            )

            self.assertEqual(actual_lines, total_expected)
        finally:
            log_path: pathlib.Path = pathlib.Path(log_file)
            if log_path.exists():
                log_path.unlink()

    def test_logging_from_different_modules(self) -> None:
        """Test logging from different module names."""
        setup_stderr_logging(logging.INFO)

        loggers: list[logging.Logger] = [
            logging.getLogger("module1"),
            logging.getLogger("module1.submodule"),
            logging.getLogger("module2"),
            logging.getLogger(""),  # Root logger
        ]

        # All should be able to log without errors
        for logger in loggers:
            logger.info(f"Message from {logger.name}")

    def test_custom_log_level(self) -> None:
        """Test logging with custom log levels."""
        # Add custom level
        VERBOSE: int = 15  # pylint: disable=invalid-name
        logging.addLevelName(VERBOSE, "VERBOSE")

        formatter: glogformat.GlogFormatter = glogformat.GlogFormatter()

        record: logging.LogRecord = logging.LogRecord(
            name="test",
            level=VERBOSE,
            pathname=__file__,
            lineno=1,
            msg="Verbose message",
            args=(),
            exc_info=None,
        )

        result: str = formatter.format(record)

        # Should format custom level (first character)
        self.assertTrue(result.startswith("V"))
        self.assertIn("Verbose message", result)


if __name__ == "__main__":
    unittest.main()
