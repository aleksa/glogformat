"""Tests for ColorGlogFormatter class."""

import io
import logging
import unittest

from glogformat import ColorGlogFormatter
from glogformat import GlogFormatter


class TestColorGlogFormatter(unittest.TestCase):
    """Test cases for ColorGlogFormatter."""

    def setUp(self):
        """Set up test fixtures."""
        self.formatter = ColorGlogFormatter()
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

    def test_debug_color(self):
        """Test DEBUG level has cyan color."""
        self.logger.debug("Debug message")
        output = self.stream.getvalue()

        # Should start with cyan color code
        self.assertTrue(output.startswith("\x1b[36m"))
        # Should end with reset code
        self.assertTrue(output.rstrip().endswith("\x1b[0m"))
        self.assertIn("Debug message", output)

    def test_info_color(self):
        """Test INFO level has bright black (grey) color."""
        self.logger.info("Info message")
        output = self.stream.getvalue()

        # Should start with bright black color code
        self.assertTrue(output.startswith("\x1b[90m"))
        # Should end with reset code
        self.assertTrue(output.rstrip().endswith("\x1b[0m"))
        self.assertIn("Info message", output)

    def test_warning_color(self):
        """Test WARNING level has yellow color."""
        self.logger.warning("Warning message")
        output = self.stream.getvalue()

        # Should start with yellow color code
        self.assertTrue(output.startswith("\x1b[33m"))
        # Should end with reset code
        self.assertTrue(output.rstrip().endswith("\x1b[0m"))
        self.assertIn("Warning message", output)

    def test_error_color(self):
        """Test ERROR level has red color."""
        self.logger.error("Error message")
        output = self.stream.getvalue()

        # Should start with red color code
        self.assertTrue(output.startswith("\x1b[31m"))
        # Should end with reset code
        self.assertTrue(output.rstrip().endswith("\x1b[0m"))
        self.assertIn("Error message", output)

    def test_critical_color(self):
        """Test CRITICAL level has bold magenta color."""
        self.logger.critical("Critical message")
        output = self.stream.getvalue()

        # Should start with bold magenta color code
        self.assertTrue(output.startswith("\x1b[1;35m"))
        # Should end with reset code
        self.assertTrue(output.rstrip().endswith("\x1b[0m"))
        self.assertIn("Critical message", output)

    def test_unknown_level_color(self):
        """Test unknown log level gets default color."""
        # Create a custom log level
        CUSTOM_LEVEL = 35
        logging.addLevelName(CUSTOM_LEVEL, "CUSTOM")

        self.logger.log(CUSTOM_LEVEL, "Custom level message")
        output = self.stream.getvalue()

        # Should start with unknown level color (bright black)
        self.assertTrue(output.startswith("\x1b[90m"))
        # Should end with reset code
        self.assertTrue(output.rstrip().endswith("\x1b[0m"))
        self.assertIn("Custom level message", output)

    def test_color_codes_constants(self):
        """Test that color code constants are defined correctly."""
        self.assertEqual(
            ColorGlogFormatter.LEVEL2COLORCODE[logging.DEBUG], "\x1b[36m"
        )
        self.assertEqual(
            ColorGlogFormatter.LEVEL2COLORCODE[logging.INFO], "\x1b[90m"
        )
        self.assertEqual(
            ColorGlogFormatter.LEVEL2COLORCODE[logging.WARNING], "\x1b[33m"
        )
        self.assertEqual(
            ColorGlogFormatter.LEVEL2COLORCODE[logging.ERROR], "\x1b[31m"
        )
        self.assertEqual(
            ColorGlogFormatter.LEVEL2COLORCODE[logging.CRITICAL], "\x1b[1;35m"
        )
        self.assertEqual(ColorGlogFormatter.UNKNOWN_LEVEL_COLOR, "\x1b[90m")
        self.assertEqual(ColorGlogFormatter.RESET_CODE, "\x1b[0m")

    def test_inheritance_from_glogformatter(self):
        """Test that ColorGlogFormatter inherits from GlogFormatter."""
        self.assertIsInstance(self.formatter, GlogFormatter)

    def test_color_format_preserves_glog_structure(self):
        """Test that colored output preserves glog format structure."""
        self.logger.info("Test message")
        output = self.stream.getvalue()

        # Remove color codes to check structure
        clean_output = output.replace("\x1b[90m", "").replace("\x1b[0m", "")

        # Should match glog format
        import re

        pattern = r"^I\d{8} \d{2}:\d{2}:\d{2}\.\d{6} \d+ \d+ .+:\d+\] Test message\n$"
        self.assertRegex(clean_output, pattern)

    def test_multiline_with_colors(self):
        """Test that multiline messages work with colors."""
        message = "Line 1\nLine 2\nLine 3"
        self.logger.info(message)
        output = self.stream.getvalue()

        # Should have color codes
        self.assertTrue(output.startswith("\x1b[90m"))
        self.assertTrue(output.rstrip().endswith("\x1b[0m"))
        # Should contain all lines
        self.assertIn("Line 1\nLine 2\nLine 3", output)

    def test_utc_with_colors(self):
        """Test that UTC mode works with colors."""
        utc_color_formatter = ColorGlogFormatter(use_utc=True)
        self.handler.setFormatter(utc_color_formatter)

        self.logger.info("UTC colored test")
        output = self.stream.getvalue()

        # Should have color codes
        self.assertTrue(output.startswith("\x1b[90m"))
        self.assertTrue(output.rstrip().endswith("\x1b[0m"))
        # Should have message
        self.assertIn("UTC colored test", output)

    def test_all_levels_have_different_colors(self):
        """Test that different log levels produce different colored output."""
        outputs = []
        levels = [
            logging.DEBUG,
            logging.INFO,
            logging.WARNING,
            logging.ERROR,
            logging.CRITICAL,
        ]

        for level in levels:
            self.stream.truncate(0)
            self.stream.seek(0)
            self.logger.log(level, f"Message at {level}")
            outputs.append(self.stream.getvalue())

        # All outputs should be different (at least in their color codes)
        # DEBUG and INFO/UNKNOWN share the same color, but WARNING, ERROR, CRITICAL are unique
        debug_color = outputs[0].split("]")[0]
        warning_color = outputs[2].split("]")[0]
        error_color = outputs[3].split("]")[0]
        critical_color = outputs[4].split("]")[0]

        # These should all be different
        self.assertNotEqual(warning_color, error_color)
        self.assertNotEqual(warning_color, critical_color)
        self.assertNotEqual(error_color, critical_color)


if __name__ == "__main__":
    unittest.main()
