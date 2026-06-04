---
name: filter-slack-channel
description: Filter and manage Slack alert messages with channel-specific ignore lists
---

Filter Slack alert messages from configured channels. $ARGUMENTS

This skill helps you manage alert fatigue by filtering out known non-actionable messages while maintaining a knowledge repository of why messages are ignored.

## Helper Scripts

This skill uses Python helper scripts for deterministic operations (see `scripts/README.md` for details):
- `scripts/filter_messages.py` - Filters and deduplicates messages against ignore lists with wildcard pattern support
- `scripts/manage_ignore_list.py` - Updates timestamps and disables stale ignore entries
- `scripts/detect_regressions.py` - Checks if messages match disabled ignore entries
- `scripts/update_channels_config.py` - Updates lastChecked timestamps in channels.json
- `scripts/ensure_ignore_list.py` - Auto-creates ignore list files if missing

These scripts handle complex logic like thread ID stripping, session ID normalization, wildcard pattern matching, deduplication, regression detection, and atomic JSON updates, making the workflow cleaner and more maintainable.

**IMPORTANT: Data handling strategy to avoid escaping issues and reduce token usage**

For **large data from MCP tools** (Slack messages, etc.):
- Always write to temp files immediately after fetching
- Avoids bash escaping issues with complex JSON
- Reduces token usage (data appears in context only once)
- Use temp files in `/tmp/` with descriptive names

For **small data between scripts** (extracted fields, etc.):
- Use stdin/pipes for efficiency
- Safe when data is small and controlled

Scripts that support stdin (use `-` to read from stdin):
- `filter_messages.py` - First argument: messages JSON (can be large array)
- `manage_ignore_list.py` - Second argument: matched ignores JSON
- `detect_regressions.py` - First argument: message text

Example pattern:
```bash
# STANDARD PATTERN - Large MCP data → temp file → stdin to script
TEMP_FILE="/tmp/slack_messages_$$.json"
cat > "$TEMP_FILE" << 'EOF'
[...large JSON from MCP tool...]
EOF
FILTER_RESULT=$(cat "$TEMP_FILE" | python3 scripts/filter_messages.py - ignore-list.md)
rm -f "$TEMP_FILE"  # Clean up

# BACKUP PATTERN - Small intermediate data can use stdin directly
MATCHED_IGNORES=$(echo "$FILTER_RESULT" | jq -c '.matched_ignores')
echo "$MATCHED_IGNORES" | python3 scripts/manage_ignore_list.py ignore.md - "2026-04-24T07:00:00Z"
```

## Workflow

### 1. Load Configuration

Read the skill's configuration files:
- `skills/filter-slack-channel/config/channels.json` - list of channels to monitor
- `skills/filter-slack-channel/config/ignore-lists/<channel-name>.md` - ignore list for each channel

If `channels.json` doesn't exist, show an error with setup instructions:
```
No channels configured. Create skills/filter-slack-channel/config/channels.json with:
{
  "workspaceDomain": "mycompany",
  "channels": [
    {
      "name": "#your-channel",
      "id": "C123456",
      "lastChecked": "2026-01-01T00:00:00Z",
      "ignoreListFile": "your-channel.md"
    }
  ]
}

Fields:
- workspaceDomain: Your Slack workspace subdomain (e.g., "mycompany" for mycompany.slack.com)
  - Optional: If omitted, message links will not be generated
  - Find your workspace domain from your Slack URL: https://WORKSPACEDOMAIN.slack.com/
- name: Channel name with # prefix
- id: Channel ID (find using Slack MCP list_channels tool or from channel URL)
- lastChecked: ISO 8601 timestamp of last check
- ignoreListFile: Filename in config/ignore-lists/ for this channel's ignore list
```

### 1.5. Get Workspace Domain

Fetch the Slack workspace domain needed for message links.

**Approach 1: Check channels.json for workspaceDomain field**

```bash
WORKSPACE_DOMAIN=$(jq -r '.workspaceDomain // empty' skills/filter-slack-channel/config/channels.json 2>/dev/null)
```

**Approach 2 (fallback): Try Slack MCP whoami**

If not found in config, try the Slack MCP:

```bash
if [ -z "$WORKSPACE_DOMAIN" ]; then
  # Try whoami tool - some Slack MCP implementations may provide team info
  if WHOAMI_RESULT=$(echo '{}' | mcp__slack__whoami 2>/dev/null); then
    # Try different possible response structures
    WORKSPACE_DOMAIN=$(echo "$WHOAMI_RESULT" | jq -r '.team.domain // .domain // empty' 2>/dev/null)
  fi
fi
```

**Error handling:**
- If both approaches fail, set `WORKSPACE_DOMAIN=""` and continue without links
- Links will only be added to messages if workspace domain is available

**To configure workspace domain:**

Add `workspaceDomain` field to the root of `channels.json`:

```json
{
  "workspaceDomain": "mycompany",
  "channels": [
    {
      "name": "#your-channel",
      "id": "C123456",
      "lastChecked": "2026-01-01T00:00:00Z",
      "ignoreListFile": "your-channel.md"
    }
  ]
}
```

**Output:** Workspace domain string (e.g., "mycompany" for mycompany.slack.com) or empty string if unavailable

**Rationale:**
- Configuration-based approach is most reliable and explicit
- Slack MCP fallback provides convenience when available  
- Graceful degradation ensures skill works even without links

### 2. Parse Arguments

Parse `$ARGUMENTS` to determine what to check:

**No arguments**: Check all channels since their last check time
**Time duration** (e.g., `2h`, `30m`, `1d`, `24h`): Check all channels for the specified duration, ignoring `lastChecked`
**Channel name** (e.g., `#prod-alerts` or `prod-alerts`): Check only that specific channel since last check
**Channel + duration** (e.g., `#prod-alerts 2h`): Check specific channel for specified duration

### 3. Determine Time Window

For each channel to check:
- If time duration specified: calculate `since = now - duration`
- Otherwise: use `since = channel.lastChecked` from channels.json
- Convert to Unix timestamp for Slack API

Duration parsing:
- `Xh` = X hours ago
- `Xm` = X minutes ago  
- `Xd` = X days ago

### 4. Process Each Channel Sequentially

**IMPORTANT: Process channels ONE AT A TIME, fully completing each channel before starting the next.**

For each channel in the list, complete ALL steps (a-f) below for that channel before moving to the next channel. Do NOT fetch all channels upfront, do NOT process multiple channels in parallel.

**CRITICAL: Token Budget Check Before Proceeding**

Before starting each channel, check your token budget to ensure you can complete the interactive workflow:

1. **Calculate remaining tokens**: `200,000 - tokens_used`
2. **Decision logic:**
   - If remaining > 30,000: Continue with normal interactive workflow
   - If remaining < 30,000: Inform user and ask how to proceed:
     ```
     ⚠️ Token budget is low (X,XXX remaining out of 200,000).
     
     Options:
     1. Continue with remaining channels (may need to be concise)
     2. Stop here and resume later
     3. Skip pagination and just update timestamps
     
     Which would you prefer?
     ```

3. **Do NOT:**
   - Skip the interactive workflow without asking first
   - Auto-complete channels to "save tokens"
   - Make optimization decisions on your own
   - Assume context is limited when you have 50k+ tokens remaining

**Why this matters:** The interactive pagination is the PRIMARY PURPOSE of this skill. Skipping it defeats the entire point. Only optimize when truly necessary.

For each channel, follow these steps:

#### a) Fetch Messages

Use the `mcp__slack__get_channel_history` tool to fetch channel history.

Fetch parameters:
- `channel_id`: channel ID from channels.json
- `oldest`: timestamp in ISO 8601 format or Unix timestamp (from step 3)
- `limit`: 1000 messages (should be enough for most alert channels)
- `include_threads`: false (don't fetch thread replies)

**IMPORTANT: Save MCP result to temp file immediately**

The Slack MCP tool returns large JSON. To avoid escaping issues and reduce token usage, write the full result to a temp file immediately:

```bash
# Save the full MCP result to temp file (use $$ for unique PID to avoid collisions)
TEMP_FILE="/tmp/slack_result_${CHANNEL_ID}_$$.json"
cat > "$TEMP_FILE" << 'EOF'
{"result": [...messages from Slack MCP...]}
EOF
```

The temp file will be read and processed in the next step, then cleaned up after the channel is complete.

If the Slack MCP server is not available, show a helpful error:
```
Slack MCP server not connected. Setup instructions:
1. Install: https://github.com/bonscji1/slack-mcp
2. Run setup: python3 slack-mcp/scripts/setup-slack-mcp.py
3. Follow the guided setup to extract tokens and configure Claude Code
4. Required scopes: channels:history, channels:read
```

#### b) Load Ignore List

**CRITICAL: Each channel has its OWN ignore list file. Ignore lists MUST NOT be shared between channels.**

For the current channel being processed:
1. Get the ignore list filename from the channel configuration:
   - Read `ignoreListFile` field from the channel object in channels.json
   - This field specifies the filename (e.g., "prod-alerts.md")

2. Build the full path: `skills/filter-slack-channel/config/ignore-lists/{channel.ignoreListFile}`

3. **Ensure the file exists** by calling the helper script:
   ```bash
   ENSURE_RESULT=$(python3 skills/filter-slack-channel/scripts/ensure_ignore_list.py "$CHANNEL_NAME" "$IGNORE_LIST_PATH")
   ```
   - This auto-creates the file with proper structure if it doesn't exist
   - Prevents errors when processing new channels

4. **Parse the markdown file into two lists:**

   **Active Ignores** (under `## Active Ignores` heading):
   - Format: `- "message text" - Reason: reason - Last seen: 2026-04-22T13:48:26Z`
   - Extract: message text, reason, last seen timestamp
   - These are used for filtering messages
   
   **Disabled Ignores** (under `## Disabled Ignores (not seen in 30+ days)` heading):
   - Format: `<!-- Disabled on 2026-04-22T13:48:26Z - Last seen: 2026-03-15T10:30:00Z -->`
   - Next line: `<!-- - "message text" - Reason: original reason -->`
   - Extract: message text, reason, disabled date, last seen date
   - These are NOT used for filtering but are checked for regressions when adding new ignores

**Thread ID Handling:**
- By default, thread IDs are IGNORED during matching
- Before comparing messages, strip `[thread:...]` patterns from both the message and ignore list entries
- This allows one ignore entry to match the same error across different threads
- Example: Ignore entry `"Error: Connection failed"` will match both:
  - `"Error: Connection failed [thread:12345]"`
  - `"Error: Connection failed [thread:67890]"`
  - `"Error: Connection failed"`

**Wildcard Pattern Support:**
- Use `*` in ignore patterns to match any characters at that position
- Wildcards enable flexible matching for variable content (session IDs, record IDs, service names, etc.)
- The filter script converts wildcard patterns to regex for matching

**Common use cases:**

1. **Ignore variable IDs/tokens:**
   ```
   "Session expired: *"
   ```
   Matches:
   - `"Session expired: abc123def456"`
   - `"Session expired: xyz789uvw"`
   - `"Session expired: <any-session-id>"`

2. **Ignore errors from any service:**
   ```
   "@Monitor: [*] Database connection timeout"
   ```
   Matches:
   - `"@Monitor: [auth-service] Database connection timeout"`
   - `"@Monitor: [payment-service] Database connection timeout"`
   - `"@Monitor: [api-gateway] Database connection timeout"`

3. **Multiple wildcards in one pattern:**
   ```
   "Request * failed with status code *"
   ```
   Matches any request ID AND any status code in the error message.

4. **Combine exact matching with wildcards:**
   ```
   "@Monitor: [*] Metric already registered: http_requests_total"
   ```
   - Service: wildcard (`[*]`) - matches any service name
   - Error message: exact - only matches this specific metric registration
   - Metric name: exact (`http_requests_total`) - only matches this metric

**Important notes:**
- Wildcards match greedily (as much as possible)
- Use wildcards strategically - be as specific as possible to avoid over-filtering
- Exact matches (no wildcards) are more efficient than wildcard patterns
- When adding ignores, decide which parts should be wildcarded based on what varies vs. what's constant

#### c) Filter and Deduplicate Messages

Use the `filter_messages.py` helper script to process messages from the temp file:

```bash
# Read MCP result from temp file, extract messages array, pipe to filter script
FILTER_RESULT=$(python3 -c "import sys, json; data=json.load(open('$TEMP_FILE')); print(json.dumps(data['result']))" | python3 skills/filter-slack-channel/scripts/filter_messages.py - "$IGNORE_LIST_FILE")
```

This approach:
1. Reads the temp file created in step 4a
2. Extracts just the messages array from `{"result": [...messages...]}`
3. Pipes it to the filter script via stdin

**Input:**
- `$TEMP_FILE`: Temp file with full MCP result saved in step 4a
- `$IGNORE_LIST_FILE`: Path to the channel's ignore list (e.g., `skills/filter-slack-channel/config/ignore-lists/prod-alerts.md`)

**Output:** JSON with:
- `unique_messages`: Array of unique, non-ignored messages with text, timestamp, count, formatted_timestamp
- `ignored_count`: Number of messages filtered out
- `total_count`: Total messages processed
- `unique_count`: Number of unique messages
- `matched_ignores`: Array of ignore patterns that matched (needed for timestamp updates)
- `active_ignore_count`: Number of active ignore patterns
- `disabled_ignore_count`: Number of disabled ignore patterns

**What the script does:**
- Normalizes messages by stripping variable patterns:
  - Strips `[thread:...]` patterns from messages and ignore entries
  - Normalizes variable IDs in common patterns (session IDs, request IDs, etc.)
- Supports wildcard patterns (`*`) for flexible matching of variable content
- Deduplicates messages (counts multiple occurrences)
- Filters out messages matching active ignore patterns (exact or wildcard)
- Tracks which ignore patterns matched (for "Last seen" timestamp updates)

#### d) Display Results and Interactive Add to Ignore List

**This step combines displaying messages and adding to ignore list in a streamlined, paginated interface.**

Show results for this channel:

```
## <channel-name> (<unique-count> unique, <total-count> total, <ignored-count> ignored)
Ignore list: config/ignore-lists/<sanitized-channel-name>.md (<X> patterns)
```

If no new actionable messages:
```
✓ No new actionable messages for <channel-name>
```

If there are messages to show, display them in **pages of 20 messages** with an interactive menu:

**IMPORTANT:** Display messages in pages, sorted by occurrence count (most frequent first), then by timestamp (most recent first).

**Link Construction:**

For each message, construct a clickable Slack link if workspace domain is available:

```bash
# Extract message data from FILTER_RESULT JSON
MESSAGE_TEXT="..."      # From unique_messages[i].text
UNIX_TIMESTAMP="..."    # From unique_messages[i].timestamp (e.g., "1777290266.083699")
FORMATTED_TIME="..."    # From unique_messages[i].formatted_timestamp
COUNT="..."             # From unique_messages[i].count

# Convert timestamp: 1777290266.083699 → p1777290266083699
PERMALINK_TS=$(echo "$UNIX_TIMESTAMP" | sed 's/\.//g; s/^/p/')

# Build Slack message URL
if [ -n "$WORKSPACE_DOMAIN" ]; then
  SLACK_URL="https://${WORKSPACE_DOMAIN}.slack.com/archives/${CHANNEL_ID}/${PERMALINK_TS}?cid=${CHANNEL_ID}"
  # Display with link on separate line
  echo "N. [$MESSAGE_TEXT] (appeared $COUNT times)"
  echo "First seen: $FORMATTED_TIME"
  echo "Link: $SLACK_URL"
  echo ""  # Empty line between messages
else
  # Fallback to plain text if workspace domain unavailable (current format)
  echo "N. \"$MESSAGE_TEXT\" (appeared $COUNT times)"
  echo "   First seen: $FORMATTED_TIME"
  echo ""  # Empty line between messages
fi
```

**Display format:**
- **With workspace domain:**
  ```
  N. [message text] (appeared X times)
  First seen: YYYY-MM-DD HH:MM:SS UTC
  Link: slack_url
  ```
- **Without workspace domain:** `N. "message text" (appeared X times)` (current format with indented timestamp)

**Format per page:**
```
Issues (Page N of M):

1. [@Monitor: [payment-service] Database connection timeout] (appeared 15 times)
First seen: 2026-04-22 10:30:15 UTC
Link: https://mycompany.slack.com/archives/C025EM2K133/p1777290266083699?cid=C025EM2K133

2. [@Monitor: [auth-service] Invalid API key in request] (appeared 3 times)
First seen: 2026-04-22 11:45:22 UTC
Link: https://mycompany.slack.com/archives/C025EM2K133/p1777285841894789?cid=C025EM2K133

... (up to 20 messages per page)

---
To add issues to ignore list, type in the text field:
  Format: <number>. <reason>
  Example: 1. testing noise, not production
  Multiple: 1. testing noise, 3. known issue tracked in JIRA-123

Wildcard tip: After adding, you can manually edit the ignore list to use wildcards:
  - Replace variable parts with * (session IDs, record IDs, etc.)
  - Example: "Session expired: abc123" → "Session expired: *"
  - Example: "@Monitor: [payment-service] Error" → "@Monitor: [*] Error" (any service)
```

**Note:**
- Message text is wrapped in square brackets `[...]` (not Markdown link syntax)
- Link appears on separate line with "Link: " prefix
- No indentation on "First seen:" and "Link:" lines
- Empty line between messages for readability

**Do not truncate long messages** - show the full text even if it's multiple lines. The user needs complete information to decide if it should be ignored.

**User interaction flow:**

1. Display first page (messages 1-20)
2. Use `AskUserQuestion` with 4 options:
   ```json
   {
     "questions": [{
       "question": "What would you like to do?",
       "header": "Actions",
       "options": [
         {
           "label": "Choose issues to ignore",
           "description": "Type command: '1. reason, 3. other reason' or '1. testing, 5. noise'"
         },
         {
           "label": "Next page",
           "description": "Show next 20 messages"
         },
         {
           "label": "Previous page",
           "description": "Show previous 20 messages"
         },
         {
           "label": "Finished",
           "description": "Done with this channel"
         }
       ],
       "multiSelect": false
     }]
   }
   ```
   - The "Other" field is always available for typing commands
   - "Choose issues to ignore" option guides users to use Other field
   - User can select navigation options OR type in Other field

3. Parse user response:
   - **"Choose issues to ignore"** or **Other field with text**: Parse for number+reason pairs
     - Extract using regex: `(\d+)\.\s*([^,\n]+?)(?:,|\n|$)`
     - For each: check regression, add to ignore list with specified reason
   - **"Next page"**: Display next page (messages 21-40)
   - **"Previous page"**: Display previous page
   - **"Finished"**: Complete this channel, move to step e

4. After processing additions, show confirmation:
   ```
   ✓ Added N message(s) to ignore list
   ```
   Then re-display current page and ask for next action

5. Continue until user selects "Finished"

**Implementation details:**

**Pagination logic:**
- Page size: 20 messages
- Track current page number (starts at 1)
- Total pages: `ceil(total_messages / 20)`
- Display range: messages `[(page-1)*20 + 1]` to `[min(page*20, total_messages)]`

**Parsing user input:**

User can either:
- **Select "Choose issues to ignore"** → Response will be in `annotations` or parsed from selection
- **Select "Next page"** → Show next page
- **Select "Previous page"** → Show previous page  
- **Select "Finished"** → Exit loop, proceed to step e
- **Type in "Other" field** → Parse as command text

**Re-prompting behavior:**
- If user selects "Choose issues to ignore" WITHOUT typing text in the Other field, prompt again with a clearer request for the specific command format
- This is expected behavior to ensure clear intent - better to re-prompt than assume what the user wants to ignore
- Use a second `AskUserQuestion` with options: "Type command below" and "Skip - don't add any"
- This two-step interaction provides better UX than failing silently or showing an error

Expected text patterns (from "Choose issues" selection or Other field):
- Single: `1. testing noise`
- Multiple (comma-separated): `1. testing noise, 3. known issue`
- Multiple (separate lines): 
  ```
  1. testing noise
  3. known issue
  ```

**Parsing algorithm:**
1. Check which option was selected:
   - If "Next page" → increment page (max: total_pages), show page, continue loop
   - If "Previous page" → decrement page (min: 1), show page, continue loop
   - If "Finished" → exit loop, proceed to step e
   - If "Choose issues to ignore" OR Other field has text → parse for number+reason pairs
2. For number+reason pairs:
   - Regex: `(\d+)\.\s*([^,\n]+?)(?:,|\n|$)`
   - This extracts: (number, reason) tuples
   - Trim whitespace from each reason
3. **Pattern detection** (when multiple messages selected):
   - If 3+ messages are selected, analyze their text for common patterns
   - Common patterns to detect:
     - Same prefix/suffix with variable content (e.g., deployment notifications with different commit hashes)
     - Same error type with different IDs/values (e.g., "record 'X' not found" where X varies)
     - Same service name with different metadata (e.g., Kafka disconnections with different broker IDs)
   - If a strong pattern is detected (80%+ similarity in structure):
     - Show the detected pattern with wildcards replacing variable parts
     - Ask user: "These messages follow a similar pattern. Would you like to create a wildcarded ignore entry instead?"
     - Options: "Use wildcard pattern" | "Add each individually"
     - If "Use wildcard pattern": create single wildcarded entry with a combined reason
     - If "Add each individually": continue with normal flow
   - Pattern detection examples:
     - Messages: `"@: :green_jenkins_circle: SaaS file *notifications-test* deployment to environment *insights-production*: Success - ...commit/abc123..."`, `"@: :green_jenkins_circle: SaaS file *notifications-test* deployment to environment *insights-production*: Success - ...commit/def456..."`
     - Suggested pattern: `"@: :green_jenkins_circle: SaaS file *notifications-test* deployment to environment *insights-production*: Success - *"`
     - Reason: Combine all user-provided reasons, e.g., "Deployment success notifications are informational noise"
4. For each (number, reason) pair:
   - Validate number is in range [1, total_messages]
   - Get message text from the full message list (1-based index)
   - Strip `[thread:...]` from message text
   - Check for regression:
     ```bash
     echo "$MESSAGE_TEXT" | python3 scripts/detect_regressions.py - "$IGNORE_LIST_FILE" "$CURRENT_TIMESTAMP"
     ```
   - If regression detected (`has_regression: true`):
     - Show warning: "⚠️ Issue #N was previously ignored (last seen: [date], disabled [X] days ago)"
     - Show: "Original reason: [reason from regression match]"
     - User already specified new reason, so add with new reason
   - Add to ignore list:
     - Format: `- "message text without thread" - Reason: reason - Last seen: CURRENT_TIMESTAMP`
     - Use Edit tool to append to Active Ignores section
5. Show confirmation:
   ```
   ✓ Added N issue(s) to ignore list
   ```
6. Re-display current page with updated numbering (if any were from this page)
7. Ask for next command (loop back to step 2)

#### e) Update Active Ignore Timestamps and Disable Stale Entries

After user finishes adding ignores (or if there are no messages), use the `manage_ignore_list.py` helper script to maintain the ignore list:

```bash
# Pass matched ignores JSON via stdin (use '-' as second argument)
UPDATE_RESULT=$(echo "$MATCHED_IGNORES_JSON" | python3 skills/filter-slack-channel/scripts/manage_ignore_list.py \
  "$IGNORE_LIST_FILE" \
  - \
  "$CURRENT_TIMESTAMP")
```

**Input:**
- `$IGNORE_LIST_FILE`: Path to the channel's ignore list
- `$MATCHED_IGNORES_JSON`: JSON array from `filter_messages.py` output (`.matched_ignores` field, passed via stdin)
- `$CURRENT_TIMESTAMP`: Current timestamp in ISO 8601 format (e.g., "2026-04-23T07:19:54Z")

**Output:** JSON with:
- `updated_count`: Number of ignores whose timestamps were updated
- `disabled_count`: Number of ignores moved to disabled section
- `disabled_entries`: Array of disabled entries with details (message, reason, last_seen, disabled_on)

**What the script does:**
- Updates "Last seen" timestamps for all matched ignore patterns
- Identifies stale ignores (not matched and not seen in 30+ days)
- Moves stale ignores to the "Disabled Ignores" section with metadata
- Preserves ignore list structure and formatting

**Report to user:**
- If `disabled_count > 0`: Show "ℹ️ Disabled X ignore(s) not seen in 30+ days"

#### f) Update Last Checked

**CRITICAL: This step can ONLY be executed after the user explicitly selects "Finished" in the AskUserQuestion menu.**

**Requirements to proceed:**
1. User MUST have selected the "Finished" option in the interactive menu
2. You CANNOT update lastChecked without user confirmation
3. If you haven't shown the user the messages and gotten "Finished", you CANNOT proceed to this step

**Do NOT:**
- Auto-complete the channel without showing messages
- Update lastChecked because you think the user is done
- Skip to this step to "optimize" or "save tokens"

**After user selects "Finished"**, update the channel's `lastChecked` timestamp in channels.json using the helper script.

This marks the channel as processed. Then move to the next channel (if any) and repeat steps a-f.

```bash
UPDATE_CONFIG_RESULT=$(python3 skills/filter-slack-channel/scripts/update_channels_config.py \
  "$CHANNEL_NAME" \
  "$CURRENT_TIMESTAMP" \
  "skills/filter-slack-channel/config/channels.json")
```

**Input:**
- `$CHANNEL_NAME`: Channel name or ID (e.g., "#prod-alerts" or "C123456")
- `$CURRENT_TIMESTAMP`: Current timestamp in ISO 8601 format with Z timezone, including hours, minutes, and seconds (e.g., "2026-04-22T14:35:42Z")
- Config file path: `skills/filter-slack-channel/config/channels.json`

**Output:** JSON with success status. If `success: false`, show error to user.

The script handles atomic updates to prevent config file corruption.

**Cleanup:**

After updating the config, clean up the temp file to avoid leaving sensitive Slack data on disk:

```bash
rm -f "$TEMP_FILE"
```

Then move to the next channel (if any) and repeat steps a-f.

**After processing all channels, move to the self-improvement review section. Do not show a processing summary.**

## Error Handling

**CRITICAL: When any helper script or tool fails, IMMEDIATELY show the error to the user. Do NOT silently retry, work around, or continue as if nothing happened.**

Error handling approach:
1. If a tool/script returns an error or non-zero exit code, STOP
2. Show the full error message to the user
3. Explain what failed and at what step
4. Ask the user how to proceed (skip channel, abort, retry, etc.)
5. Do NOT attempt to "fix" the error silently

Specific error scenarios:
- **Slack MCP not available**: Show setup instructions (see step 4a), do not attempt to continue
- **Channel not found in Slack**: Show error to user, ask whether to skip or abort
- **Invalid channel ID**: Show error with suggestion to verify ID in channels.json
- **Ignore list file read error**: Show error, explain impact, ask user to proceed or fix
- **channels.json missing**: Show setup instructions (see step 1), do not create file automatically
- **Invalid time duration format**: Show error with examples (2h, 30m, 1d), do not guess
- **Permission errors writing to config files**: Show clear error message, explain what needs permission
- **Helper script failure**: Show full script output (stdout + stderr), explain which script failed and why
- **JSON parsing error**: Show the parsing error and what was being parsed, do not retry with modified input

## Important Notes

- **Paginated display**: Show messages 20 at a time for better readability. Don't overwhelm the user with 100+ messages at once.
- **Display full messages**: Don't truncate message text (long messages are OK). Users need complete information to decide if it should be ignored.
- **Menu-driven interaction**: Use `AskUserQuestion` with 4 options: "Choose issues to ignore" | "Next page" | "Previous page" | "Finished". The "Other" field is always available for typing commands.
- **Dual input methods**: Users can select "Choose issues to ignore" OR type directly in Other field - both work the same way
- **Sort messages**: By count (descending) then timestamp (descending) for better visibility of recurring issues
- **Preserve exact message text**: When adding to ignore lists, strip `[thread:...]` but preserve everything else (wildcards can be added manually after)
- **Wildcard patterns**: Users can manually edit ignore list files to replace variable parts with `*` for flexible matching. Examples: `"Mcp session not found: *"` matches any session, `"@Sentry: [*] Error"` matches error from any service
- **Pattern detection**: When 3+ similar messages are selected, automatically detect patterns and offer to create a single wildcarded ignore entry instead of adding each individually. This reduces noise more effectively.
- **Use UTC timestamps consistently**
- **Sanitize channel names** consistently for file paths
- **Don't skip channels silently** - always report what happened
- **Parse flexibly**: Accept various input formats - comma-separated, multi-line, different spacing
- **Validate input**: Check message numbers are in valid range before processing

## Self-Improvement Review (Ask First)

**REQUIRED:** Use AskUserQuestion to ask the user if they want to run the self-improvement review. Only skip the review if they decline.

If they accept, reflect on your execution:

- Did anything fail, feel awkward, or require unnecessary retries?
- Were you missing context that CLAUDE.md or another project doc should have provided?
- Is there a step in this skill that was unclear, redundant, or in the wrong order?

If you identify a concrete improvement, present it as a **diff to the relevant file** (skill definition, CLAUDE.md, AGENTS.md, etc.) and offer to apply it. Do NOT just list observations — every finding must come with an actionable diff.
Do not apply changes without approval.
If nothing stands out, say so briefly and move on — do not force feedback.
