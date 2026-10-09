"""Tests for edge cases and error handling."""

import contextlib
import glob
import io
import logging
import logging.handlers
import pathlib
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock
from unittest.mock import patch

import glogformat
from glogformat import _safe_stderr_write
from glogformat import setup_stderr_logging
from tests.helpers import isolate_logging_env


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


class TestRotatingFileHandlerWarnings(unittest.TestCase):
    """Test cases for rotating file handler warnings."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        isolate_logging_env(self)

    def test_application_exception_does_not_warn_about_rotation(self) -> None:
        """Test that logger.exception doesn't look like rotation failure."""
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".log"
        ) as fh:
            log_file: str = fh.name

        original_handlers = logging.root.handlers[:]
        original_level = logging.root.level
        try:
            setup_stderr_logging(logging.INFO, log_file=log_file)
            logger = logging.getLogger("test_exception_warning")

            with patch("glogformat._safe_stderr_write") as mock_write:
                try:
                    raise ValueError("Test error")
                except ValueError:
                    logger.exception("Application exception")

                warning_text = str(mock_write.call_args_list)
                self.assertNotIn("Log rotation failed", warning_text)
                self.assertNotIn("Log file handler failed", warning_text)
        finally:
            for handler in logging.root.handlers[:]:
                if handler not in original_handlers:
                    logging.root.removeHandler(handler)
                    handler.close()
            logging.root.handlers = original_handlers
            logging.root.level = original_level
            with contextlib.suppress(FileNotFoundError, OSError):
                pathlib.Path(log_file).unlink()

    def test_handler_error_warning_is_once(self) -> None:
        """Test that handler write errors emit one warning."""
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".log"
        ) as fh:
            log_file: str = fh.name

        handler = glogformat._WarningRotatingFileHandler(log_file)
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="File write failed",
            args=(),
            exc_info=None,
        )

        try:
            with patch("glogformat._safe_stderr_write") as mock_write:
                with patch.object(
                    logging.handlers.RotatingFileHandler,
                    "handleError",
                    return_value=None,
                ):
                    for _ in range(2):
                        try:
                            raise OSError("No space left on device")
                        except OSError:
                            handler.handleError(record)

                self.assertEqual(mock_write.call_count, 1)
                call_args: str = str(mock_write.call_args)
                self.assertIn("Warning: Log file handler failed", call_args)
                self.assertIn("No space left on device", call_args)
        finally:
            handler.close()
            with contextlib.suppress(FileNotFoundError, OSError):
                pathlib.Path(log_file).unlink()

    def test_write_failure_warns(self) -> None:
        """Test that a failing file write emits the warning end to end."""
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".log"
        ) as fh:
            log_file: str = fh.name

        handler = glogformat._WarningRotatingFileHandler(log_file)
        logger = logging.getLogger("test_write_failure_warns")
        logger.addHandler(handler)
        logger.propagate = False
        failing_stream: Mock = Mock()
        failing_stream.write.side_effect = OSError("No space left on device")
        original_stream = handler.stream
        handler.stream = failing_stream

        try:
            with patch("glogformat._safe_stderr_write") as mock_write:
                with patch.object(logging, "raiseExceptions", False):
                    logger.error("First")
                    logger.error("Second")

                self.assertEqual(mock_write.call_count, 1)
                self.assertIn(
                    "No space left on device", str(mock_write.call_args)
                )
        finally:
            handler.stream = original_stream
            glogformat._close_handlers(logger)
            logger.propagate = True
            with contextlib.suppress(FileNotFoundError, OSError):
                pathlib.Path(log_file).unlink()

    def test_format_error_does_not_consume_warning(self) -> None:
        """Test that a caller's bad format args don't use up the warning.

        Regression test: handleError used to call record.getMessage(), which
        re-raised the formatting error before the warning was written, while
        still marking the one-shot warning as shown.
        """
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".log"
        ) as fh:
            log_file: str = fh.name

        handler = glogformat._WarningRotatingFileHandler(log_file)
        logger = logging.getLogger("test_format_error_warning")
        logger.addHandler(handler)
        logger.propagate = False
        original_stream = handler.stream

        try:
            with patch("glogformat._safe_stderr_write") as mock_write:
                with patch.object(logging, "raiseExceptions", False):
                    logger.info("count=%d", "not-a-number")
                    mock_write.assert_not_called()

                    failing_stream: Mock = Mock()
                    failing_stream.write.side_effect = OSError("Disk full")
                    handler.stream = failing_stream
                    logger.error("Real failure")

                self.assertEqual(mock_write.call_count, 1)
                self.assertIn("Disk full", str(mock_write.call_args))
        finally:
            handler.stream = original_stream
            glogformat._close_handlers(logger)
            logger.propagate = True
            with contextlib.suppress(FileNotFoundError, OSError):
                pathlib.Path(log_file).unlink()


class TestEdgeCasesIntegration(unittest.TestCase):
    """Integration tests for edge cases."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        isolate_logging_env(self)
        self.original_handlers = logging.root.handlers[:]
        self.original_level = logging.root.level

    def tearDown(self) -> None:
        """Clean up test fixtures."""
        new_handlers: list[logging.Handler] = [
            handler
            for handler in logging.root.handlers
            if handler not in self.original_handlers
        ]
        glogformat._close_handlers(logging.root, new_handlers)
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
