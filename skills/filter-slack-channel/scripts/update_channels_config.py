#!/usr/bin/env python3
"""
Update channel's lastChecked timestamp in channels.json.

Usage:
  python3 update_channels_config.py <channel_name_or_id> <new_timestamp> <config_file>

Outputs JSON with success status and updated details.
"""

import sys
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional


def validate_iso8601(timestamp: str) -> bool:
    """
    Validate that a timestamp is in ISO 8601 format.

    Args:
        timestamp: Timestamp string to validate

    Returns:
        True if valid ISO 8601, False otherwise
    """
    try:
        datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        return True
    except (ValueError, AttributeError):
        return False


def find_channel(channels: list, identifier: str) -> Optional[int]:
    """
    Find channel index by name or ID.

    Args:
        channels: List of channel objects
        identifier: Channel name (e.g., "#prod-alerts") or ID (e.g., "C123456")

    Returns:
        Index of matching channel, or None if not found
    """
    for i, channel in enumerate(channels):
        if channel.get('name') == identifier or channel.get('id') == identifier:
            return i

        # Also try without # prefix
        if identifier.startswith('#'):
            if channel.get('name') == identifier[1:]:
                return i

    return None


def update_channel_timestamp(
    config_file: str,
    channel_identifier: str,
    new_timestamp: str
) -> Dict:
    """
    Update channel's lastChecked timestamp.

    Args:
        config_file: Path to channels.json
        channel_identifier: Channel name or ID
        new_timestamp: New lastChecked timestamp in ISO 8601 format

    Returns:
        Dict with success status and details
    """
    # Validate inputs
    if not Path(config_file).exists():
        return {
            'success': False,
            'error': f'Config file not found: {config_file}'
        }

    if not validate_iso8601(new_timestamp):
        return {
            'success': False,
            'error': f'Invalid ISO 8601 timestamp: {new_timestamp}'
        }

    # Read config file
    try:
        with open(config_file, 'r') as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        return {
            'success': False,
            'error': f'Invalid JSON in config file: {e}'
        }

    # Find channel
    channels = config.get('channels', [])
    channel_index = find_channel(channels, channel_identifier)

    if channel_index is None:
        return {
            'success': False,
            'error': f'Channel not found: {channel_identifier}'
        }

    # Update timestamp
    channel = channels[channel_index]
    old_timestamp = channel.get('lastChecked')
    channel['lastChecked'] = new_timestamp

    # Write atomically (write to temp file, then rename)
    try:
        # Create temp file in same directory to ensure atomic rename works
        config_dir = os.path.dirname(config_file)
        with tempfile.NamedTemporaryFile(
            mode='w',
            dir=config_dir,
            delete=False,
            suffix='.tmp'
        ) as tmp_file:
            json.dump(config, tmp_file, indent=2)
            tmp_file.write('\n')  # Add trailing newline
            tmp_path = tmp_file.name

        # Atomic rename
        os.replace(tmp_path, config_file)

        return {
            'success': True,
            'updated_channel': channel.get('name'),
            'new_last_checked': new_timestamp,
            'old_last_checked': old_timestamp,
            'error': None
        }

    except Exception as e:
        # Clean up temp file if it exists
        if 'tmp_path' in locals() and os.path.exists(tmp_path):
            os.unlink(tmp_path)

        return {
            'success': False,
            'error': f'Failed to write config file: {e}'
        }


def main():
    if len(sys.argv) != 4:
        print(
            "Usage: python3 update_channels_config.py <channel_name_or_id> <new_timestamp> <config_file>",
            file=sys.stderr
        )
        sys.exit(1)

    channel_identifier = sys.argv[1]
    new_timestamp = sys.argv[2]
    config_file = sys.argv[3]

    result = update_channel_timestamp(config_file, channel_identifier, new_timestamp)

    print(json.dumps(result, indent=2))

    # Exit with error code if update failed
    if not result.get('success'):
        sys.exit(1)


if __name__ == '__main__':
    main()
