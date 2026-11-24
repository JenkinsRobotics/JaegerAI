"""Pure Mail.app mailbox alias expansion and AppleScript resolver helpers.

No tool registration, no permission decorators, no product imports.
"""

from __future__ import annotations

from .appleevents import escape_applescript

ALIAS_GROUPS: dict[str, tuple[str, ...]] = {
    "trash": ("Trash", "Deleted Messages", "Deleted Items", "Bin"),
    "deleted": ("Trash", "Deleted Messages", "Deleted Items", "Bin"),
    "junk": ("Spam", "Junk", "Junk Email", "Bulk"),
    "spam": ("Spam", "Junk", "Junk Email", "Bulk"),
    "archive": ("Archive", "All Mail"),
    "receipts": ("Receipts", "Archive", "All Mail"),
    "finance": ("Finance", "Archive", "All Mail"),
    "github-noise": ("GitHub-Noise", "Archive", "All Mail"),
}

MAIL_RESOLVER_AS = r'''
on _aliasHit(nameOrPath, aliasCSV)
    ignoring case
        if aliasCSV is "" then return false
        set oldDelims to AppleScript's text item delimiters
        set AppleScript's text item delimiters to ","
        set aliasItems to text items of aliasCSV
        set AppleScript's text item delimiters to oldDelims
        repeat with a in aliasItems
            if nameOrPath is (contents of a) then return true
        end repeat
        return false
    end ignoring
end _aliasHit

on _walk(mbs, prefix, wanted, aliasCSV, exactOnly, depth)
    if depth > 5 then return missing value
    tell application "Mail"
        repeat with mb in mbs
            set n to name of mb as string
            if prefix is "" then
                set p to n
            else
                set p to prefix & "/" & n
            end if
            ignoring case
                if p is wanted or n is wanted then return mb
            end ignoring
            if exactOnly is false then
                if my _aliasHit(n, aliasCSV) then return mb
                if my _aliasHit(p, aliasCSV) then return mb
            end if
            try
                set kids to mailboxes of mb
                if (count of kids) > 0 then
                    set nested to my _walk(kids, p, wanted, aliasCSV, exactOnly, depth + 1)
                    if nested is not missing value then return nested
                end if
            end try
        end repeat
    end tell
    return missing value
end _walk

on resolveMb(accName, wanted, aliasCSV)
    tell application "Mail"
        set acc to missing value
        repeat with candidate in accounts
            ignoring case
                if (name of candidate as string) is accName then
                    set acc to candidate
                    exit repeat
                end if
            end ignoring
        end repeat
        if acc is missing value then error "No Mail account named " & accName
        -- Fast path: try direct top-level exact name before walking nested folders.
        if wanted does not contain "/" then
            try
                return mailbox wanted of acc
            end try
        end if
        ignoring case
            if wanted is "INBOX" then
                try
                    return mailbox "INBOX" of acc
                end try
            end if
        end ignoring
        set topMbs to mailboxes of acc
        -- Fast pass over top-level mailboxes only (avoids nested IPC walks for common folders).
        if wanted does not contain "/" then
            repeat with mb in topMbs
                set n to name of mb as string
                ignoring case
                    if n is wanted then return mb
                end ignoring
            end repeat
            repeat with mb in topMbs
                set n to name of mb as string
                if my _aliasHit(n, aliasCSV) then return mb
            end repeat
        end if
        set found to my _walk(topMbs, "", wanted, aliasCSV, true, 0)
        if found is missing value then
            set found to my _walk(topMbs, "", wanted, aliasCSV, false, 0)
        end if
        if found is missing value then error "Can't get mailbox " & wanted & " of account " & accName & ". Call list_mailboxes and use an exact path."
        return found
    end tell
end resolveMb
'''


def alias_candidates(mailbox: str) -> list[str]:
    """Return Mail.app names that should match ``mailbox``."""
    raw = (mailbox or "").strip()
    if not raw:
        return ["INBOX"]
    key = raw.replace("\\", "/").strip()
    leaf = key.split("/")[-1]
    lowered = {key.lower(), leaf.lower()}
    out: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        cleaned = name.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            out.append(cleaned)

    add(key)
    if leaf != key:
        add(leaf)
    for alias_key, names in ALIAS_GROUPS.items():
        group_lower = {alias_key, *[n.lower() for n in names]}
        if lowered & group_lower:
            add(alias_key)
            for n in names:
                add(n)
    return out


def resolve_mailbox_call(var_name: str, account: str, mailbox: str) -> str:
    acc = escape_applescript(account)
    wanted = escape_applescript((mailbox or "INBOX").strip() or "INBOX")
    aliases = escape_applescript(",".join(alias_candidates(mailbox)))
    return f'set {var_name} to my resolveMb("{acc}", "{wanted}", "{aliases}")'
