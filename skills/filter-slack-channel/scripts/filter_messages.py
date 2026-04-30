#!/usr/bin/env python3
"""
Filter and deduplicate Slack messages against an ignore list.

Usage:
  python3 filter_messages.py <messages_json> <ignore_list_file>

Outputs JSON with:
  - unique_messages: Array of unique, non-ignored messages with metadata
  - ignored_count: Number of messages filtered out
  - total_count: Total messages processed
  - matched_ignores: Array of ignore patterns that matched (for timestamp updates)
"""

import sys
import json
import re
from datetime import datetime, timezone
from typing import List, Dict, Tuple, Set
from pathlib import Path


def normalize_message(text: str) -> str:
    """
    Normalize message text by stripping variable patterns.

    This includes:
    - Thread IDs: [thread:xxx]
    - Session IDs after "Mcp session not found: "

    Args:
        text: Message text to normalize

    Returns:
        Normalized message text
    """
    # Strip thread pattern
    text = re.sub(r'\s*\[thread:[^\]]+\]', '', text)

    # Strip session IDs from "Mcp session not found:" messages
    # Pattern: "Mcp session not found: <session_id>" → "Mcp session not found:"
    text = re.sub(r'(Mcp session not found:)\s*[^\s]+', r'\1', text)

    return text


def extract_message_parts(msg: str) -> Tuple[str, str, str]:
    """
    Extract timestamp and message text from Slack message format.

    Args:
        msg: Message in format "[timestamp] text [thread:xxx]"

    Returns:
        Tuple of (timestamp, full_text_with_thread, text_normalized)
    """
    match = re.match(r'\[([\d.]+)\] (.+)', msg)
    if match:
        timestamp = match.group(1)
        text = match.group(2)
        # Normalize text for matching
        text_normalized = normalize_message(text)
        return timestamp, text, text_normalized
    return '', msg, msg


def parse_ignore_list(file_path: str) -> Tuple[List[str], List[str]]:
    """
    Parse ignore list markdown file into active and disabled lists.

    Args:
        file_path: Path to the ignore list markdown file

    Returns:
        Tuple of (active_ignores, disabled_ignores) - both are message text only
    """
    if not Path(file_path).exists():
        return [], []

    with open(file_path, 'r') as f:
        content = f.read()

    active_ignores = []
    disabled_ignores = []

    # Split by sections
    sections = re.split(r'^## ', content, flags=re.MULTILINE)

    for section in sections:
        if section.startswith('Active Ignores'):
            # Extract active ignore patterns
            # Format: - "message text" - Reason: reason - Last seen: timestamp
            # Use greedy matching with specific timestamp pattern to handle messages containing " - Reason:"
            for line in section.split('\n'):
                match = re.match(r'^- "(.+)" - Reason: (.+) - Last seen: (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)$', line)
                if match:
                    ignore_text = match.group(1)
                    # Normalize ignore list entry (strip threads, session IDs, etc.)
                    ignore_text_normalized = normalize_message(ignore_text)
                    active_ignores.append(ignore_text_normalized)

        elif section.startswith('Disabled Ignores'):
            # Extract disabled ignore patterns
            # Format: <!-- - "message text" - Reason: reason -->
            for line in section.split('\n'):
                match = re.match(r'^<!-- - "(.+?)" - Reason:', line)
                if match:
                    ignore_text = match.group(1)
                    ignore_text_normalized = normalize_message(ignore_text)
                    disabled_ignores.append(ignore_text_normalized)

    return active_ignores, disabled_ignores


def filter_and_deduplicate(messages: List[str], active_ignores: List[str]) -> Tuple[List[Dict], int, Set[str]]:
    """
    Filter and deduplicate messages.

    Args:
        messages: List of Slack messages
        active_ignores: List of active ignore patterns (already stripped of thread IDs)

    Returns:
        Tuple of (unique_messages, ignored_count, matched_ignores)
        - unique_messages: List of dicts with {text, timestamp, count}
        - ignored_count: Number of messages filtered out
        - matched_ignores: Set of ignore patterns that matched messages
    """
    unique_messages = {}
    ignored_count = 0
    matched_ignores = set()

    for msg in messages:
        timestamp, full_text, stripped_text = extract_message_parts(msg)

        # Check if this message should be ignored
        is_ignored = False
        for ignore_pattern in active_ignores:
            if stripped_text == ignore_pattern:
                is_ignored = True
                ignored_count += 1
                matched_ignores.add(ignore_pattern)
                break

        if is_ignored:
            continue

        # Deduplicate by stripped text (thread-agnostic)
        if stripped_text not in unique_messages:
            unique_messages[stripped_text] = {
                'text': stripped_text,
                'timestamp': timestamp,
                'count': 0
            }
        unique_messages[stripped_text]['count'] += 1

    # Convert to sorted list (by count descending, then timestamp descending)
    # This puts the most frequent messages first, which are often the most important to address
    sorted_messages = sorted(
        unique_messages.values(),
        key=lambda x: (x['count'], x['timestamp']),
        reverse=True
    )

    return sorted_messages, ignored_count, matched_ignores


def format_timestamp(ts: str) -> str:
    """Convert Unix timestamp to human-readable UTC format."""
    try:
        dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
        return dt.strftime('%Y-%m-%d %H:%M:%S UTC')
    except (ValueError, TypeError):
        return ts


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 filter_messages.py <messages_json|--> <ignore_list_file>", file=sys.stderr)
        print("  Use '-' to read messages JSON from stdin", file=sys.stderr)
        sys.exit(1)

    # Read messages from stdin if first arg is '-', otherwise use arg as JSON string
    if sys.argv[1] == '-':
        messages_json = sys.stdin.read()
    else:
        messages_json = sys.argv[1]

    ignore_list_file = sys.argv[2]

    # Parse inputs
    try:
        messages = json.loads(messages_json)
    except json.JSONDecodeError as e:
        print(f"Error parsing messages JSON: {e}", file=sys.stderr)
        sys.exit(1)

    # Load ignore list
    active_ignores, disabled_ignores = parse_ignore_list(ignore_list_file)

    # Filter and deduplicate
    unique_messages, ignored_count, matched_ignores = filter_and_deduplicate(messages, active_ignores)

    # Add human-readable timestamps
    for msg in unique_messages:
        msg['formatted_timestamp'] = format_timestamp(msg['timestamp'])

    # Output results as JSON
    result = {
        'unique_messages': unique_messages,
        'ignored_count': ignored_count,
        'total_count': len(messages),
        'unique_count': len(unique_messages),
        'matched_ignores': list(matched_ignores),
        'active_ignore_count': len(active_ignores),
        'disabled_ignore_count': len(disabled_ignores)
    }

    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
