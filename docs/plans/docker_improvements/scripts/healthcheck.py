#!/usr/bin/env python3
"""
Health check script for RulesLawyerBot.

Provides three types of health checks:
  - startup: Verify all prerequisites are met before starting
  - readiness: Check if service is ready to accept requests
  - liveness: Check if service is still alive and responsive

Usage:
    python scripts/healthcheck.py startup
    python scripts/healthcheck.py readiness
    python scripts/healthcheck.py liveness
"""

import os
import sys
import sqlite3
import logging
import subprocess
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


class HealthChecker:
    """Comprehensive health check implementation."""

    def __init__(self):
        """Initialize health checker."""
        self.pdf_path = Path(os.getenv('PDF_STORAGE_PATH', './rules_pdfs'))
        self.data_path = Path(os.getenv('DATA_PATH', './data'))
        self.db_path = self.data_path / 'sessions.db'

    def startup_check(self) -> tuple[bool, list[str]]:
        """
        Check prerequisites for startup.

        Verifies:
        - Required environment variables are set
        - Required directories exist or can be created
        - External tools are available

        Returns:
            Tuple of (success: bool, errors: list[str])
        """
        errors = []

        # Check 1: Required environment variables
        logger.info("Checking environment variables...")
        required_env = {
            'TELEGRAM_TOKEN': 'Telegram bot token',
            'OPENAI_API_KEY': 'OpenAI API key',
        }

        for var, description in required_env.items():
            if not os.getenv(var):
                errors.append(f"Missing required environment variable: {var} ({description})")
            else:
                logger.debug(f"  ✓ {var} is set")

        # Check 2: Required directories can be created
        logger.info("Checking directories...")
        for dir_path in [self.pdf_path, self.data_path]:
            try:
                dir_path.mkdir(parents=True, exist_ok=True)
                logger.debug(f"  ✓ Directory available: {dir_path}")
            except Exception as e:
                errors.append(f"Cannot create directory {dir_path}: {e}")

        # Check 3: External tools
        logger.info("Checking external tools...")
        tools = ['ugrep', 'python']

        for tool in tools:
            try:
                subprocess.run(
                    [tool, '--version'] if tool != 'python' else ['python', '--version'],
                    capture_output=True,
                    check=True,
                    timeout=5
                )
                logger.debug(f"  ✓ {tool} is available")
            except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                errors.append(f"Tool not available: {tool} ({e})")

        return len(errors) == 0, errors

    def readiness_check(self) -> tuple[bool, list[str]]:
        """
        Check if service is ready to accept requests.

        Verifies:
        - Directory permissions (read/write)
        - Database connectivity
        - Environment variables are set

        Returns:
            Tuple of (success: bool, errors: list[str])
        """
        errors = []

        # Check 1: Directory permissions
        logger.info("Checking directory permissions...")
        for dir_path in [self.pdf_path, self.data_path]:
            if not dir_path.is_dir():
                errors.append(f"Directory not found: {dir_path}")
            elif not os.access(dir_path, os.R_OK | os.W_OK):
                errors.append(f"No read/write access to: {dir_path}")
            else:
                logger.debug(f"  ✓ {dir_path} is accessible")

        # Check 2: Database connectivity
        logger.info("Checking database...")
        try:
            # Ensure directory exists
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

            # Test connection with timeout
            with sqlite3.connect(str(self.db_path), timeout=2) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT 1')
                logger.debug(f"  ✓ Database is accessible at {self.db_path}")
        except Exception as e:
            errors.append(f"Database error: {e}")

        # Check 3: Environment variables
        logger.info("Checking required environment variables...")
        for var in ['TELEGRAM_TOKEN', 'OPENAI_API_KEY']:
            if not os.getenv(var):
                errors.append(f"Missing required environment variable: {var}")
            else:
                logger.debug(f"  ✓ {var} is set")

        return len(errors) == 0, errors

    def liveness_check(self) -> tuple[bool, list[str]]:
        """
        Check if service is still alive and responsive.

        Currently same as readiness_check, but can be extended to check:
        - Recent activity in logs
        - Message processing timestamps
        - Memory leaks or hung processes
        - API connectivity

        Returns:
            Tuple of (success: bool, errors: list[str])
        """
        logger.info("Running liveness check...")
        return self.readiness_check()


def main():
    """CLI entry point for health checks."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Health check utility for RulesLawyerBot',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/healthcheck.py startup
    python scripts/healthcheck.py readiness
    python scripts/healthcheck.py liveness
        """
    )

    parser.add_argument(
        'check',
        choices=['startup', 'readiness', 'liveness'],
        help='Type of health check to perform'
    )

    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose output'
    )

    args = parser.parse_args()

    # Set logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    checker = HealthChecker()

    # Execute selected check
    if args.check == 'startup':
        ok, errors = checker.startup_check()
        check_name = 'Startup'
    elif args.check == 'readiness':
        ok, errors = checker.readiness_check()
        check_name = 'Readiness'
    else:  # liveness
        ok, errors = checker.liveness_check()
        check_name = 'Liveness'

    # Report results
    if ok:
        logger.info(f"{check_name} check passed")
        return 0
    else:
        logger.error(f"{check_name} check failed:")
        for error in errors:
            logger.error(f"  - {error}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
