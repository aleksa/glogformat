"""Tests for edge cases and error handling."""

import glob
import io
import logging
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import Mock
from unittest.mock import patch

from glogformat import RotationErrorFilter
from glogformat import _safe_stderr_write
from glogformat import setup_stderr_logging


class TestSafeStderrWrite(unittest.TestCase):
    """Test cases for _safe_stderr_write function."""

    def test_normal_write(self):
        """Test normal write to stderr."""
        original_stderr = sys.stderr
        try:
            output = io.StringIO()
            sys.stderr = output

            _safe_stderr_write("Test message\n")

            self.assertEqual(output.getvalue(), "Test message\n")
        finally:
            sys.stderr = original_stderr

    def test_none_stderr(self):
        """Test that function handles None stderr gracefully."""
        original_stderr = sys.stderr
        try:
            sys.stderr = None

            # Should not raise exception
            _safe_stderr_write("Test message\n")
        finally:
            sys.stderr = original_stderr

    def test_closed_stderr(self):
        """Test that function handles closed stderr gracefully."""
        original_stderr = sys.stderr
        try:
            # Create a closed StringIO
            closed_stream = io.StringIO()
            closed_stream.close()
            sys.stderr = closed_stream

            # Should not raise exception
            _safe_stderr_write("Test message\n")
        finally:
            sys.stderr = original_stderr

    def test_stderr_write_exception(self):
        """Test that function handles write exceptions gracefully."""
        original_stderr = sys.stderr
        try:
            # Create mock that raises on write
            mock_stderr = Mock()
            mock_stderr.write.side_effect = IOError("Mock write error")
            sys.stderr = mock_stderr

            # Should not raise exception
            _safe_stderr_write("Test message\n")
        finally:
            sys.stderr = original_stderr

    def test_stderr_flush_exception(self):
        """Test that function handles flush exceptions gracefully."""
        original_stderr = sys.stderr
        try:
            # Create mock that raises on flush
            mock_stderr = Mock()
            mock_stderr.flush.side_effect = IOError("Mock flush error")
            sys.stderr = mock_stderr

            # Should not raise exception
            _safe_stderr_write("Test message\n")
        finally:
            sys.stderr = original_stderr


class TestRotationErrorFilter(unittest.TestCase):
    """Test cases for RotationErrorFilter."""

    def test_first_error_shows_warning(self):
        """Test that first error shows warning."""
        filter_obj = RotationErrorFilter()

        # Create a log record with exception
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="Rotation failed",
            args=(),
            exc_info=(ValueError, ValueError("Test error"), None),
        )

        with patch("glogformat._safe_stderr_write") as mock_write:
            result = filter_obj.filter(record)

            # Should return True to allow the record
            self.assertTrue(result)
            # Should have written warning
            mock_write.assert_called_once()
            call_args = str(mock_write.call_args)
            self.assertIn("Warning: Log rotation failed", call_args)

    def test_subsequent_errors_no_warning(self):
        """Test that subsequent errors don't show warning."""
        filter_obj = RotationErrorFilter()

        # Create log records with exceptions
        record1 = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="First error",
            args=(),
            exc_info=(ValueError, ValueError("Test error 1"), None),
        )
        record2 = logging.LogRecord(
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

    def test_record_without_exception(self):
        """Test filtering record without exception info."""
        filter_obj = RotationErrorFilter()

        # Create a log record without exception
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="Normal message",
            args=(),
            exc_info=None,
        )

        with patch("glogformat._safe_stderr_write") as mock_write:
            result = filter_obj.filter(record)

            # Should return True to allow the record
            self.assertTrue(result)
            # Should not write warning
            mock_write.assert_not_called()

    def test_filter_always_returns_true(self):
        """Test that filter always returns True to allow records through."""
        filter_obj = RotationErrorFilter()

        # Test various scenarios
        test_cases = [
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
            result = filter_obj.filter(record)
            self.assertTrue(result)


class TestEdgeCasesIntegration(unittest.TestCase):
    """Integration tests for edge cases."""

    def setUp(self):
        """Set up test fixtures."""
        self.original_handlers = logging.root.handlers[:]
        self.original_level = logging.root.level

    def tearDown(self):
        """Clean up test fixtures."""
        logging.root.handlers = self.original_handlers
        logging.root.level = self.original_level

    def test_large_thread_ids(self):
        """Test formatting with large thread IDs (Linux 64-bit)."""
        from glogformat import GlogFormatter

        formatter = GlogFormatter()

        # Create a log record with a large thread ID
        record = logging.LogRecord(
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

        result = formatter.format(record)

        # Should include the large thread ID without truncation
        self.assertIn(str(140737354018816), result)

    def test_very_long_messages(self):
        """Test formatting very long messages."""
        from glogformat import GlogFormatter

        formatter = GlogFormatter()
        long_message = "A" * 10000

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg=long_message,
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)

        # Should contain the full message
        self.assertIn(long_message, result)

    def test_unicode_messages(self):
        """Test formatting messages with unicode characters."""
        from glogformat import GlogFormatter

        formatter = GlogFormatter()
        unicode_message = "Hello 世界 🌍 Привет мир"

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg=unicode_message,
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)

        # Should preserve unicode characters
        self.assertIn(unicode_message, result)

    def test_exception_logging(self):
        """Test logging with exception info."""
        from glogformat import GlogFormatter

        formatter = GlogFormatter()

        try:
            raise ValueError("Test exception")
        except ValueError:
            record = logging.LogRecord(
                name="test",
                level=logging.ERROR,
                pathname=__file__,
                lineno=1,
                msg="Exception occurred",
                args=(),
                exc_info=sys.exc_info(),
            )

            result = formatter.format(record)

            # Should contain exception info
            self.assertIn("Exception occurred", result)
            # Default formatter should handle exc_info

    def test_file_rotation_on_size_limit(self):
        """Test that file rotation happens at size limit."""
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".log"
        ) as f:
            log_file = f.name

        try:
            # Set very small size limit
            logger = setup_stderr_logging(
                logging.INFO,
                log_file=log_file,
                max_bytes=100,  # Very small
                backup_count=2,
            )

            test_logger = logging.getLogger("test_rotation")

            # Write enough to trigger rotation
            for i in range(20):
                test_logger.info(
                    f"Message {i} with enough text to fill the file"
                )

            # Should have created backup files
            backup_files = glob.glob(f"{log_file}.*")

            # Should have at least one backup
            self.assertGreater(len(backup_files), 0)
        finally:
            # Clean up
            for f in glob.glob(f"{log_file}*"):
                try:
                    pathlib.Path(f).unlink()
                except:
                    pass

    def test_concurrent_logging(self):
        """Test thread-safe concurrent logging."""
        import tempfile
        import threading

        from glogformat import setup_stderr_logging

        # Use a file instead of StringIO for better thread safety
        with tempfile.NamedTemporaryFile(
            mode="w+", delete=False, suffix=".log"
        ) as f:
            log_file = f.name

        try:
            logger = setup_stderr_logging(
                logging.INFO, log_file=log_file, clear_handlers=True
            )

            test_logger = logging.getLogger("test_concurrent")
            messages_per_thread = 50
            num_threads = 5

            def log_messages(thread_id):
                for i in range(messages_per_thread):
                    test_logger.info(f"Thread {thread_id} message {i}")

            threads = [
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
            with open(log_file, "r") as f:
                output_text = f.read()

            total_expected = messages_per_thread * num_threads
            actual_lines = len(
                [line for line in output_text.split("\n") if line]
            )

            self.assertEqual(actual_lines, total_expected)
        finally:
            log_path = pathlib.Path(log_file)
            if log_path.exists():
                log_path.unlink()

    def test_logging_from_different_modules(self):
        """Test logging from different module names."""
        setup_stderr_logging(logging.INFO)

        loggers = [
            logging.getLogger("module1"),
            logging.getLogger("module1.submodule"),
            logging.getLogger("module2"),
            logging.getLogger(""),  # Root logger
        ]

        # All should be able to log without errors
        for logger in loggers:
            logger.info(f"Message from {logger.name}")

    def test_custom_log_level(self):
        """Test logging with custom log levels."""
        from glogformat import GlogFormatter

        # Add custom level
        VERBOSE = 15
        logging.addLevelName(VERBOSE, "VERBOSE")

        formatter = GlogFormatter()

        record = logging.LogRecord(
            name="test",
            level=VERBOSE,
            pathname=__file__,
            lineno=1,
            msg="Verbose message",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)

        # Should format custom level (first character)
        self.assertTrue(result.startswith("V"))
        self.assertIn("Verbose message", result)


if __name__ == "__main__":
    unittest.main()
