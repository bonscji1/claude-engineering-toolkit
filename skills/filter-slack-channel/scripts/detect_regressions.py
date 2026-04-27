#!/usr/bin/env python3
"""
Detect regressions by checking if a message matches any disabled ignore entries.

Usage:
  python3 detect_regressions.py <message_text> <ignore_list_file> <current_timestamp>

Outputs JSON with matches from the disabled ignores section.
"""

import sys
import json
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple


def parse_disabled_ignores(file_path: str) -> List[Tuple[str, str, str, str]]:
    """
    Parse disabled ignores from the markdown file.

    Args:
        file_path: Path to the ignore list markdown file

    Returns:
        List of tuples: (message_text, reason, disabled_on, last_seen)
    """
    if not Path(file_path).exists():
        return []

    with open(file_path, 'r') as f:
        content = f.read()

    disabled_ignores = []

    # Split by sections
    sections = re.split(r'^## ', content, flags=re.MULTILINE)

    for section in sections:
        if section.startswith('Disabled Ignores'):
            lines = section.split('\n')
            i = 0
            while i < len(lines):
                # Look for metadata line
                metadata_match = re.match(
                    r'^<!-- Disabled on (.+?) - Last seen: (.+?) -->$',
                    lines[i].strip()
                )
                if metadata_match and i + 1 < len(lines):
                    disabled_on = metadata_match.group(1)
                    last_seen = metadata_match.group(2)

                    # Next line should have the message
                    # Use greedy matching to handle messages containing " - Reason:"
                    message_match = re.match(
                        r'^<!-- - "(.+)" - Reason: (.+) -->$',
                        lines[i + 1].strip()
                    )
                    if message_match:
                        message_text = message_match.group(1)
                        reason = message_match.group(2)

                        # Strip thread IDs for matching
                        message_text_no_thread = re.sub(
                            r'\s*\[thread:[^\]]+\]',
                            '',
                            message_text
                        )

                        disabled_ignores.append((
                            message_text_no_thread,
                            reason,
                            disabled_on,
                            last_seen
                        ))
                        i += 2
                        continue
                i += 1

    return disabled_ignores


def calculate_days_ago(timestamp_iso: str, current_iso: str) -> int:
    """
    Calculate days between two ISO 8601 timestamps.

    Args:
        timestamp_iso: Earlier timestamp
        current_iso: Later timestamp (current time)

    Returns:
        Number of days between timestamps
    """
    try:
        earlier = datetime.fromisoformat(timestamp_iso.replace('Z', '+00:00'))
        later = datetime.fromisoformat(current_iso.replace('Z', '+00:00'))
        return (later - earlier).days
    except (ValueError, AttributeError):
        return 0


def detect_regressions(
    message_text: str,
    ignore_list_file: str,
    current_timestamp: str
) -> Dict:
    """
    Check if message matches any disabled ignore entries.

    Args:
        message_text: Message to check (will be stripped of thread IDs)
        ignore_list_file: Path to the ignore list markdown file
        current_timestamp: Current timestamp in ISO 8601 format

    Returns:
        Dict with matches and has_regression flag
    """
    # Strip thread IDs from the input message
    message_no_thread = re.sub(r'\s*\[thread:[^\]]+\]', '', message_text)

    # Parse disabled ignores
    disabled_ignores = parse_disabled_ignores(ignore_list_file)

    # Find matches
    matches = []
    for msg_text, reason, disabled_on, last_seen in disabled_ignores:
        if msg_text == message_no_thread:
            matches.append({
                'message': msg_text,
                'reason': reason,
                'last_seen': last_seen,
                'disabled_on': disabled_on,
                'days_since_disabled': calculate_days_ago(disabled_on, current_timestamp),
                'days_since_last_seen': calculate_days_ago(last_seen, current_timestamp)
            })

    return {
        'matches': matches,
        'has_regression': len(matches) > 0
    }


def main():
    if len(sys.argv) != 4:
        print(
            "Usage: python3 detect_regressions.py <message_text|--> <ignore_list_file> <current_timestamp>",
            file=sys.stderr
        )
        print("  Use '-' to read message text from stdin", file=sys.stderr)
        sys.exit(1)

    # Read message from stdin if arg is '-', otherwise use arg as message text
    if sys.argv[1] == '-':
        message_text = sys.stdin.read().strip()
    else:
        message_text = sys.argv[1]

    ignore_list_file = sys.argv[2]
    current_timestamp = sys.argv[3]

    result = detect_regressions(message_text, ignore_list_file, current_timestamp)

    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
