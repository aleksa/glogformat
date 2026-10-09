"""Tests for setup_stderr_logging function."""

import io
import logging
import logging.handlers
import os
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import Mock
from unittest.mock import patch

import glogformat
from glogformat import ColorGlogFormatter
from glogformat import GlogFormatter
from glogformat import disable_child_propagation
from glogformat import setup_logger
from glogformat import setup_stderr_logging
from glogformat import silence_logger
from tests.helpers import isolate_logging_env


class TestSetupStderrLogging(unittest.TestCase):
    """Test cases for setup_stderr_logging function."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        isolate_logging_env(self)
        # Save original handlers
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
        # Restore original state
        logging.root.handlers = self.original_handlers
        logging.root.level = self.original_level

    def test_basic_setup(self) -> None:
        """Test basic stderr logging setup."""
        logger: logging.Logger = setup_stderr_logging(logging.INFO)

        self.assertEqual(logger, logging.root)
        self.assertEqual(logger.level, logging.INFO)
        self.assertGreater(len(logger.handlers), 0)

    def test_default_level_from_env(self) -> None:
        """Test that LOG_LEVEL environment variable sets default level."""
        os.environ["LOG_LEVEL"] = "DEBUG"
        logger: logging.Logger = setup_stderr_logging()

        self.assertEqual(logger.level, logging.DEBUG)

    def test_explicit_level_overrides_env(self) -> None:
        """Test that explicit level overrides LOG_LEVEL env var."""
        os.environ["LOG_LEVEL"] = "DEBUG"
        logger: logging.Logger = setup_stderr_logging(logging.WARNING)

        self.assertEqual(logger.level, logging.WARNING)

    def test_explicit_string_level(self) -> None:
        """Test that explicit string level names are supported."""
        logger: logging.Logger = setup_stderr_logging("ERROR")

        self.assertEqual(logger.level, logging.ERROR)

    def test_invalid_explicit_level_defaults_to_info(self) -> None:
        """Test that invalid explicit levels default to INFO."""
        with patch("glogformat._safe_stderr_write") as mock_write:
            logger: logging.Logger = setup_stderr_logging("LOUD")

            self.assertEqual(logger.level, logging.INFO)
            mock_write.assert_called()
            call_args: str = str(mock_write.call_args)
            self.assertIn("Invalid logging_level", call_args)

    def test_numeric_string_levels(self) -> None:
        """Test that numeric level strings work, from env and as argument."""
        for text, expected in (("10", 10), (" 25 ", 25), ("0", 0)):
            with self.subTest(text=text):
                os.environ["LOG_LEVEL"] = text
                self.assertEqual(setup_stderr_logging().level, expected)
                self.assertEqual(setup_stderr_logging(text).level, expected)

    def test_malformed_numeric_level_is_rejected(self) -> None:
        """Test that signed or non-ASCII-digit strings aren't levels."""
        for text in ("-10", "1.5", "²"):
            with self.subTest(text=text):
                with patch("glogformat._safe_stderr_write") as mock_write:
                    logger: logging.Logger = setup_stderr_logging(text)

                    self.assertEqual(logger.level, logging.INFO)
                    self.assertIn(
                        "Invalid logging_level", str(mock_write.call_args)
                    )

    def test_bool_level_is_rejected(self) -> None:
        """Test that True/False aren't accepted as levels 1/0."""
        for value in (True, False):
            with self.subTest(value=value):
                with patch("glogformat._safe_stderr_write") as mock_write:
                    logger: logging.Logger = setup_stderr_logging(value)

                    self.assertEqual(logger.level, logging.INFO)
                    self.assertIs(type(logger.level), int)
                    self.assertIn(
                        "Invalid logging_level", str(mock_write.call_args)
                    )

    def test_invalid_env_log_level_defaults_to_info(self) -> None:
        """Test that invalid LOG_LEVEL defaults to INFO."""
        os.environ["LOG_LEVEL"] = "INVALID_LEVEL"

        with patch("glogformat._safe_stderr_write") as mock_write:
            logger: logging.Logger = setup_stderr_logging()

            self.assertEqual(logger.level, logging.INFO)
            # Should have warned about invalid level
            mock_write.assert_called()
            call_args: str = str(mock_write.call_args)
            self.assertIn("Invalid LOG_LEVEL", call_args)

    def test_non_level_logging_attribute_is_rejected(self) -> None:
        """Test that non-level logging attributes aren't used as levels.

        BASIC_FORMAT is a str attribute of the logging module, so a plain
        getattr(logging, name) lookup would pass it to setLevel(), which
        raises ValueError.
        """
        for level in ("basic_format", "raiseExceptions"):
            with self.subTest(level=level):
                os.environ["LOG_LEVEL"] = level

                with patch("glogformat._safe_stderr_write") as mock_write:
                    logger: logging.Logger = setup_stderr_logging()

                    self.assertEqual(logger.level, logging.INFO)
                    self.assertIn(
                        "Invalid LOG_LEVEL", str(mock_write.call_args)
                    )

                with patch("glogformat._safe_stderr_write") as mock_write:
                    logger = setup_stderr_logging(level)

                    self.assertEqual(logger.level, logging.INFO)
                    self.assertIn(
                        "Invalid logging_level", str(mock_write.call_args)
                    )

    @unittest.skipIf(
        sys.version_info < (3, 11), "needs logging.getLevelNamesMapping()"
    )
    def test_custom_level_name(self) -> None:
        """Test that levels registered with addLevelName() are accepted."""
        logging.addLevelName(15, "VERBOSE")
        os.environ["LOG_LEVEL"] = "verbose"

        self.assertEqual(setup_stderr_logging().level, 15)
        self.assertEqual(setup_stderr_logging("VERBOSE").level, 15)

    def test_clear_handlers(self) -> None:
        """Test that clear_handlers removes existing handlers."""
        # Add a dummy handler
        dummy_handler: logging.NullHandler = logging.NullHandler()
        logging.root.addHandler(dummy_handler)

        initial_count: int = len(logging.root.handlers)
        logger: logging.Logger = setup_stderr_logging(
            logging.INFO, clear_handlers=True
        )

        # Old handler should be removed
        self.assertNotIn(dummy_handler, logger.handlers)
        # New handler(s) should be added
        self.assertGreater(len(logger.handlers), 0)
        # Should not accumulate handlers (cleared first)
        self.assertLessEqual(len(logger.handlers), initial_count)

    def test_no_clear_handlers_warning(self) -> None:
        """Test warning when not clearing existing handlers."""
        # Add a dummy handler
        dummy_handler: logging.NullHandler = logging.NullHandler()
        logging.root.addHandler(dummy_handler)

        with patch("glogformat._safe_stderr_write") as mock_write:
            logger: logging.Logger = setup_stderr_logging(
                logging.INFO, clear_handlers=False
            )

            # Should have warned about duplicate logs
            mock_write.assert_called()
            call_args: str = str(mock_write.call_args)
            self.assertIn("duplicate logs", call_args)

    def test_color_enabled_for_tty(self) -> None:
        """Test that color formatter is used when stderr is a TTY."""
        with patch("sys.stderr") as mock_stderr:
            mock_stderr.isatty.return_value = True
            mock_stderr.fileno.return_value = 2

            logger: logging.Logger = setup_stderr_logging(
                logging.INFO, color=True
            )

            # Find the StreamHandler
            stream_handler: logging.StreamHandler | None = None
            for handler in logger.handlers:
                if isinstance(handler, logging.StreamHandler):
                    stream_handler = handler
                    break

            self.assertIsNotNone(stream_handler)
            assert stream_handler is not None  # Type narrowing for mypy
            self.assertIsInstance(stream_handler.formatter, ColorGlogFormatter)

    def test_color_disabled_for_non_tty(self) -> None:
        """Test that plain formatter is used when stderr is not a TTY."""
        with patch("sys.stderr") as mock_stderr:
            mock_stderr.isatty.return_value = False
            mock_stderr.fileno.return_value = 2

            logger: logging.Logger = setup_stderr_logging(
                logging.INFO, color=True
            )

            # Find the StreamHandler
            stream_handler: logging.StreamHandler | None = None
            for handler in logger.handlers:
                if isinstance(handler, logging.StreamHandler):
                    stream_handler = handler
                    break

            self.assertIsNotNone(stream_handler)
            assert stream_handler is not None  # Type narrowing for mypy
            self.assertIsInstance(stream_handler.formatter, GlogFormatter)
            self.assertNotIsInstance(
                stream_handler.formatter, ColorGlogFormatter
            )

    def test_log_color_env_enable(self) -> None:
        """Test LOG_COLOR environment variable enables color."""
        for value in ["1", "true", "yes"]:
            with self.subTest(value=value):
                os.environ["LOG_COLOR"] = value

                with patch("sys.stderr") as mock_stderr:
                    mock_stderr.isatty.return_value = True
                    mock_stderr.fileno.return_value = 2

                    logger: logging.Logger = setup_stderr_logging(
                        logging.INFO, color=False
                    )

                    # Find the StreamHandler
                    stream_handler: logging.StreamHandler | None = None
                    for handler in logger.handlers:
                        if isinstance(handler, logging.StreamHandler):
                            stream_handler = handler
                            break

                    # Color should be enabled despite color=False
                    assert (
                        stream_handler is not None
                    )  # Type narrowing for mypy
                    self.assertIsInstance(
                        stream_handler.formatter, ColorGlogFormatter
                    )

                del os.environ["LOG_COLOR"]
                glogformat._close_handlers(logging.root)

    def test_log_color_env_disable(self) -> None:
        """Test LOG_COLOR environment variable disables color."""
        for value in ["0", "false", "no"]:
            with self.subTest(value=value):
                os.environ["LOG_COLOR"] = value

                with patch("sys.stderr") as mock_stderr:
                    mock_stderr.isatty.return_value = True
                    mock_stderr.fileno.return_value = 2

                    logger: logging.Logger = setup_stderr_logging(
                        logging.INFO, color=True
                    )

                    # Find the StreamHandler
                    stream_handler: logging.StreamHandler | None = None
                    for handler in logger.handlers:
                        if isinstance(handler, logging.StreamHandler):
                            stream_handler = handler
                            break

                    # Color should be disabled despite color=True
                    assert (
                        stream_handler is not None
                    )  # Type narrowing for mypy
                    self.assertNotIsInstance(
                        stream_handler.formatter, ColorGlogFormatter
                    )

                del os.environ["LOG_COLOR"]
                glogformat._close_handlers(logging.root)

    def test_invalid_log_color_env(self) -> None:
        """Test invalid LOG_COLOR environment variable."""
        os.environ["LOG_COLOR"] = "maybe"

        with patch("glogformat._safe_stderr_write") as mock_write:
            with patch("sys.stderr") as mock_stderr:
                mock_stderr.isatty.return_value = True
                mock_stderr.fileno.return_value = 2

                setup_stderr_logging(logging.INFO, color=True)

                # Should warn about invalid value
                mock_write.assert_called()
                call_args: str = str(mock_write.call_args)
                self.assertIn("Invalid LOG_COLOR", call_args)

    def test_no_color_env_disables_color(self) -> None:
        """Test NO_COLOR disables color output."""
        os.environ["NO_COLOR"] = "1"

        with patch("sys.stderr") as mock_stderr:
            mock_stderr.isatty.return_value = True
            mock_stderr.fileno.return_value = 2

            logger: logging.Logger = setup_stderr_logging(
                logging.INFO, color=True
            )

            stream_handler = next(
                h
                for h in logger.handlers
                if isinstance(h, logging.StreamHandler)
                and not isinstance(h, logging.handlers.RotatingFileHandler)
            )
            self.assertNotIsInstance(
                stream_handler.formatter, ColorGlogFormatter
            )

    def test_force_color_env_enables_color(self) -> None:
        """Test FORCE_COLOR enables color output."""
        os.environ["FORCE_COLOR"] = "1"

        with patch("sys.stderr") as mock_stderr:
            mock_stderr.isatty.return_value = True
            mock_stderr.fileno.return_value = 2

            logger: logging.Logger = setup_stderr_logging(
                logging.INFO, color=False
            )

            stream_handler = next(
                h
                for h in logger.handlers
                if isinstance(h, logging.StreamHandler)
                and not isinstance(h, logging.handlers.RotatingFileHandler)
            )
            self.assertIsInstance(stream_handler.formatter, ColorGlogFormatter)

    def test_log_color_overrides_no_color(self) -> None:
        """Test LOG_COLOR keeps backwards-compatible precedence."""
        os.environ["LOG_COLOR"] = "1"
        os.environ["NO_COLOR"] = "1"

        with patch("sys.stderr") as mock_stderr:
            mock_stderr.isatty.return_value = True
            mock_stderr.fileno.return_value = 2

            logger: logging.Logger = setup_stderr_logging(
                logging.INFO, color=False
            )

            stream_handler = next(
                h
                for h in logger.handlers
                if isinstance(h, logging.StreamHandler)
                and not isinstance(h, logging.handlers.RotatingFileHandler)
            )
            self.assertIsInstance(stream_handler.formatter, ColorGlogFormatter)

    def _stderr_formatter(
        self, *, isatty: bool, color: bool
    ) -> logging.Formatter | None:
        """Set up logging on a mock stderr and return its formatter."""
        with patch("sys.stderr") as mock_stderr:
            mock_stderr.isatty.return_value = isatty
            mock_stderr.closed = False
            logger: logging.Logger = setup_stderr_logging(
                logging.INFO, color=color
            )
        stream_handler = next(
            h
            for h in logger.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.handlers.RotatingFileHandler)
        )
        return stream_handler.formatter

    def test_force_color_env_colors_non_tty(self) -> None:
        """Test FORCE_COLOR colors output even when stderr is not a TTY."""
        os.environ["FORCE_COLOR"] = "1"

        formatter = self._stderr_formatter(isatty=False, color=True)

        self.assertIsInstance(formatter, ColorGlogFormatter)

    def test_no_color_overrides_force_color(self) -> None:
        """Test NO_COLOR wins over FORCE_COLOR, as in CPython."""
        os.environ["FORCE_COLOR"] = "1"
        os.environ["NO_COLOR"] = "1"

        formatter = self._stderr_formatter(isatty=True, color=True)

        self.assertNotIsInstance(formatter, ColorGlogFormatter)

    def test_force_color_falsy_values_do_not_enable_color(self) -> None:
        """Test FORCE_COLOR=0/false/no doesn't force color on."""
        for value in ("0", "false", "no", ""):
            with self.subTest(value=value):
                os.environ["FORCE_COLOR"] = value

                formatter = self._stderr_formatter(isatty=True, color=False)

                self.assertNotIsInstance(formatter, ColorGlogFormatter)

    def test_log_color_enable_still_requires_tty(self) -> None:
        """Test LOG_COLOR=1 keeps its TTY-only behavior."""
        os.environ["LOG_COLOR"] = "1"

        formatter = self._stderr_formatter(isatty=False, color=True)

        self.assertNotIsInstance(formatter, ColorGlogFormatter)

    def test_invalid_log_color_falls_through_to_no_color(self) -> None:
        """Test an invalid LOG_COLOR is ignored in favor of NO_COLOR."""
        os.environ["LOG_COLOR"] = "maybe"
        os.environ["NO_COLOR"] = "1"

        with patch("glogformat._safe_stderr_write") as mock_write:
            formatter = self._stderr_formatter(isatty=True, color=True)

            self.assertIn("Invalid LOG_COLOR", str(mock_write.call_args))
        self.assertNotIsInstance(formatter, ColorGlogFormatter)

    def test_file_logging(self) -> None:
        """Test logging to file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as fh:
            log_file: str = fh.name

        try:
            logger: logging.Logger = setup_stderr_logging(
                logging.INFO, log_file=log_file, max_bytes=1000, backup_count=3
            )

            # Should have file handler
            file_handlers: list[logging.handlers.RotatingFileHandler] = [
                h
                for h in logger.handlers
                if isinstance(h, logging.handlers.RotatingFileHandler)
            ]
            self.assertGreater(len(file_handlers), 0)

            # Test logging to file
            test_logger: logging.Logger = logging.getLogger("test_file")
            test_logger.info("Test file message")

            # Read file content
            content: str = pathlib.Path(log_file).read_text()

            self.assertIn("Test file message", content)
        finally:
            # Clean up
            log_path: pathlib.Path = pathlib.Path(log_file)
            if log_path.exists():
                log_path.unlink()

    def test_file_logging_with_rotation_params(self) -> None:
        """Test that file rotation parameters are set correctly."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as fh:
            log_file: str = fh.name

        try:
            logger: logging.Logger = setup_stderr_logging(
                logging.INFO, log_file=log_file, max_bytes=5000, backup_count=7
            )

            # Find rotating file handler
            file_handler: logging.handlers.RotatingFileHandler | None = None
            for h in logger.handlers:
                if isinstance(h, logging.handlers.RotatingFileHandler):
                    file_handler = h
                    break

            self.assertIsNotNone(file_handler)
            assert file_handler is not None  # Type narrowing for mypy
            self.assertEqual(file_handler.maxBytes, 5000)
            self.assertEqual(file_handler.backupCount, 7)
        finally:
            log_path: pathlib.Path = pathlib.Path(log_file)
            if log_path.exists():
                log_path.unlink()

    def test_file_logging_accepts_pathlike(self) -> None:
        """Test logging to a pathlib.Path log file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as fh:
            log_file = pathlib.Path(fh.name)

        try:
            logger: logging.Logger = setup_stderr_logging(
                logging.INFO, log_file=log_file
            )

            file_handlers: list[logging.handlers.RotatingFileHandler] = [
                h
                for h in logger.handlers
                if isinstance(h, logging.handlers.RotatingFileHandler)
            ]
            self.assertGreater(len(file_handlers), 0)

            logging.getLogger("test_pathlike").info("PathLike message")
            self.assertIn("PathLike message", log_file.read_text())
        finally:
            if log_file.exists():
                log_file.unlink()

    def test_invalid_log_file(self) -> None:
        """Test handling of invalid log file path."""
        with patch("glogformat._safe_stderr_write") as mock_write:
            # Try to create file in non-existent directory
            logger: logging.Logger = setup_stderr_logging(
                logging.INFO, log_file="/nonexistent/directory/file.log"
            )

            # Should have warned about failure
            mock_write.assert_called()
            call_args: str = str(mock_write.call_args)
            self.assertIn("Failed to create log file", call_args)

    def test_empty_log_file_string(self) -> None:
        """Test handling of empty log file string."""
        with patch("glogformat._safe_stderr_write") as mock_write:
            logger: logging.Logger = setup_stderr_logging(
                logging.INFO, log_file="   "
            )

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

    def test_missing_stderr(self) -> None:
        """Test handling when stderr is None."""
        with patch.object(sys, "stderr", None):
            logger: logging.Logger = setup_stderr_logging(logging.INFO)

            # Should add NullHandler
            has_null_handler: bool = any(
                isinstance(h, logging.NullHandler) for h in logger.handlers
            )
            self.assertTrue(has_null_handler)

    def test_stderr_without_fileno(self) -> None:
        """Test handling when stderr has no fileno method."""
        # Create mock stderr without fileno
        mock_stderr: Mock = Mock()
        del mock_stderr.fileno
        mock_stderr.closed = False
        mock_stderr.isatty.return_value = False

        with patch.object(sys, "stderr", mock_stderr):
            logger: logging.Logger = setup_stderr_logging(logging.INFO)

            stream_handlers: list[logging.StreamHandler] = [
                h
                for h in logger.handlers
                if isinstance(h, logging.StreamHandler)
                and not isinstance(h, logging.handlers.RotatingFileHandler)
            ]
            self.assertEqual(len(stream_handlers), 1)

    def test_stderr_isatty_exception_disables_color(self) -> None:
        """Test that isatty failures fall back to plain stderr logging."""
        mock_stderr: Mock = Mock()
        mock_stderr.closed = False
        mock_stderr.isatty.side_effect = OSError("isatty failed")

        with patch.object(sys, "stderr", mock_stderr):
            logger: logging.Logger = setup_stderr_logging(
                logging.INFO, color=True
            )

            stream_handler = next(
                h
                for h in logger.handlers
                if isinstance(h, logging.StreamHandler)
                and not isinstance(h, logging.handlers.RotatingFileHandler)
            )
            self.assertIsInstance(stream_handler.formatter, GlogFormatter)
            self.assertNotIsInstance(
                stream_handler.formatter, ColorGlogFormatter
            )

    def test_utc_timestamps(self) -> None:
        """Test UTC timestamp mode."""
        logger: logging.Logger = setup_stderr_logging(
            logging.INFO, use_utc=True
        )

        # Check that handlers have UTC formatters
        for handler in logger.handlers:
            if hasattr(handler.formatter, "use_utc"):
                assert handler.formatter is not None  # Type narrowing for mypy
                self.assertTrue(handler.formatter.use_utc)

    def test_local_timestamps(self) -> None:
        """Test local timestamp mode (default)."""
        logger: logging.Logger = setup_stderr_logging(
            logging.INFO, use_utc=False
        )

        # Check that handlers have local time formatters
        for handler in logger.handlers:
            if hasattr(handler.formatter, "use_utc"):
                assert handler.formatter is not None  # Type narrowing for mypy
                self.assertFalse(handler.formatter.use_utc)

    def test_both_stderr_and_file_logging(self) -> None:
        """Test that both stderr and file logging work together."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as fh:
            log_file: str = fh.name

        try:
            logger: logging.Logger = setup_stderr_logging(
                logging.INFO, color=False, log_file=log_file
            )

            # Should have both handlers
            has_stream: bool = any(
                isinstance(h, logging.StreamHandler)
                and not isinstance(h, logging.handlers.RotatingFileHandler)
                for h in logger.handlers
            )
            has_file: bool = any(
                isinstance(h, logging.handlers.RotatingFileHandler)
                for h in logger.handlers
            )

            self.assertTrue(has_stream)
            self.assertTrue(has_file)
        finally:
            log_path: pathlib.Path = pathlib.Path(log_file)
            if log_path.exists():
                log_path.unlink()


class TestDisableChildPropagation(unittest.TestCase):
    """Test cases for disable_child_propagation function."""

    def test_disable_propagation(self) -> None:
        """Test that propagation is disabled for named logger."""
        logger_name: str = "test.child.logger"
        logger: logging.Logger = logging.getLogger(logger_name)

        # Ensure propagation is enabled initially
        logger.propagate = True

        disable_child_propagation(logger_name)

        # Propagation should be disabled
        self.assertFalse(logger.propagate)

    def test_multiple_loggers(self) -> None:
        """Test disabling propagation for multiple loggers."""
        logger_names: list[str] = [
            "test.logger1",
            "test.logger2",
            "test.logger3",
        ]

        for name in logger_names:
            logging.getLogger(name).propagate = True

        for name in logger_names:
            disable_child_propagation(name)

        for name in logger_names:
            self.assertFalse(logging.getLogger(name).propagate)


class TestSetupLogger(unittest.TestCase):
    """Test cases for setup_logger function."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        isolate_logging_env(self)
        self.logger_name = "test.named.setup"
        self.logger = logging.getLogger(self.logger_name)
        self.original_handlers = self.logger.handlers[:]
        self.original_level = self.logger.level
        self.original_propagate = self.logger.propagate

    def tearDown(self) -> None:
        """Clean up test fixtures."""
        new_handlers: list[logging.Handler] = [
            handler
            for handler in self.logger.handlers
            if handler not in self.original_handlers
        ]
        glogformat._close_handlers(self.logger, new_handlers)
        self.logger.handlers = self.original_handlers
        self.logger.level = self.original_level
        self.logger.propagate = self.original_propagate

    def test_setup_logger_configures_named_logger_only(self) -> None:
        """Test named logger setup avoids root logger configuration."""
        original_root_handlers = logging.root.handlers[:]
        original_root_level = logging.root.level

        logger = setup_logger(self.logger_name, "DEBUG")

        self.assertIs(logger, self.logger)
        self.assertEqual(logger.level, logging.DEBUG)
        self.assertFalse(logger.propagate)
        self.assertGreater(len(logger.handlers), 0)
        self.assertEqual(logging.root.handlers, original_root_handlers)
        self.assertEqual(logging.root.level, original_root_level)

    def test_setup_logger_can_preserve_propagation(self) -> None:
        """Test named logger setup can leave propagation enabled."""
        logger = setup_logger(self.logger_name, logging.INFO, propagate=True)

        self.assertTrue(logger.propagate)

    def test_setup_logger_uses_env_level(self) -> None:
        """Test named logger setup uses LOG_LEVEL by default."""
        os.environ["LOG_LEVEL"] = "WARNING"

        logger = setup_logger(self.logger_name)

        self.assertEqual(logger.level, logging.WARNING)


class TestSilenceLogger(unittest.TestCase):
    """Test cases for silence_logger function."""

    def test_silence_logger_sets_level_above_critical(self) -> None:
        """Test that a named logger is configured to suppress records."""
        logger_name: str = "test.silenced.logger"
        logger: logging.Logger = logging.getLogger(logger_name)
        original_level: int = logger.level

        try:
            logger.setLevel(logging.NOTSET)
            silence_logger(logger_name)
            self.assertEqual(logger.level, logging.CRITICAL + 1)
        finally:
            logger.setLevel(original_level)

    def test_silence_logger_covers_inheriting_children(self) -> None:
        """Test that NOTSET children are silenced, explicit ones are not."""
        parent: logging.Logger = logging.getLogger("test.silenced.parent")
        inheriting: logging.Logger = logging.getLogger(
            "test.silenced.parent.inheriting"
        )
        explicit: logging.Logger = logging.getLogger(
            "test.silenced.parent.explicit"
        )

        try:
            inheriting.setLevel(logging.NOTSET)
            explicit.setLevel(logging.INFO)
            silence_logger(parent.name)

            self.assertFalse(inheriting.isEnabledFor(logging.CRITICAL))
            self.assertTrue(explicit.isEnabledFor(logging.INFO))
        finally:
            for logger in (parent, inheriting, explicit):
                logger.setLevel(logging.NOTSET)


if __name__ == "__main__":
    unittest.main()
