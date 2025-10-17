"""Tests for setup_stderr_logging function."""

import io
import logging
import os
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import Mock
from unittest.mock import patch

from glogformat import ColorGlogFormatter
from glogformat import GlogFormatter
from glogformat import disable_child_propagation
from glogformat import setup_stderr_logging


class TestSetupStderrLogging(unittest.TestCase):
    """Test cases for setup_stderr_logging function."""

    def setUp(self):
        """Set up test fixtures."""
        # Save original handlers
        self.original_handlers = logging.root.handlers[:]
        self.original_level = logging.root.level

    def tearDown(self):
        """Clean up test fixtures."""
        # Restore original state
        logging.root.handlers = self.original_handlers
        logging.root.level = self.original_level

        # Clean up environment variables
        for key in ["LOG_LEVEL", "LOG_COLOR"]:
            if key in os.environ:
                del os.environ[key]

    def test_basic_setup(self):
        """Test basic stderr logging setup."""
        logger = setup_stderr_logging(logging.INFO)

        self.assertEqual(logger, logging.root)
        self.assertEqual(logger.level, logging.INFO)
        self.assertGreater(len(logger.handlers), 0)

    def test_default_level_from_env(self):
        """Test that LOG_LEVEL environment variable sets default level."""
        os.environ["LOG_LEVEL"] = "DEBUG"
        logger = setup_stderr_logging()

        self.assertEqual(logger.level, logging.DEBUG)

    def test_explicit_level_overrides_env(self):
        """Test that explicit level overrides LOG_LEVEL env var."""
        os.environ["LOG_LEVEL"] = "DEBUG"
        logger = setup_stderr_logging(logging.WARNING)

        self.assertEqual(logger.level, logging.WARNING)

    def test_invalid_env_log_level_defaults_to_info(self):
        """Test that invalid LOG_LEVEL defaults to INFO."""
        os.environ["LOG_LEVEL"] = "INVALID_LEVEL"

        with patch("glogformat._safe_stderr_write") as mock_write:
            logger = setup_stderr_logging()

            self.assertEqual(logger.level, logging.INFO)
            # Should have warned about invalid level
            mock_write.assert_called()
            call_args = str(mock_write.call_args)
            self.assertIn("Invalid LOG_LEVEL", call_args)

    def test_clear_handlers(self):
        """Test that clear_handlers removes existing handlers."""
        # Add a dummy handler
        dummy_handler = logging.NullHandler()
        logging.root.addHandler(dummy_handler)

        initial_count = len(logging.root.handlers)
        logger = setup_stderr_logging(logging.INFO, clear_handlers=True)

        # Old handler should be removed
        self.assertNotIn(dummy_handler, logger.handlers)

    def test_no_clear_handlers_warning(self):
        """Test warning when not clearing existing handlers."""
        # Add a dummy handler
        dummy_handler = logging.NullHandler()
        logging.root.addHandler(dummy_handler)

        with patch("glogformat._safe_stderr_write") as mock_write:
            logger = setup_stderr_logging(logging.INFO, clear_handlers=False)

            # Should have warned about duplicate logs
            mock_write.assert_called()
            call_args = str(mock_write.call_args)
            self.assertIn("duplicate logs", call_args)

    def test_color_enabled_for_tty(self):
        """Test that color formatter is used when stderr is a TTY."""
        with patch("sys.stderr") as mock_stderr:
            mock_stderr.isatty.return_value = True
            mock_stderr.fileno.return_value = 2

            logger = setup_stderr_logging(logging.INFO, color=True)

            # Find the StreamHandler
            stream_handler = None
            for handler in logger.handlers:
                if isinstance(handler, logging.StreamHandler):
                    stream_handler = handler
                    break

            self.assertIsNotNone(stream_handler)
            self.assertIsInstance(stream_handler.formatter, ColorGlogFormatter)

    def test_color_disabled_for_non_tty(self):
        """Test that plain formatter is used when stderr is not a TTY."""
        with patch("sys.stderr") as mock_stderr:
            mock_stderr.isatty.return_value = False
            mock_stderr.fileno.return_value = 2

            logger = setup_stderr_logging(logging.INFO, color=True)

            # Find the StreamHandler
            stream_handler = None
            for handler in logger.handlers:
                if isinstance(handler, logging.StreamHandler):
                    stream_handler = handler
                    break

            self.assertIsNotNone(stream_handler)
            self.assertIsInstance(stream_handler.formatter, GlogFormatter)
            self.assertNotIsInstance(
                stream_handler.formatter, ColorGlogFormatter
            )

    def test_log_color_env_enable(self):
        """Test LOG_COLOR environment variable enables color."""
        for value in ["1", "true", "yes"]:
            with self.subTest(value=value):
                os.environ["LOG_COLOR"] = value

                with patch("sys.stderr") as mock_stderr:
                    mock_stderr.isatty.return_value = True
                    mock_stderr.fileno.return_value = 2

                    logger = setup_stderr_logging(logging.INFO, color=False)

                    # Find the StreamHandler
                    stream_handler = None
                    for handler in logger.handlers:
                        if isinstance(handler, logging.StreamHandler):
                            stream_handler = handler
                            break

                    # Color should be enabled despite color=False
                    self.assertIsInstance(
                        stream_handler.formatter, ColorGlogFormatter
                    )

                del os.environ["LOG_COLOR"]
                logging.root.handlers.clear()

    def test_log_color_env_disable(self):
        """Test LOG_COLOR environment variable disables color."""
        for value in ["0", "false", "no"]:
            with self.subTest(value=value):
                os.environ["LOG_COLOR"] = value

                with patch("sys.stderr") as mock_stderr:
                    mock_stderr.isatty.return_value = True
                    mock_stderr.fileno.return_value = 2

                    logger = setup_stderr_logging(logging.INFO, color=True)

                    # Find the StreamHandler
                    stream_handler = None
                    for handler in logger.handlers:
                        if isinstance(handler, logging.StreamHandler):
                            stream_handler = handler
                            break

                    # Color should be disabled despite color=True
                    self.assertNotIsInstance(
                        stream_handler.formatter, ColorGlogFormatter
                    )

                del os.environ["LOG_COLOR"]
                logging.root.handlers.clear()

    def test_invalid_log_color_env(self):
        """Test invalid LOG_COLOR environment variable."""
        os.environ["LOG_COLOR"] = "maybe"

        with patch("glogformat._safe_stderr_write") as mock_write:
            with patch("sys.stderr") as mock_stderr:
                mock_stderr.isatty.return_value = True
                mock_stderr.fileno.return_value = 2

                setup_stderr_logging(logging.INFO, color=True)

                # Should warn about invalid value
                mock_write.assert_called()
                call_args = str(mock_write.call_args)
                self.assertIn("Invalid LOG_COLOR", call_args)

    def test_file_logging(self):
        """Test logging to file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            log_file = f.name

        try:
            logger = setup_stderr_logging(
                logging.INFO, log_file=log_file, max_bytes=1000, backup_count=3
            )

            # Should have file handler
            file_handlers = [
                h
                for h in logger.handlers
                if isinstance(h, logging.handlers.RotatingFileHandler)
            ]
            self.assertGreater(len(file_handlers), 0)

            # Test logging to file
            test_logger = logging.getLogger("test_file")
            test_logger.info("Test file message")

            # Read file content
            with open(log_file, "r") as f:
                content = f.read()

            self.assertIn("Test file message", content)
        finally:
            # Clean up
            log_path = pathlib.Path(log_file)
            if log_path.exists():
                log_path.unlink()

    def test_file_logging_with_rotation_params(self):
        """Test that file rotation parameters are set correctly."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            log_file = f.name

        try:
            logger = setup_stderr_logging(
                logging.INFO, log_file=log_file, max_bytes=5000, backup_count=7
            )

            # Find rotating file handler
            file_handler = None
            for h in logger.handlers:
                if isinstance(h, logging.handlers.RotatingFileHandler):
                    file_handler = h
                    break

            self.assertIsNotNone(file_handler)
            self.assertEqual(file_handler.maxBytes, 5000)
            self.assertEqual(file_handler.backupCount, 7)
        finally:
            log_path = pathlib.Path(log_file)
            if log_path.exists():
                log_path.unlink()

    def test_invalid_log_file(self):
        """Test handling of invalid log file path."""
        with patch("glogformat._safe_stderr_write") as mock_write:
            # Try to create file in non-existent directory
            logger = setup_stderr_logging(
                logging.INFO, log_file="/nonexistent/directory/file.log"
            )

            # Should have warned about failure
            mock_write.assert_called()
            call_args = str(mock_write.call_args)
            self.assertIn("Failed to create log file", call_args)

    def test_empty_log_file_string(self):
        """Test handling of empty log file string."""
        with patch("glogformat._safe_stderr_write") as mock_write:
            logger = setup_stderr_logging(logging.INFO, log_file="   ")

            # Should have warned about invalid file
            self.assertTrue(
                mock_write.called
                or len(
                    [
                        h
                        for h in logger.handlers
                        if isinstance(h, logging.handlers.RotatingFileHandler)
                    ]
                )
                == 0
            )

    def test_missing_stderr(self):
        """Test handling when stderr is None."""
        original_stderr = sys.stderr
        try:
            sys.stderr = None

            logger = setup_stderr_logging(logging.INFO)

            # Should add NullHandler
            has_null_handler = any(
                isinstance(h, logging.NullHandler) for h in logger.handlers
            )
            self.assertTrue(has_null_handler)
        finally:
            sys.stderr = original_stderr

    def test_stderr_without_fileno(self):
        """Test handling when stderr has no fileno method."""
        original_stderr = sys.stderr
        try:
            # Create mock stderr without fileno
            mock_stderr = Mock()
            del mock_stderr.fileno
            sys.stderr = mock_stderr

            logger = setup_stderr_logging(logging.INFO)

            # Should add NullHandler or handle gracefully
            self.assertIsNotNone(logger)
        finally:
            sys.stderr = original_stderr

    def test_utc_timestamps(self):
        """Test UTC timestamp mode."""
        logger = setup_stderr_logging(logging.INFO, use_utc=True)

        # Check that handlers have UTC formatters
        for handler in logger.handlers:
            if hasattr(handler.formatter, "use_utc"):
                self.assertTrue(handler.formatter.use_utc)

    def test_local_timestamps(self):
        """Test local timestamp mode (default)."""
        logger = setup_stderr_logging(logging.INFO, use_utc=False)

        # Check that handlers have local time formatters
        for handler in logger.handlers:
            if hasattr(handler.formatter, "use_utc"):
                self.assertFalse(handler.formatter.use_utc)

    def test_both_stderr_and_file_logging(self):
        """Test that both stderr and file logging work together."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            log_file = f.name

        try:
            logger = setup_stderr_logging(
                logging.INFO, color=False, log_file=log_file
            )

            # Should have both handlers
            has_stream = any(
                isinstance(h, logging.StreamHandler)
                and not isinstance(h, logging.handlers.RotatingFileHandler)
                for h in logger.handlers
            )
            has_file = any(
                isinstance(h, logging.handlers.RotatingFileHandler)
                for h in logger.handlers
            )

            self.assertTrue(has_stream)
            self.assertTrue(has_file)
        finally:
            log_path = pathlib.Path(log_file)
            if log_path.exists():
                log_path.unlink()


class TestDisableChildPropagation(unittest.TestCase):
    """Test cases for disable_child_propagation function."""

    def test_disable_propagation(self):
        """Test that propagation is disabled for named logger."""
        logger_name = "test.child.logger"
        logger = logging.getLogger(logger_name)

        # Ensure propagation is enabled initially
        logger.propagate = True

        disable_child_propagation(logger_name)

        # Propagation should be disabled
        self.assertFalse(logger.propagate)

    def test_multiple_loggers(self):
        """Test disabling propagation for multiple loggers."""
        logger_names = ["test.logger1", "test.logger2", "test.logger3"]

        for name in logger_names:
            logging.getLogger(name).propagate = True

        for name in logger_names:
            disable_child_propagation(name)

        for name in logger_names:
            self.assertFalse(logging.getLogger(name).propagate)


if __name__ == "__main__":
    unittest.main()
