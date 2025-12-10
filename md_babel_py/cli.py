"""Command-line interface for md-babel-py."""

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import load_config, get_evaluator, Config, EvaluatorConfig
from .exceptions import ConfigError, MdBabelError
from .executor import Executor
from .parser import find_code_blocks, CodeBlock
from .types import ExecutionResult
from .writer import apply_results, BlockResult

logger = logging.getLogger(__name__)


def main() -> int:
    """Main entry point for md-babel-py CLI."""
    parser = argparse.ArgumentParser(
        prog="md-babel-py",
        description="Execute code blocks in markdown files",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose/debug output",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # config command - show merged config
    config_parser = subparsers.add_parser("config", help="Show merged configuration as JSON")
    config_parser.add_argument("--config", "-c", type=Path, help="Config file path")

    # ls command - list configured evaluators
    ls_parser = subparsers.add_parser("ls", help="List configured evaluators")
    ls_parser.add_argument("--config", "-c", type=Path, help="Config file path")

    # run command
    run_parser = subparsers.add_parser("run", help="Execute code blocks in a markdown file")
    run_parser.add_argument("file", type=Path, help="Markdown file to process")
    run_parser.add_argument("--output", "-o", type=Path, help="Output file (default: edit in-place)")
    run_parser.add_argument("--stdout", action="store_true", help="Print result to stdout instead of writing file")
    run_parser.add_argument("--config", "-c", type=Path, help="Config file path")
    run_parser.add_argument("--lang", help="Only execute these languages (comma-separated)")
    run_parser.add_argument("--dry-run", action="store_true", help="Show what would be executed")

    args = parser.parse_args()

    # Setup logging
    setup_logging(verbose=args.verbose)

    try:
        if args.command == "config":
            return cmd_config(args)
        elif args.command == "ls":
            return cmd_ls(args)
        elif args.command == "run":
            return cmd_run(args)
        return 0
    except ConfigError as e:
        logger.error(f"Configuration error: {e}")
        return 1
    except MdBabelError as e:
        logger.error(f"Error: {e}")
        return 1


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the application.

    Args:
        verbose: If True, enable DEBUG level logging.
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        stream=sys.stderr,
    )
    # Quieter format for non-verbose
    if not verbose:
        logging.getLogger("md_babel_py").setLevel(logging.INFO)


def format_block_flags(block: CodeBlock) -> str:
    """Format block flags for display.

    Args:
        block: The code block to format flags for.

    Returns:
        A formatted string like " [session=main, expected-error]" or empty string.
    """
    flags = []
    if block.session:
        flags.append(f"session={block.session}")
    if block.expected_error:
        flags.append("expected-error")
    if block.no_result:
        flags.append("no-result")
    return f" [{', '.join(flags)}]" if flags else ""


def filter_blocks(
    blocks: list[CodeBlock],
    config: Config,
    lang_filter: set[str] | None,
) -> tuple[list[CodeBlock], set[str]]:
    """Filter blocks by language and configuration.

    Args:
        blocks: All parsed code blocks.
        config: The loaded configuration.
        lang_filter: Optional set of languages to include.

    Returns:
        Tuple of (configured_blocks, unconfigured_languages).
    """
    # Filter by language if specified
    if lang_filter:
        blocks = [b for b in blocks if b.language in lang_filter]

    # Separate configured from unconfigured
    unconfigured: set[str] = set()
    configured: list[CodeBlock] = []

    for block in blocks:
        if get_evaluator(config, block.language):
            configured.append(block)
        else:
            unconfigured.add(block.language)

    return configured, unconfigured


def execute_blocks(
    executor: Executor,
    blocks: list[CodeBlock],
) -> tuple[list[BlockResult], list[str], bool]:
    """Execute code blocks and collect results.

    Args:
        executor: The executor instance.
        blocks: The blocks to execute.

    Returns:
        Tuple of (results, test_failures, stopped_early).
    """
    results: list[BlockResult] = []
    test_failures: list[str] = []
    stopped_early = False

    for i, block in enumerate(blocks, 1):
        flags_str = format_block_flags(block)
        logger.info(f"[{i}/{len(blocks)}] Executing {block.language}{flags_str} block at line {block.start_line}...")

        result = executor.execute(block)

        # Only add to results if we want to write output (not no-result)
        if not block.no_result:
            results.append(BlockResult(block=block, result=result))

        # Check expected-error logic
        if block.expected_error:
            if result.success:
                msg = f"Line {block.start_line}: expected error but block succeeded"
                test_failures.append(msg)
                logger.error(f"FAIL: {msg}")
            # Don't stop on expected errors
        else:
            if not result.success:
                msg = f"Line {block.start_line}: {result.error_message or 'Execution failed'}"
                test_failures.append(msg)
                logger.error(f"Error: {result.error_message or 'Execution failed'}")
                if result.stderr:
                    logger.error(result.stderr)
                # Stop on first unexpected error
                stopped_early = True
                break

    return results, test_failures, stopped_early


def cmd_config(args: argparse.Namespace) -> int:
    """Show merged configuration as JSON.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code (0 for success).
    """
    config = load_config(args.config)

    # Convert to JSON-serializable format
    output = {
        "evaluators": {
            "codeBlock": {
                lang: {
                    "path": ev.path,
                    "defaultArguments": ev.default_arguments,
                    **({"session": {
                        "command": ev.session.command,
                        **({"marker": ev.session.marker} if ev.session.marker else {}),
                        **({"prompts": ev.session.prompts} if ev.session.prompts else {}),
                    }} if ev.session else {}),
                    **({"inputExtension": ev.input_extension} if ev.input_extension else {}),
                    **({"defaultParams": ev.default_params} if ev.default_params else {}),
                    **({"prefix": ev.prefix} if ev.prefix else {}),
                    **({"suffix": ev.suffix} if ev.suffix else {}),
                }
                for lang, ev in sorted(config.evaluators.items())
            }
        }
    }

    print(json.dumps(output, indent=2))
    return 0


def cmd_ls(args: argparse.Namespace) -> int:
    """List configured evaluators.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code (0 for success).
    """
    config = load_config(args.config)

    if not config.evaluators:
        print("No evaluators configured.")
        return 0

    for lang, ev in sorted(config.evaluators.items()):
        features = []
        if ev.session:
            features.append("session")
        if ev.input_extension:
            features.append(f"file:{ev.input_extension}")
        if ev.prefix or ev.suffix:
            features.append("wrap")

        features_str = f" [{', '.join(features)}]" if features else ""
        cmd = f"{ev.path} {' '.join(ev.default_arguments)}"
        print(f"{lang}{features_str}")
        print(f"  {cmd}")

    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Execute the run command.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code (0 for success, non-zero for failure).
    """
    # Load config
    config = load_config(args.config)

    # Read input file
    if not args.file.exists():
        logger.error(f"Error: File not found: {args.file}")
        return 1

    content = args.file.read_text()

    # Parse code blocks
    blocks = find_code_blocks(content)

    if not blocks:
        logger.info("No code blocks found.")
        return 0

    # Parse language filter
    lang_filter = set(args.lang.split(",")) if args.lang else None

    # Filter blocks
    configured_blocks, unconfigured = filter_blocks(blocks, config, lang_filter)

    if unconfigured:
        logger.warning(f"Warning: No evaluators configured for: {', '.join(sorted(unconfigured))}")

    if not configured_blocks:
        logger.info("No executable code blocks found.")
        return 0

    # Filter out skipped blocks
    executable_blocks = [b for b in configured_blocks if not b.skip]
    skipped_count = len(configured_blocks) - len(executable_blocks)

    # Dry run - just show what would execute
    if args.dry_run:
        logger.info(f"Would execute {len(executable_blocks)} code block(s):\n")
        for i, block in enumerate(executable_blocks, 1):
            flags_str = format_block_flags(block)
            logger.info(f"{i}. {block.language}{flags_str} (lines {block.start_line}-{block.end_line})")
            logger.info(f"   {block.code[:50]}{'...' if len(block.code) > 50 else ''}")
            logger.info("")
        if skipped_count:
            logger.info(f"({skipped_count} block(s) marked as skip)")
        return 0

    # Execute blocks
    executor = Executor(config)
    try:
        results, test_failures, _ = execute_blocks(executor, executable_blocks)
    finally:
        executor.cleanup()

    # Apply results to content
    new_content = apply_results(content, results)

    # Write output
    if args.stdout:
        print(new_content)
    else:
        output_path = args.output or args.file
        output_path.write_text(new_content)

    success_count = sum(1 for r in results if r.result.success)
    logger.info(f"\nDone: {success_count}/{len(results)} blocks executed successfully.")

    if not args.stdout and args.output and args.output != args.file:
        logger.info(f"Output written to: {args.output}")

    if test_failures:
        logger.error(f"\n{len(test_failures)} test failure(s):")
        for f in test_failures:
            logger.error(f"  - {f}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
