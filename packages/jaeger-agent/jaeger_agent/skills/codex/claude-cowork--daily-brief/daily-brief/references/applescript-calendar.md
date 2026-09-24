# AppleScript: Fetch Today's Calendar Events

Use this script to fetch all events for today from Apple Calendar. Write it to `/tmp/cal_fetch.scpt` and run with `osascript /tmp/cal_fetch.scpt`.

```applescript
tell application "Calendar"
    set output to ""
    set todayStart to current date
    set hours of todayStart to 0
    set minutes of todayStart to 0
    set seconds of todayStart to 0
    set todayEnd to todayStart + (86400 - 1)

    repeat with cal in calendars
        set calName to name of cal
        set todayEvents to (every event of cal whose start date >= todayStart and start date <= todayEnd)
        repeat with evt in todayEvents
            set evtTitle to summary of evt
            set evtStart to start date of evt as string
            set evtEnd to end date of evt as string
            try
                set evtLocation to location of evt
            on error
                set evtLocation to ""
            end try
            set output to output & calName & " | " & evtTitle & " | " & evtStart & " | " & evtEnd & " | " & evtLocation & linefeed
        end repeat
    end repeat
    return output
end tell
```

## Output Format
Each line: `CalendarName | EventTitle | StartTime | EndTime | Location`

## Notes
- Reads all calendars visible in Calendar.app (iCloud, Google, Exchange, local)
- Only fetches events starting today (midnight to 11:59pm)
- Requires Automation permission for Terminal/Claude in System Settings
