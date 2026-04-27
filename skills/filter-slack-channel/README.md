# filter-slack-channel

Filter and manage Slack alert messages with channel-specific ignore lists.

## Overview

This skill helps you manage alert fatigue by:
- Fetching new messages from configured Slack channels
- Filtering out known non-actionable messages
- Deduplicating repeated messages (shows each unique message once with count)
- Generating clickable links to jump directly to messages in Slack
- Maintaining channel-specific ignore lists with documented reasons
- Tracking what you've already checked (stateful)

## Use Cases

- **Alert channels**: Filter out testing alerts, known issues, informational messages
- **Production vs. Staging**: Different ignore lists for different environments
- **Knowledge repository**: Document why messages are safe to ignore
- **Daily triage**: Quickly see only actionable alerts since last check

## Setup

### 1. Install Slack MCP Server

You need a Slack MCP server to fetch messages. Install from:

```bash
# Clone the repository
git clone https://github.com/bonscji1/slack-mcp
cd slack-mcp

# Run the guided setup script
python3 scripts/setup-slack-mcp.py

# Or use the quick install:
python3 <(curl -fsSL https://raw.githubusercontent.com/bonscji1/slack-mcp/main/scripts/setup-slack-mcp.py)
```

The setup script handles everything: virtual environment, Playwright installation, token extraction, and Claude Code registration.

**Required Slack scopes:**
- `channels:history` - read message history
- `channels:read` - list channels
- `users:read` - get user info (optional, for display)

### 2. Configure Channels

Copy the example template and customize it:

```bash
cp skills/filter-slack-channel/config/channels.example.json \
   skills/filter-slack-channel/config/channels.json
```

Or create `skills/filter-slack-channel/config/channels.json` manually:

```json
{
  "workspaceDomain": "mycompany",
  "channels": [
    {
      "name": "#prod-alerts",
      "id": "C01ABC123",
      "lastChecked": "2026-04-01T00:00:00Z",
      "ignoreListFile": "prod-alerts.md"
    },
    {
      "name": "#stage-alerts",
      "id": "C01DEF456",
      "lastChecked": "2026-04-01T00:00:00Z",
      "ignoreListFile": "stage-alerts.md"
    }
  ]
}
```

**Workspace domain (optional):**
- Set `workspaceDomain` to your Slack workspace subdomain (e.g., "mycompany" for mycompany.slack.com)
- If provided, messages will include clickable links to jump directly to the Slack message
- Find your workspace domain from your Slack URL: `https://WORKSPACEDOMAIN.slack.com/`
- If omitted, messages will be displayed without links

**Finding channel IDs:**
- Use Slack MCP's `mcp__slack__get_channel_id_by_name` tool
- Use Slack MCP's `mcp__slack__list_joined_channels` tool to see all channels
- Or visit channel in Slack, right-click → View channel details → copy ID from URL

**Initial `lastChecked`:**
- Set to when you want to start monitoring from
- Use ISO 8601 format with `Z` timezone
- Skill will update this automatically after each run

**Ignore list file:**
- Set `ignoreListFile` to the filename for this channel's ignore list
- Files are stored in `config/ignore-lists/`
- Use sanitized channel name: remove `#`, replace spaces/special chars with `-`, lowercase
- Examples: `#prod-alerts` → `prod-alerts.md`, `#my-channel` → `my-channel.md`
- The skill will auto-create the file if it doesn't exist

### 3. Create Ignore Lists (Optional)

Ignore lists are created automatically when you add messages through the skill, but you can also create them manually:

Create `skills/filter-slack-channel/config/ignore-lists/<channel-name>.md`:

```markdown
# Ignore List for #prod-alerts

## Messages to Ignore

- "log. severity banana does not exist" - Reason: testing message, safe to ignore
- "Daily backup completed" - Reason: informational only, not actionable
- "Health check succeeded" - Reason: routine check, only failures are actionable
```

**File naming:**
- Channel `#prod-alerts` → `prod-alerts.md`
- Channel `#stage-notifications` → `stage-notifications.md`
- Remove `#`, replace spaces/special chars with `-`, lowercase

## Usage

### Basic Usage

Check all configured channels since last check:
```
/filter-slack-channel
```

### Time Window Override

Check all channels for a specific time window (ignores `lastChecked`):
```
/filter-slack-channel 2h      # Last 2 hours
/filter-slack-channel 30m     # Last 30 minutes
/filter-slack-channel 1d      # Last 24 hours
```

### Specific Channel

Check only one channel:
```
/filter-slack-channel #prod-alerts
/filter-slack-channel prod-alerts
```

### Channel + Time Override

Check specific channel for specific time window:
```
/filter-slack-channel #prod-alerts 2h
```

## Workflow

When you run the skill:

1. **Fetches messages** from each configured channel since `lastChecked` (or time override)
2. **Filters out** messages that match the channel's ignore list
3. **Deduplicates** - if the same message appears 5 times, shows it once (with count)
4. **Displays results** in pages of 10 messages per channel
5. **Interactive command interface** - add issues with simple commands like `1. testing noise`
6. **Updates `lastChecked`** timestamp after finishing each channel

**Key features:**
- **Fast interaction**: Add multiple issues in one response: `1. testing, 3. known issue`
- **Paginated display**: 20 messages per page with menu navigation
- **Dual input**: Select from menu OR type in Other field
- **Regression detection**: Warns if message was previously ignored but came back
- **Channel-specific ignore lists**: Each channel has its own ignore patterns

## Example Session

```
/filter-slack-channel

## #prod-alerts (25 unique, 42 total, 17 ignored)
Ignore list: config/ignore-lists/prod-alerts.md (5 patterns)

Issues (Page 1 of 2):

1. [@Database connection pool exhausted] (appeared 15 times)
First seen: 2026-04-22 10:30:15 UTC
Link: https://mycompany.slack.com/archives/C01ABC123/p1713786615000000?cid=C01ABC123

2. [@High memory usage on node-5] (appeared 8 times)
First seen: 2026-04-22 11:45:22 UTC
Link: https://mycompany.slack.com/archives/C01ABC123/p1713791122000000?cid=C01ABC123

3. [@API timeout on /users endpoint] (appeared 3 times)
First seen: 2026-04-22 14:20:10 UTC
Link: https://mycompany.slack.com/archives/C01ABC123/p1713800410000000?cid=C01ABC123

... (17 more messages)

---
To add issues to ignore list, type in the text field:
  Format: <number>. <reason>
  Example: 1. testing noise, not production
  Multiple: 1. testing noise, 3. known issue tracked in JIRA-123

What would you like to do?
○ Choose issues to ignore
○ Next page
○ Previous page
○ Finished
○ Other: _____________

> User selects "Choose issues to ignore" or types in Other:
  1. testing data, not real issue, 5. known timeout, tracked

✓ Added 2 issue(s) to ignore list

What would you like to do?
○ Choose issues to ignore
○ Next page
○ Previous page
○ Finished

> User selects: Next page

Issues (Page 2 of 2):
... (remaining 5 messages)

> User selects: Finished

## #stage-alerts (0 unique, 12 total, 12 ignored)

✓ No new actionable messages for #stage-alerts

(Skill completes)
```

## Ignore List Format

Each entry in an ignore list file:

```markdown
- "exact message text" - Reason: why this is safe to ignore
```

**Important:**
- Message text must match **exactly** (case-sensitive)
- Include full message text, not partial
- Reason provides context for why it's ignored
- Use this as a knowledge repository for your team

## Configuration Files

```
skills/filter-slack-channel/
├── SKILL.md                    # Skill logic (don't edit)
├── README.md                   # This file
└── config/
    ├── channels.json           # Channel list with last check times
    └── ignore-lists/
        ├── prod-alerts.md      # Ignore list for #prod-alerts
        └── stage-alerts.md     # Ignore list for #stage-alerts
```

## Migration to Production

When you're ready to use this skill across all projects:

**Option 1: Install to ~/.claude (keep config local)**
```bash
mkdir -p ~/.claude/plugins/my-slack-tools/skills
cp -r skills/filter-slack-channel ~/.claude/plugins/my-slack-tools/skills/
```

Config files travel with the skill.

**Option 2: Centralize config**
```bash
# Move config to shared location
mkdir -p ~/.claude/slack-filters
mv skills/filter-slack-channel/config/* ~/.claude/slack-filters/

# Update SKILL.md to reference ~/.claude/slack-filters instead
```

Then config is shared across all skill installations.

## Tips

- **Run daily**: Check channels once per day to stay on top of alerts
- **Review ignore lists**: Periodically review your ignore lists to ensure they're still accurate
- **Document reasons**: Good reasons help team members understand context
- **Separate environments**: Different ignore lists for prod vs. stage helps catch real issues
- **Use time overrides**: When investigating an incident, use `/filter-slack-channel 6h` to see recent history

## Troubleshooting

**"Slack MCP server not connected"**
- Ensure Slack MCP server is installed and configured
- Check MCP settings in Claude Code
- Verify Slack token has required scopes

**"Channel not found"**
- Verify channel ID is correct in channels.json
- Ensure bot/user has access to the channel
- Check if channel was archived or deleted

**Messages not being filtered**
- Ensure message text in ignore list matches exactly (case-sensitive)
- Check file name matches sanitized channel name
- Verify ignore list file format (must have quotes around message)

**lastChecked not updating**
- Check file permissions on channels.json
- Ensure JSON is valid (run through a JSON validator)
- Look for error messages in skill output
