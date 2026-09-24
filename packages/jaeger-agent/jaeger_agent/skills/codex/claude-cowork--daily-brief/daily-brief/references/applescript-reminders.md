# AppleScript: Fetch Due Reminders

Use this script to fetch incomplete reminders that are due today or overdue. Write it to `/tmp/reminders_fetch.scpt` and run with `osascript /tmp/reminders_fetch.scpt`.

```applescript
tell application "Reminders"
    set output to ""
    set todayEnd to current date
    set hours of todayEnd to 23
    set minutes of todayEnd to 59
    set seconds of todayEnd to 59

    repeat with reminderList in lists
        set listName to name of reminderList
        set dueReminders to (reminders of reminderList whose completed is false and due date <= todayEnd)
        repeat with rem in dueReminders
            set remName to name of rem
            try
                set remDue to due date of rem as string
            on error
                set remDue to "No due date"
            end try
            try
                set remPriority to priority of rem as string
            on error
                set remPriority to "0"
            end try
            set output to output & listName & " | " & remName & " | " & remDue & " | Priority:" & remPriority & linefeed
        end repeat
    end repeat
    return output
end tell
```

## Output Format
Each line: `ListName | ReminderTitle | DueDate | Priority`

## Priority Values
- 0 = No priority
- 1-4 = High
- 5 = Medium
- 6-9 = Low

## Notes
- Fetches all incomplete reminders due today or earlier (overdue)
- Reads all lists in Reminders.app
- Requires Automation permission for Terminal/Claude in System Settings
