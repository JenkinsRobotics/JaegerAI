# AppleScript: Fetch Unread Mail

Use this script to fetch unread messages from Apple Mail. Write it to `/tmp/mail_fetch.scpt` and run with `osascript /tmp/mail_fetch.scpt`.

```applescript
tell application "Mail"
    set output to ""
    set allAccounts to every account
    repeat with acct in allAccounts
        set acctName to name of acct
        -- Skip Gmail/Google accounts — handled separately via Gmail MCP connector
        if acctName does not contain "Gmail" and acctName does not contain "Google" then
            set inboxes to every mailbox of acct whose name is "INBOX"
            if (count of inboxes) > 0 then
                set theInbox to item 1 of inboxes
                set unreadMsgs to (messages of theInbox whose read status is false)
                repeat with msg in unreadMsgs
                    set msgSender to sender of msg
                    set msgSubject to subject of msg
                    set msgDate to date received of msg as string
                    set output to output & acctName & " | " & msgSender & " | " & msgSubject & " | " & msgDate & linefeed
                end repeat
            end if
        end if
    end repeat
    return output
end tell
```

## Output Format
Each line: `AccountName | Sender | Subject | Date`

## Notes
- Covers all accounts added to Apple Mail (iCloud, Outlook, Yahoo)
- Skips Gmail/Google accounts to avoid duplicates — those are fetched via the Gmail MCP connector
- Only reads INBOX; does not touch Junk/Spam
- Requires Automation permission for Terminal/Claude in System Settings
