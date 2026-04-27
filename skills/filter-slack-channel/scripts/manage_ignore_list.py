#!/usr/bin/env python3
"""
Manage ignore list: update timestamps and disable stale entries.

Usage:
  python3 manage_ignore_list.py <ignore_list_file> <matched_ignores_json> <current_timestamp>

Updates the ignore list file by:
- Updating "Last seen" timestamps for matched ignores
- Moving stale ignores (>30 days) to disabled section
- Reports changes to stdout as JSON
"""

import sys
import json
import re
import os
import tempfile
from datetime import datetime, timedelta
from typing import List, Tuple, Dict
from pathlib import Path


def parse_ignore_entry(line: str) -> Tuple[str, str, str]:
    """
    Parse an active ignore entry line.

    Args:
        line: Entry in format '- "message" - Reason: reason - Last seen: timestamp'

    Returns:
        Tuple of (message_text, reason, last_seen_timestamp)
    """
    # Use greedy matching with specific timestamp pattern to handle messages containing " - Reason:"
    match = re.match(r'^- "(.+)" - Reason: (.+) - Last seen: (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)$', line)
    if match:
        return match.group(1), match.group(2), match.group(3)
    return None, None, None


def is_stale(last_seen_iso: str, current_iso: str, days: int = 30) -> bool:
    """
    Check if an ignore entry is stale (not seen in X days).

    Args:
        last_seen_iso: Last seen timestamp in ISO 8601 format
        current_iso: Current timestamp in ISO 8601 format
        days: Number of days to consider stale (default 30)

    Returns:
        True if stale, False otherwise
    """
    try:
        last_seen = datetime.fromisoformat(last_seen_iso.replace('Z', '+00:00'))
        current = datetime.fromisoformat(current_iso.replace('Z', '+00:00'))
        return (current - last_seen).days > days
    except (ValueError, AttributeError):
        return False


def update_ignore_list(file_path: str, matched_ignores: List[str], current_timestamp: str) -> Dict:
    """
    Update the ignore list file.

    Args:
        file_path: Path to ignore list markdown file
        matched_ignores: List of ignore patterns that matched (stripped of thread IDs)
        current_timestamp: Current timestamp in ISO 8601 format

    Returns:
        Dict with update statistics: {updated_count, disabled_count, disabled_entries}
    """
    if not Path(file_path).exists():
        return {'updated_count': 0, 'disabled_count': 0, 'disabled_entries': []}

    with open(file_path, 'r') as f:
        lines = f.readlines()

    # Track statistics
    updated_count = 0
    disabled_count = 0
    disabled_entries = []

    # Process the file
    new_lines = []
    in_active_section = False
    in_disabled_section = False
    active_entries_to_process = []
    disabled_section_lines = []

    for line in lines:
        # Track which section we're in
        if line.strip() == '## Active Ignores':
            in_active_section = True
            in_disabled_section = False
            new_lines.append(line)
            continue
        elif line.strip() == '## Disabled Ignores (not seen in 30+ days)':
            in_active_section = False
            in_disabled_section = True
            # We'll add this section later after processing active entries
            continue
        elif line.startswith('# '):
            in_active_section = False
            in_disabled_section = False
            new_lines.append(line)
            continue

        # Process active ignore entries
        if in_active_section and line.strip().startswith('- "'):
            message_text, reason, last_seen = parse_ignore_entry(line.strip())
            if message_text:
                # Strip thread pattern from the stored message for comparison
                message_text_no_thread = re.sub(r'\s*\[thread:[^\]]+\]', '', message_text)

                # Check if this ignore matched in this run
                if message_text_no_thread in matched_ignores:
                    # Update last seen timestamp
                    new_line = f'- "{message_text}" - Reason: {reason} - Last seen: {current_timestamp}\n'
                    active_entries_to_process.append(('keep', new_line))
                    updated_count += 1
                else:
                    # Check if stale
                    if is_stale(last_seen, current_timestamp):
                        # Move to disabled section
                        disabled_entry = {
                            'message': message_text,
                            'reason': reason,
                            'last_seen': last_seen,
                            'disabled_on': current_timestamp
                        }
                        disabled_entries.append(disabled_entry)
                        disabled_section_lines.append(
                            f'<!-- Disabled on {current_timestamp} - Last seen: {last_seen} -->\n'
                        )
                        disabled_section_lines.append(
                            f'<!-- - "{message_text}" - Reason: {reason} -->\n'
                        )
                        disabled_count += 1
                        active_entries_to_process.append(('disable', None))
                    else:
                        # Keep as-is (not matched this run, but not stale yet)
                        active_entries_to_process.append(('keep', line))
            else:
                # Couldn't parse, keep as-is
                active_entries_to_process.append(('keep', line))
        elif in_disabled_section:
            # Collect existing disabled section lines
            disabled_section_lines.append(line)
        else:
            # Other lines (headers, empty lines outside sections)
            if not in_active_section and not in_disabled_section:
                new_lines.append(line)

    # Add active entries that weren't disabled
    new_lines.append('\n')  # Blank line after header
    for action, line in active_entries_to_process:
        if action == 'keep' and line:
            new_lines.append(line)

    # Add disabled section
    new_lines.append('\n## Disabled Ignores (not seen in 30+ days)\n')
    new_lines.append('\n')
    for line in disabled_section_lines:
        new_lines.append(line)

    # Write back to file atomically (write to temp, then replace)
    file_dir = os.path.dirname(file_path) or '.'
    with tempfile.NamedTemporaryFile(mode='w', dir=file_dir, delete=False, suffix='.tmp') as tmp:
        tmp.writelines(new_lines)
        tmp_path = tmp.name
    os.replace(tmp_path, file_path)

    return {
        'updated_count': updated_count,
        'disabled_count': disabled_count,
        'disabled_entries': disabled_entries
    }


def main():
    if len(sys.argv) != 4:
        print("Usage: python3 manage_ignore_list.py <ignore_list_file> <matched_ignores_json|--> <current_timestamp>",
              file=sys.stderr)
        print("  Use '-' to read matched ignores JSON from stdin", file=sys.stderr)
        sys.exit(1)

    ignore_list_file = sys.argv[1]

    # Read matched ignores from stdin if arg is '-', otherwise use arg as JSON string
    if sys.argv[2] == '-':
        matched_ignores_json = sys.stdin.read()
    else:
        matched_ignores_json = sys.argv[2]

    current_timestamp = sys.argv[3]

    # Parse matched ignores
    try:
        matched_ignores = json.loads(matched_ignores_json)
    except json.JSONDecodeError as e:
        print(f"Error parsing matched ignores JSON: {e}", file=sys.stderr)
        sys.exit(1)

    # Update the ignore list
    result = update_ignore_list(ignore_list_file, matched_ignores, current_timestamp)

    # Output results as JSON
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
