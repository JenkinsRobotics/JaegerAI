// JaegerPIM — fast native Calendar / Reminders / Contacts reads for Jaeger.
//
// Replaces slow AppleScript round-trips to Calendar.app and Contacts.app
// (60s / 10s timeouts in the 2026-11-16 audit, parity P7) with EventKit and
// the Contacts framework, the way native assistants read them.
// Launched by LaunchServices (`open -W -g -n -a JaegerPIM.app --args …`) so the
// macOS privacy prompt names this app, not the Gateway's Python. Writes one
// JSON object to --out (stdout is not captured under `open`).
//
//   events   --start ISO --end ISO [--calendar NAME]
//   create-event --title T --start ISO --end ISO [--calendar NAME] [--location L] [--notes N]
//   reminders [--list NAME] [--include-completed]
//   contacts --query NAME [--limit N]
//   status
//   grant      (one-time: shows the Calendars, Reminders and Contacts prompts)

import Foundation
import EventKit
import Contacts

var args = Array(CommandLine.arguments.dropFirst())
func opt(_ name: String) -> String? {
    guard let i = args.firstIndex(of: name), i + 1 < args.count else { return nil }
    return args[i + 1]
}
let outPath = opt("--out")
let command = args.first ?? "status"

func finish(_ obj: [String: Any]) -> Never {
    let data = (try? JSONSerialization.data(withJSONObject: obj, options: [.sortedKeys])) ?? Data("{}".utf8)
    if let outPath { FileManager.default.createFile(atPath: outPath, contents: data) }
    else { FileHandle.standardOutput.write(data); FileHandle.standardOutput.write(Data("\n".utf8)) }
    exit(0)
}

let iso = ISO8601DateFormatter()
iso.formatOptions = [.withInternetDateTime]
let isoFrac = ISO8601DateFormatter()
isoFrac.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
func parseDate(_ s: String?) -> Date? {
    guard let s else { return nil }
    if let d = iso.date(from: s) ?? isoFrac.date(from: s) { return d }
    let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.timeZone = .current
    for fmt in ["yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd'T'HH:mm", "yyyy-MM-dd HH:mm", "yyyy-MM-dd"] {
        f.dateFormat = fmt
        if let d = f.date(from: s) { return d }
    }
    return nil
}
let localOut = ISO8601DateFormatter()
localOut.timeZone = .current
localOut.formatOptions = [.withInternetDateTime]

let store = EKEventStore()
let sema = DispatchSemaphore(value: 0)

func eventAccess() -> Bool {
    var ok = false
    store.requestFullAccessToEvents { granted, _ in ok = granted; sema.signal() }
    _ = sema.wait(timeout: .now() + 120)
    return ok
}
func reminderAccess() -> Bool {
    var ok = false
    store.requestFullAccessToReminders { granted, _ in ok = granted; sema.signal() }
    _ = sema.wait(timeout: .now() + 120)
    return ok
}

switch command {
case "grant":
    // One-time setup: ask for all three in the foreground so the owner sees each prompt.
    let cal = eventAccess()
    let rem = reminderAccess()
    var con = false
    CNContactStore().requestAccess(for: .contacts) { g, _ in con = g; sema.signal() }
    _ = sema.wait(timeout: .now() + 120)
    finish(["ok": cal && rem && con, "calendar": cal, "reminders": rem, "contacts": con])
case "status":
    finish(["ok": true,
            "calendar": EKEventStore.authorizationStatus(for: .event).rawValue,
            "reminders": EKEventStore.authorizationStatus(for: .reminder).rawValue,
            "contacts": CNContactStore.authorizationStatus(for: .contacts).rawValue])

case "events":
    guard eventAccess() else { finish(["ok": false, "error": "Calendar access not granted to JaegerPIM (System Settings › Privacy & Security › Calendars)"]) }
    let start = parseDate(opt("--start")) ?? Calendar.current.startOfDay(for: Date())
    let end = parseDate(opt("--end")) ?? start.addingTimeInterval(86400)
    var cals = store.calendars(for: .event)
    if let name = opt("--calendar") { cals = cals.filter { $0.title.caseInsensitiveCompare(name) == .orderedSame } }
    let events = store.events(matching: store.predicateForEvents(withStart: start, end: end, calendars: cals))
        .sorted { $0.startDate < $1.startDate }
    finish(["ok": true, "range_start": localOut.string(from: start), "range_end": localOut.string(from: end),
            "count": events.count,
            "events": events.prefix(200).map { e -> [String: Any] in
                ["title": e.title ?? "", "start": localOut.string(from: e.startDate), "end": localOut.string(from: e.endDate),
                 "all_day": e.isAllDay, "calendar": e.calendar.title, "location": e.location ?? "",
                 "notes": String((e.notes ?? "").prefix(500))]
            }])

case "create-event":
    guard eventAccess() else { finish(["ok": false, "error": "Calendar access not granted to JaegerPIM"]) }
    guard let title = opt("--title"), let start = parseDate(opt("--start")) else { finish(["ok": false, "error": "--title and --start are required"]) }
    let end = parseDate(opt("--end")) ?? start.addingTimeInterval(3600)
    let ev = EKEvent(eventStore: store)
    ev.title = title; ev.startDate = start; ev.endDate = end
    ev.location = opt("--location"); ev.notes = opt("--notes")
    if let name = opt("--calendar"), let cal = store.calendars(for: .event).first(where: { $0.title.caseInsensitiveCompare(name) == .orderedSame && $0.allowsContentModifications }) {
        ev.calendar = cal
    } else { ev.calendar = store.defaultCalendarForNewEvents }
    do { try store.save(ev, span: .thisEvent, commit: true) }
    catch { finish(["ok": false, "error": "save failed: \(error.localizedDescription)"]) }
    finish(["ok": true, "created": true, "title": title, "start": localOut.string(from: start), "end": localOut.string(from: end),
            "calendar": ev.calendar?.title ?? "", "id": ev.eventIdentifier ?? ""])

case "reminders":
    guard reminderAccess() else { finish(["ok": false, "error": "Reminders access not granted to JaegerPIM (System Settings › Privacy & Security › Reminders)"]) }
    var lists = store.calendars(for: .reminder)
    let listNames = lists.map(\.title)
    if let name = opt("--list") { lists = lists.filter { $0.title.caseInsensitiveCompare(name) == .orderedSame } }
    let includeDone = args.contains("--include-completed")
    var found: [EKReminder] = []
    let pred = includeDone ? store.predicateForReminders(in: lists)
        : store.predicateForIncompleteReminders(withDueDateStarting: nil, ending: nil, calendars: lists)
    store.fetchReminders(matching: pred) { r in found = r ?? []; sema.signal() }
    _ = sema.wait(timeout: .now() + 30)
    finish(["ok": true, "lists": listNames, "count": found.count,
            "reminders": found.prefix(300).map { r -> [String: Any] in
                var d: [String: Any] = ["id": r.calendarItemIdentifier,
                                        "title": r.title ?? "", "list": r.calendar.title,
                                        "completed": r.isCompleted, "notes": r.notes ?? ""]
                if let due = r.dueDateComponents?.date { d["due"] = localOut.string(from: due) }
                return d
            }])

case "contacts":
    let cstore = CNContactStore()
    var ok = false
    cstore.requestAccess(for: .contacts) { g, _ in ok = g; sema.signal() }
    _ = sema.wait(timeout: .now() + 120)
    guard ok else { finish(["ok": false, "error": "Contacts access not granted to JaegerPIM (System Settings › Privacy & Security › Contacts)"]) }
    let query = opt("--query") ?? ""
    let limit = Int(opt("--limit") ?? "10") ?? 10
    let keys: [CNKeyDescriptor] = [CNContactGivenNameKey, CNContactFamilyNameKey, CNContactOrganizationNameKey,
                                   CNContactPhoneNumbersKey, CNContactEmailAddressesKey, CNContactNicknameKey] as [CNKeyDescriptor]
    let matches = (try? cstore.unifiedContacts(matching: CNContact.predicateForContacts(matchingName: query), keysToFetch: keys)) ?? []
    finish(["ok": true, "query": query, "found": !matches.isEmpty, "count": matches.count,
            "contacts": matches.prefix(limit).map { c -> [String: Any] in
                ["name": [c.givenName, c.familyName].filter { !$0.isEmpty }.joined(separator: " "),
                 "organization": c.organizationName, "nickname": c.nickname,
                 "phones": c.phoneNumbers.map { $0.value.stringValue },
                 "emails": c.emailAddresses.map { String($0.value) }]
            }])

default:
    finish(["ok": false, "error": "unknown command \(command)"])
}
