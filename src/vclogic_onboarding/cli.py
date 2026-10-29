"""Command-line interface for portable investor assessment bundles."""
import argparse
import json
import sys
import httpx
from pathlib import Path

from .bundle import check_bundle, index_bundle, install_bundle, prepare


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    build = commands.add_parser("prepare", help="Validate a wiki and prepare an investor bundle")
    build.add_argument("--wiki", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    for name in ("slug", "display-name", "firm", "role"):
        build.add_argument(f"--{name}")
    build.add_argument("--alias", dest="aliases", action="append", default=[])
    build.add_argument("--from-pitch-show", action="store_true", help="Collect Pitch Show evidence and extract decisions, explanations and policy links (uses model calls)")
    build.add_argument("--pitch-show-slug", help="Investor slug on The Pitch website (defaults to wiki slug)")
    build.add_argument("--pitch-show-cache", type=Path, help="Reuse collected evidence; automatic extraction still calls the model")
    build.add_argument("--max-episodes", type=int, help="Limit matching investor episodes; candidate pages examined may be higher")
    build.add_argument("--collect-only", action="store_true", help="Download Pitch Show evidence without automatic decision extraction")
    build.add_argument("--decision-model", help="OpenRouter model for automatic decision extraction and verification")
    build.add_argument("--review", type=Path, help="Evidence-linked human review JSON for historical pitches")
    build.add_argument("--skip-indexes", action="store_true", help="Prepare an incomplete bundle without downloading embedding models")
    for name, help_text in (("index", "Build semantic indexes for an existing bundle"), ("check", "Verify bundle contents and assessment compatibility"), ("install", "Install an investor bundle into an existing pipeline workspace")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--bundle", type=Path, required=True)
        if name == "install":
            command.add_argument("--pipeline-workspace", type=Path, required=True)
    return result


def main(argv=None):
    args = vars(parser().parse_args(argv))
    command = args.pop("command")
    try:
        if command == "prepare":
            output = args["output"]
            prepare(**args)
            result = check_bundle(output)
        elif command == "index":
            index_bundle(args["bundle"])
            result = check_bundle(args["bundle"])
        elif command == "check":
            result = check_bundle(args["bundle"])
        else:
            result = install_bundle(args["bundle"], args["pipeline_workspace"])
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, RuntimeError, ImportError, httpx.HTTPError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        if isinstance(exc, ImportError):
            print("For semantic indexing, run with: uv run --extra embeddings investor-onboarding ...", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
