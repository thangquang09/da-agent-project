#!/usr/bin/env python3
"""
Sync CLAUDE.md and AGENTS.md files in each directory.
If one file is newer than the other, copy the newer content to the older file.
"""

import argparse
import os
from pathlib import Path
from datetime import datetime


def get_file_mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime)


def sync_pair(dir_path: Path) -> tuple[bool, str]:
    """Sync CLAUDE.md and AGENTS.md in a directory. Returns (did_sync, message)."""
    claude_path = dir_path / "CLAUDE.md"
    agents_path = dir_path / "AGENTS.md"

    if not claude_path.exists() and not agents_path.exists():
        return False, "No CLAUDE.md or AGENTS.md found"

    if not claude_path.exists():
        return False, "CLAUDE.md does not exist"
    if not agents_path.exists():
        return False, "AGENTS.md does not exist"

    claude_mtime = get_file_mtime(claude_path)
    agents_mtime = get_file_mtime(agents_path)

    if claude_mtime == agents_mtime:
        return False, "Files are in sync"

    if claude_mtime > agents_mtime:
        source = claude_path
        dest = agents_path
        source_name = "CLAUDE.md"
    else:
        source = agents_path
        dest = claude_path
        source_name = "AGENTS.md"

    content = source.read_text(encoding="utf-8")
    dest.write_text(content, encoding="utf-8")

    return (
        True,
        f"Copied {source_name} → {'AGENTS.md' if source_name == 'CLAUDE.md' else 'CLAUDE.md'}",
    )


def find_directories(root: Path) -> list[Path]:
    """Find all directories containing either CLAUDE.md or AGENTS.md."""
    dirs = set()
    for md_file in ["CLAUDE.md", "AGENTS.md"]:
        for path in root.rglob(md_file):
            dirs.add(path.parent)
    return sorted(dirs)


def main():
    parser = argparse.ArgumentParser(description="Sync CLAUDE.md and AGENTS.md files")
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Show what would be synced without making changes",
    )
    parser.add_argument(
        "--root",
        "-r",
        type=Path,
        default=Path("."),
        help="Root directory to search (default: current dir)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show all directories even if no sync needed",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    if not root.exists():
        print(f"Error: Directory not found: {root}")
        return 1

    dirs = find_directories(root)

    if not dirs:
        print("No directories with CLAUDE.md or AGENTS.md found")
        return 0

    synced_count = 0

    for dir_path in dirs:
        did_sync, msg = sync_pair(dir_path)
        rel_path = dir_path.relative_to(root)

        if did_sync:
            synced_count += 1
            if args.dry_run:
                print(f"[DRY-RUN] Would sync: {rel_path} — {msg}")
            else:
                print(f"Synced: {rel_path} — {msg}")
        elif args.verbose:
            print(f"  SKIP: {rel_path} — {msg}")

    if args.dry_run:
        print(f"\n[DRY-RUN] Would sync {synced_count} directory(ies)")
    else:
        print(f"\nSynced {synced_count} directory(ies)")

    return 0


if __name__ == "__main__":
    exit(main())
