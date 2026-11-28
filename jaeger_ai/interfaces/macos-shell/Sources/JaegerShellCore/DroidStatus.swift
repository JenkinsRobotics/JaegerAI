// JaegerShellCore: modular Gateway /v1/droid/status parsing and menu presentation rules.
import CoreFoundation
import Foundation

public struct DroidStatusSnapshot: Sendable, Equatable {
    public let reachable: Bool
    public let awake: Bool
    public let sleeping: Bool
    public let camera: String
    public let estopActive: Bool
    public let gimbalCameraName: String?
    public let panDeg: Double?
    public let tiltDeg: Double?

    public init(
        reachable: Bool,
        awake: Bool,
        sleeping: Bool,
        camera: String,
        estopActive: Bool,
        gimbalCameraName: String?,
        panDeg: Double?,
        tiltDeg: Double?
    ) {
        self.reachable = reachable
        self.awake = awake
        self.sleeping = sleeping
        self.camera = camera
        self.estopActive = estopActive
        self.gimbalCameraName = gimbalCameraName
        self.panDeg = panDeg
        self.tiltDeg = tiltDeg
    }

    public static let offline = DroidStatusSnapshot(
        reachable: false,
        awake: false,
        sleeping: true,
        camera: "offline",
        estopActive: false,
        gimbalCameraName: nil,
        panDeg: nil,
        tiltDeg: nil
    )

    public var stateLineTitle: String {
        guard reachable else { return "Droid: Gateway offline" }
        let base: String
        if awake {
            switch camera.lowercased() {
            case "streaming":
                base = "Droid: Awake (Streaming)"
            case "parked":
                base = "Droid: Awake (Camera Parked)"
            default:
                base = "Droid: Awake (Camera Ready)"
            }
        } else {
            base = "Droid: Asleep (Camera Parked)"
        }
        return estopActive ? "\(base) · E-Stop ON" : base
    }

    public var senseLineTitle: String? {
        guard reachable else { return nil }
        var parts: [String] = []
        if let name = gimbalCameraName, !name.isEmpty {
            parts.append(name)
        }
        if let panDeg {
            parts.append("pan \(Self.formatDegrees(panDeg))°")
        }
        if let tiltDeg {
            parts.append("tilt \(Self.formatDegrees(tiltDeg))°")
        }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    public var toggleTitle: String {
        if reachable && awake {
            return "Turn Off Droid Mode (Sleep & Park)"
        }
        return "Turn On Droid Mode (Wake)"
    }

    /// Turning OFF (Sleep & Park) is ALWAYS enabled when Gateway is reachable, even under E-Stop.
    /// Turning ON (Wake) is blocked fail-closed whenever E-Stop is active.
    public var toggleEnabled: Bool {
        guard reachable else { return false }
        return awake ? true : !estopActive
    }

    public var toggleEndpointPath: String {
        awake ? "/v1/droid/sleep" : "/v1/droid/wake"
    }

    /// Explicit privacy park is ALWAYS enabled when Gateway is reachable, even under E-Stop.
    public var parkEnabled: Bool { reachable }

    /// Centering moves the gimbal forward; enabled only when awake and E-Stop is released.
    public var centerEnabled: Bool { reachable && awake && !estopActive }

    public static func formatDegrees(_ value: Double) -> String {
        let normalized = abs(value) < 0.05 ? 0.0 : value
        let rounded = (normalized * 10.0).rounded() / 10.0
        if rounded == rounded.rounded() {
            return String(Int(rounded))
        }
        return String(format: "%.1f", rounded)
    }
}

public enum DroidStatusParser {
    /// Parses a Gateway `GET /v1/droid/status` HTTP response into a `DroidStatusSnapshot`.
    public static func parse(statusCode: Int?, data: Data?) -> DroidStatusSnapshot {
        guard let code = statusCode, (200..<300).contains(code),
              let data, !data.isEmpty,
              let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else {
            return .offline
        }
        if let ok = json["ok"] as? Bool, !ok {
            return .offline
        }

        let sleepingFlag = json["sleeping"] as? Bool
        let awakeFlag = json["awake"] as? Bool
        let awake: Bool
        let sleeping: Bool
        if let awakeFlag, let sleepingFlag {
            awake = awakeFlag
            sleeping = sleepingFlag
        } else if let awakeFlag {
            awake = awakeFlag
            sleeping = !awakeFlag
        } else if let sleepingFlag {
            sleeping = sleepingFlag
            awake = !sleepingFlag
        } else {
            awake = false
            sleeping = true
        }

        let cameraRaw = (json["camera"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
        let camera = (cameraRaw?.isEmpty == false ? cameraRaw! : (awake ? "ready" : "parked"))
        let estopActive = (json["estop_active"] as? Bool) ?? (json["estop_latched"] as? Bool) ?? false

        let devices = json["devices"] as? [String: Any]
        let gimbal = devices?["gimbal_camera"] as? [String: Any]
        let gimbalNameRaw = (gimbal?["name"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
        let gimbalName = (gimbalNameRaw?.isEmpty == false) ? gimbalNameRaw : nil

        let pose = json["pose"] as? [String: Any]
        let panDeg = parseDouble(pose?["pan_deg"])
        let tiltDeg = parseDouble(pose?["tilt_deg"])

        return DroidStatusSnapshot(
            reachable: true,
            awake: awake,
            sleeping: sleeping,
            camera: camera,
            estopActive: estopActive,
            gimbalCameraName: gimbalName,
            panDeg: panDeg,
            tiltDeg: tiltDeg
        )
    }

    private static func parseDouble(_ value: Any?) -> Double? {
        if let number = value as? NSNumber {
            if CFGetTypeID(number) == CFBooleanGetTypeID() { return nil }
            return number.doubleValue
        }
        if let text = value as? String {
            return Double(text.trimmingCharacters(in: .whitespacesAndNewlines))
        }
        return nil
    }
}
