# Ignore List for #example-channel

<!--
**Wildcard patterns:** Use `*` to match any characters in variable content.

**Examples:**
- `"Session expired: *"` - Matches any session ID after "Session expired: "
- `"@Monitor: [*] Database timeout"` - Matches the error from any service name
- `"Record not found: * in table users"` - Matches any record ID
- `"Error code *: Connection refused"` - Matches any error code number

**When to use wildcards:**
- Session IDs, request IDs, user IDs that change each occurrence
- Service names when the same error occurs across multiple services
- Dynamic values (timestamps, counters, UUIDs) embedded in messages
- Keep non-variable parts exact for safety (avoid over-filtering)
-->

## Active Ignores

- "Health check passed" - Reason: routine automated check, only failures need attention - Last seen: 2026-04-20T14:30:00Z
- "Daily backup completed successfully" - Reason: informational only, not actionable - Last seen: 2026-04-22T02:00:00Z
- "Test alert - please ignore" - Reason: testing message from monitoring team - Last seen: 2026-04-21T16:45:00Z

## Disabled Ignores (not seen in 30+ days)


<!-- Disabled on 2026-04-22T13:00:00Z - Last seen: 2026-03-10T08:15:00Z -->
<!-- - "Connection to dev-database timeout" - Reason: dev database is decommissioned, expected failure -->
