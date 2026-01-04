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
    run_parser.add_argument("file", type=Path, help="Markdown file or directory to process")
    run_parser.add_argument("--output", "-o", type=Path, help="Output file (default: edit in-place)")
    run_parser.add_argument("--stdout", action="store_true", help="Print result to stdout instead of writing file")
    run_parser.add_argument("--config", "-c", type=Path, help="Config file path")
    run_parser.add_argument("--lang", help="Only execute these languages (comma-separated)")
    run_parser.add_argument("--dry-run", action="store_true", help="Show what would be executed")
    run_parser.add_argument("--no-cache", action="store_true", help="Disable caching, always re-execute blocks")
    run_parser.add_argument("--recursive", "-r", action="store_true", help="Process all .md files in directory recursively")

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


def collect_markdown_files(path: Path, recursive: bool) -> list[Path]:
    """Collect markdown files from path.

    Args:
        path: File or directory path.
        recursive: If True and path is a directory, find all .md files recursively.

    Returns:
        List of markdown file paths.
    """
    if path.is_file():
        return [path]
    elif path.is_dir():
        if recursive:
            return sorted(path.rglob("*.md"))
        else:
            return sorted(path.glob("*.md"))
    return []


def run_single_file(
    file_path: Path,
    config: Config,
    args: argparse.Namespace,
) -> tuple[int, int, list[str]]:
    """Process a single markdown file.

    Args:
        file_path: Path to the markdown file.
        config: Loaded configuration.
        args: Command-line arguments.

    Returns:
        Tuple of (blocks_executed, blocks_total, test_failures).
    """
    content = file_path.read_text()

    # Parse code blocks
    blocks = find_code_blocks(content)

    if not blocks:
        return 0, 0, []

    # Parse language filter
    lang_filter = set(args.lang.split(",")) if args.lang else None

    # Filter blocks
    configured_blocks, unconfigured = filter_blocks(blocks, config, lang_filter)

    if unconfigured:
        logger.warning(f"Warning: No evaluators configured for: {', '.join(sorted(unconfigured))}")

    if not configured_blocks:
        return 0, 0, []

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
        return len(executable_blocks), len(executable_blocks), []

    # Execute blocks
    cache_enabled = not getattr(args, "no_cache", False)
    executor = Executor(config, cache_enabled=cache_enabled, source_file=file_path)
    try:
        results, test_failures, _ = execute_blocks(executor, executable_blocks)
    finally:
        executor.cleanup()

    # Log cache stats
    stats = executor.cache.stats
    if stats["hits"] > 0 or stats["misses"] > 0:
        logger.info(f"Cache: {stats['hits']} hits, {stats['misses']} misses")

    # Apply results to content
    new_content = apply_results(content, results)

    # Write output
    if args.stdout:
        print(new_content)
    else:
        output_path = args.output or file_path
        output_path.write_text(new_content)

    success_count = sum(1 for r in results if r.result.success)
    return success_count, len(results), test_failures


def cmd_run(args: argparse.Namespace) -> int:
    """Execute the run command.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code (0 for success, non-zero for failure).
    """
    # Load config
    config = load_config(args.config)

    # Check path exists
    if not args.file.exists():
        logger.error(f"Error: Path not found: {args.file}")
        return 1

    # Collect files to process
    files = collect_markdown_files(args.file, args.recursive)

    if not files:
        if args.file.is_dir():
            logger.info(f"No markdown files found in {args.file}")
        else:
            logger.error(f"Error: Not a markdown file: {args.file}")
        return 0

    # Validate flags for multi-file mode
    if len(files) > 1:
        if args.stdout:
            logger.error("Error: --stdout not supported with multiple files")
            return 1
        if args.output:
            logger.error("Error: --output not supported with multiple files")
            return 1

    # Process files
    total_success = 0
    total_blocks = 0
    all_failures: list[str] = []

    for file_path in files:
        if len(files) > 1:
            logger.info(f"\n{'='*60}\nProcessing: {file_path}\n{'='*60}")

        success, total, failures = run_single_file(file_path, config, args)
        total_success += success
        total_blocks += total
        all_failures.extend([f"{file_path}: {f}" for f in failures])

    # Summary for multi-file mode
    if len(files) > 1:
        logger.info(f"\n{'='*60}")
        logger.info(f"Total: {len(files)} files, {total_success}/{total_blocks} blocks executed successfully.")
    elif total_blocks > 0:
        logger.info(f"\nDone: {total_success}/{total_blocks} blocks executed successfully.")

    if not args.stdout and args.output and len(files) == 1:
        logger.info(f"Output written to: {args.output}")

    if all_failures:
        logger.error(f"\n{len(all_failures)} test failure(s):")
        for f in all_failures:
            logger.error(f"  - {f}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
