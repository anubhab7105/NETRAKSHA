"""CLI entry point for the Netraksha Testing Framework.

Run with: python main.py [options]
"""

import argparse
import sys
from pathlib import Path

from netraksha_testing.core.config import load_config
from netraksha_testing.core.registry import CATEGORY_GROUPS, get_all_categories
from netraksha_testing.core.runner import TestRunner


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Netraksha Testing and Benchmarking Framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --all                # Run everything
  python main.py --category ai        # Run only AI accuracy tests
  python main.py --category performance # Run only performance tests
  python main.py --config custom.yml  # Use custom configuration
"""
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all test categories",
    )
    
    parser.add_argument(
        "--category",
        "-c",
        type=str,
        action="append",
        choices=list(CATEGORY_GROUPS.keys()) + get_all_categories(),
        help="Run specific test category or group",
    )
    
    parser.add_argument(
        "--config",
        type=str,
        help="Path to custom config.yaml",
    )
    
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress console output (except fatal errors)",
    )

    args = parser.parse_args()

    # Determine categories
    categories = None
    if not args.all:
        if args.category:
            categories = args.category
        else:
            parser.print_help()
            print("\nError: Must specify either --all or at least one --category")
            return 1

    # Load config
    cfg_path = Path(args.config) if args.config else None
    try:
        cfg = load_config(cfg_path)
    except Exception as e:
        print(f"Error loading configuration: {e}")
        return 1

    # Initialize and execute runner
    runner = TestRunner(
        cfg=cfg,
        categories=categories,
        verbose=args.verbose,
        quiet=args.quiet,
    )
    
    try:
        result = runner.run()
        # Return non-zero if there were any errors or failures
        if result.failed > 0 or result.errors > 0:
            return 1
        return 0
    except KeyboardInterrupt:
        print("\n\nTest run interrupted by user.")
        return 130
    except Exception as e:
        print(f"\n\nFatal error during test run: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
