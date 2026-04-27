#!/usr/bin/env python3
"""
Ensure ignore list file exists, create if missing.

Usage:
  python3 ensure_ignore_list.py <channel_name> <ignore_list_file_path>

Outputs JSON with creation status.
"""

import sys
import json
import os
from pathlib import Path
from typing import Dict


def get_ignore_list_template(channel_name: str) -> str:
    """
    Generate ignore list file template.

    Args:
        channel_name: Channel name (e.g., "#prod-alerts")

    Returns:
        Markdown template for ignore list
    """
    return f"""# Ignore List for {channel_name}

## Active Ignores


## Disabled Ignores (not seen in 30+ days)

"""


def ensure_ignore_list(channel_name: str, file_path: str) -> Dict:
    """
    Ensure ignore list file exists, create if missing.

    Args:
        channel_name: Channel name for template header
        file_path: Path where ignore list file should exist

    Returns:
        Dict with existed/created status
    """
    path = Path(file_path)

    # Check if file already exists
    if path.exists():
        return {
            'existed': True,
            'created': False,
            'file_path': file_path
        }

    # Create parent directories if needed
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return {
            'existed': False,
            'created': False,
            'error': f'Failed to create parent directories: {e}',
            'file_path': file_path
        }

    # Create the file with template
    try:
        template = get_ignore_list_template(channel_name)
        with open(file_path, 'w') as f:
            f.write(template)

        return {
            'existed': False,
            'created': True,
            'file_path': file_path
        }

    except Exception as e:
        return {
            'existed': False,
            'created': False,
            'error': f'Failed to create file: {e}',
            'file_path': file_path
        }


def main():
    if len(sys.argv) != 3:
        print(
            "Usage: python3 ensure_ignore_list.py <channel_name> <ignore_list_file_path>",
            file=sys.stderr
        )
        sys.exit(1)

    channel_name = sys.argv[1]
    file_path = sys.argv[2]

    result = ensure_ignore_list(channel_name, file_path)

    print(json.dumps(result, indent=2))

    # Exit with error code if creation failed
    if 'error' in result:
        sys.exit(1)


if __name__ == '__main__':
    main()
