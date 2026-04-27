# Filter Slack Channel - Helper Scripts

Python helper scripts for the `/filter-slack-channel` skill.

## Scripts

### `filter_messages.py`

Filters and deduplicates Slack messages against an ignore list.

**Usage:**
```bash
# Via stdin (RECOMMENDED - handles large datasets, avoids ARG_MAX limits)
echo '<messages_json>' | python3 filter_messages.py - '<ignore_list_file>'

# Direct argument (for small datasets only)
python3 filter_messages.py '<messages_json>' '<ignore_list_file>'
```

**Input:**
- `messages_json`: JSON array of Slack messages in format `"[timestamp] message text [thread:xxx]"` (pass via stdin using `-` or as direct argument)
- `ignore_list_file`: Path to the ignore list markdown file

**Output:** (JSON to stdout)
```json
{
  "unique_messages": [
    {
      "text": "message text without thread",
      "timestamp": "1776926609.248229",
      "count": 3,
      "formatted_timestamp": "2026-04-23 10:30:09 UTC"
    }
  ],
  "ignored_count": 12,
  "total_count": 20,
  "unique_count": 8,
  "matched_ignores": ["pattern1", "pattern2"],
  "active_ignore_count": 5,
  "disabled_ignore_count": 2
}
```

**Features:**
- Thread ID stripping: Automatically strips `[thread:xxx]` patterns for matching
- Deduplication: Counts multiple occurrences of the same message
- Filtering: Removes messages matching active ignore patterns
- Tracking: Returns which ignore patterns matched (for timestamp updates)
- Smart sorting: Results sorted by count (descending), then timestamp (descending) - most frequent issues appear first

---

### `manage_ignore_list.py`

Updates ignore list timestamps and disables stale entries.

**Usage:**
```bash
# Via stdin (RECOMMENDED)
echo '<matched_ignores_json>' | python3 manage_ignore_list.py '<ignore_list_file>' - '<current_timestamp>'

# Direct argument (for small datasets only)
python3 manage_ignore_list.py '<ignore_list_file>' '<matched_ignores_json>' '<current_timestamp>'
```

**Input:**
- `ignore_list_file`: Path to the ignore list markdown file
- `matched_ignores_json`: JSON array of ignore patterns that matched (from filter_messages.py, pass via stdin using `-` or as direct argument)
- `current_timestamp`: Current timestamp in ISO 8601 format (e.g., "2026-04-23T07:19:54Z")

**Output:** (JSON to stdout)
```json
{
  "updated_count": 3,
  "disabled_count": 1,
  "disabled_entries": [
    {
      "message": "old message text",
      "reason": "original reason",
      "last_seen": "2026-03-15T10:30:00Z",
      "disabled_on": "2026-04-23T07:19:54Z"
    }
  ]
}
```

**Features:**
- Updates "Last seen" timestamps for matched ignores
- Automatically disables ignores not seen in 30+ days
- Moves disabled entries to the disabled section with metadata
- Preserves ignore list structure and formatting

---

### `detect_regressions.py`

Checks if a message matches any disabled ignore entries (regression detection).

**Usage:**
```bash
# Via stdin (RECOMMENDED)
echo '<message_text>' | python3 detect_regressions.py - '<ignore_list_file>' '<current_timestamp>'

# Direct argument
python3 detect_regressions.py '<message_text>' '<ignore_list_file>' '<current_timestamp>'
```

**Input:**
- `message_text`: Message text to check (pass via stdin using `-` or as direct argument)
- `ignore_list_file`: Path to the ignore list markdown file
- `current_timestamp`: Current timestamp in ISO 8601 format (e.g., "2026-04-23T07:19:54Z")

**Output:** (JSON to stdout)
```json
{
  "matches": [
    {
      "message": "matching message text",
      "reason": "original reason",
      "last_seen": "2026-03-15T10:30:00Z",
      "disabled_on": "2026-04-23T07:19:54Z",
      "days_since_disabled": 30,
      "days_since_last_seen": 69
    }
  ],
  "has_regression": true
}
```

**Features:**
- Detects if a previously-ignored message is appearing again after being disabled
- Provides context about when it was last seen and why it was originally ignored
- Helps identify regressions (old bugs returning)

---

### `update_channels_config.py`

Updates the lastChecked timestamp for a channel in channels.json.

**Usage:**
```bash
python3 update_channels_config.py '<channel_name_or_id>' '<new_timestamp>' '<config_file>'
```

**Input:**
- `channel_name_or_id`: Channel name (e.g., "#prod-alerts") or ID (e.g., "C123456")
- `new_timestamp`: New timestamp in ISO 8601 format (e.g., "2026-04-23T07:19:54Z")
- `config_file`: Path to channels.json

**Output:** (JSON to stdout)
```json
{
  "success": true,
  "updated_channel": "#prod-alerts",
  "new_last_checked": "2026-04-23T07:19:54Z",
  "old_last_checked": "2026-04-22T10:30:00Z",
  "error": null
}
```

**Features:**
- Atomic file updates (write to temp file, then rename)
- Prevents config file corruption
- Exits with error code 1 if update fails

---

### `ensure_ignore_list.py`

Auto-creates ignore list files if they don't exist.

**Usage:**
```bash
python3 ensure_ignore_list.py '<channel_name>' '<ignore_list_file_path>'
```

**Input:**
- `channel_name`: Channel name for the header (e.g., "#prod-alerts")
- `ignore_list_file_path`: Path where the file should be created

**Output:** (JSON to stdout)
```json
{
  "existed": false,
  "created": true,
  "file_path": "config/ignore-lists/prod-alerts.md"
}
```

**Features:**
- Creates file with proper markdown structure
- Safe idempotent operation (won't overwrite existing files)
- Returns status indicating whether file already existed or was created

---

## Example Workflow

```bash
# 1. Fetch messages from Slack (via MCP tool)
MESSAGES='["[1776926609.248229] @Sentry: error [thread:123]", ...]'

# 2. Filter and deduplicate (using stdin - RECOMMENDED)
FILTER_RESULT=$(echo "$MESSAGES" | python3 scripts/filter_messages.py - "config/ignore-lists/prod.md")

# 3. Extract matched ignores
MATCHED=$(echo "$FILTER_RESULT" | jq -c '.matched_ignores')

# 4. Update ignore list timestamps (using stdin - RECOMMENDED)
UPDATE_RESULT=$(echo "$MATCHED" | python3 scripts/manage_ignore_list.py "config/ignore-lists/prod.md" - "2026-04-23T07:19:54Z")

# 5. Check for regressions (using stdin - RECOMMENDED)
MESSAGE_TEXT="Error: Connection failed"
REGRESSION=$(echo "$MESSAGE_TEXT" | python3 scripts/detect_regressions.py - "config/ignore-lists/prod.md" "2026-04-23T07:19:54Z")

# 6. Display results
echo "$FILTER_RESULT" | jq '.unique_messages'
echo "Updated: $(echo "$UPDATE_RESULT" | jq '.updated_count')"
echo "Disabled: $(echo "$UPDATE_RESULT" | jq '.disabled_count')"
echo "Has regression: $(echo "$REGRESSION" | jq '.has_regression')"
```

## Testing

```bash
# Test filter_messages.py (using stdin)
echo '[
  "[1776926609.248229] Test message [thread:123]",
  "[1776926610.248229] Test message [thread:456]",
  "[1776926611.248229] Different message"
]' | python3 scripts/filter_messages.py - config/ignore-lists/example-channel.md

# Test manage_ignore_list.py (using stdin)
echo '["Health check passed"]' | python3 scripts/manage_ignore_list.py \
  config/ignore-lists/example-channel.md \
  - \
  "2026-04-23T08:00:00Z"

# Test detect_regressions.py (using stdin)
echo "Error: Connection failed" | python3 scripts/detect_regressions.py \
  - \
  config/ignore-lists/example-channel.md \
  "2026-04-23T08:00:00Z"

# Test update_channels_config.py
python3 scripts/update_channels_config.py \
  "#example-channel" \
  "2026-04-23T08:00:00Z" \
  config/channels.json

# Test ensure_ignore_list.py
python3 scripts/ensure_ignore_list.py \
  "#example-channel" \
  config/ignore-lists/example-channel.md
```
