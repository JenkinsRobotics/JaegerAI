//
//  MonarchAuthSheet.swift
//  JaegerAI / ChatWindow
//
//  Native macOS Authentication Sheet for Monarch Money.
//  Configured with Apple Passwords / iCloud Keychain AutoFill (.textContentType)
//  and Touch ID support, so operators never have to copy passwords into a terminal.
//

import AppKit
import SwiftUI

struct MonarchAuthSheet: View {
    var onDismiss: () -> Void
    var onConnected: (Int) -> Void

    @State private var email: String = ""
    @State private var password: String = ""
    @State private var mfaCode: String = ""
    @State private var isConnecting: Bool = false
    @State private var errorMessage: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            // Header
            HStack(spacing: 12) {
                ZStack {
                    RoundedRectangle(cornerRadius: 10)
                        .fill(Color(red: 0.96, green: 0.55, blue: 0.16).opacity(0.15))
                        .frame(width: 36, height: 36)
                    Image(systemName: "creditcard.fill")
                        .font(.system(size: 18))
                        .foregroundColor(Color(red: 0.96, green: 0.55, blue: 0.16))
                }

                VStack(alignment: .leading, spacing: 2) {
                    Text("Connect Monarch Money")
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundColor(Term.ink)
                    Text("AutoFill credentials via Apple Passwords & iCloud Keychain")
                        .font(.system(size: 11))
                        .foregroundColor(Term.inkDim)
                }

                Spacer()
            }

            if let error = errorMessage {
                HStack(spacing: 8) {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundColor(Color.red)
                    Text(error)
                        .font(.system(size: 11))
                        .foregroundColor(Color.red)
                }
                .padding(8)
                .background(RoundedRectangle(cornerRadius: 6).fill(Color.red.opacity(0.1)))
            }

            // Input fields
            VStack(alignment: .leading, spacing: 12) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Monarch Email / Apple ID")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundColor(Term.inkDim)
                    TextField("Email", text: $email)
                        .textFieldStyle(.plain)
                        .textContentType(.username)
                        .font(.system(size: 13))
                        .padding(8)
                        .background(RoundedRectangle(cornerRadius: 8).fill(Color.white.opacity(0.06)))
                        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.white.opacity(0.1), lineWidth: 1))
                }

                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        Text("Password")
                            .font(.system(size: 11, weight: .medium))
                            .foregroundColor(Term.inkDim)
                        Spacer()
                        Label("Apple Passwords", systemImage: "key.fill")
                            .font(.system(size: 10))
                            .foregroundColor(Term.accent)
                    }
                    SecureField("Password", text: $password)
                        .textFieldStyle(.plain)
                        .textContentType(.password)
                        .font(.system(size: 13))
                        .padding(8)
                        .background(RoundedRectangle(cornerRadius: 8).fill(Color.white.opacity(0.06)))
                        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.white.opacity(0.1), lineWidth: 1))
                }

                VStack(alignment: .leading, spacing: 4) {
                    Text("2FA Authenticator Code (if enabled)")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundColor(Term.inkDim)
                    TextField("6-digit code or leave blank", text: $mfaCode)
                        .textFieldStyle(.plain)
                        .textContentType(.oneTimeCode)
                        .font(.system(size: 13))
                        .padding(8)
                        .background(RoundedRectangle(cornerRadius: 8).fill(Color.white.opacity(0.06)))
                        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.white.opacity(0.1), lineWidth: 1))
                }
            }

            HStack(spacing: 8) {
                Image(systemName: "lock.shield.fill")
                    .font(.system(size: 12))
                    .foregroundColor(Color.green)
                Text("Stored strictly in ~/.ares/.mm_session.pickle (mode 0600). Never uploaded to GitHub.")
                    .font(.system(size: 10))
                    .foregroundColor(Term.inkDim)
            }
            .padding(.top, 4)

            // Buttons
            HStack(spacing: 12) {
                Spacer()

                Button("Cancel") {
                    onDismiss()
                }
                .keyboardShortcut(.cancelAction)
                .buttonStyle(.plain)
                .foregroundColor(Term.inkDim)

                Button {
                    Task { await connectMonarch() }
                } label: {
                    HStack(spacing: 6) {
                        if isConnecting {
                            ProgressView()
                                .controlSize(.mini)
                        } else {
                            Image(systemName: "touchid")
                                .font(.system(size: 12))
                        }
                        Text(isConnecting ? "Authenticating…" : "Connect with Apple Passwords")
                            .font(.system(size: 12, weight: .semibold))
                    }
                    .padding(.horizontal, 14)
                    .padding(.vertical, 8)
                    .background(RoundedRectangle(cornerRadius: 8).fill(Term.accent))
                    .foregroundColor(.white)
                }
                .buttonStyle(.plain)
                .keyboardShortcut(.defaultAction)
                .disabled(isConnecting || email.isEmpty || password.isEmpty)
            }
            .padding(.top, 6)
        }
        .padding(24)
        .frame(width: 440)
        .background(Color(red: 0.08, green: 0.09, blue: 0.12))
    }

    private func connectMonarch() async {
        isConnecting = true
        errorMessage = nil

        let userEmail = email.trimmingCharacters(in: .whitespacesAndNewlines)
        let userPassword = password
        let code = mfaCode.trimmingCharacters(in: .whitespacesAndNewlines)

        do {
            let accountCount = try await Task.detached(priority: .userInitiated) { () -> Int in
                let process = Process()
                let venvPython = FileManager.default.homeDirectoryForCurrentUser
                    .appendingPathComponent(".jaeger/venv/bin/python")
                process.executableURL = FileManager.default.fileExists(atPath: venvPython.path) ? venvPython : URL(fileURLWithPath: "/usr/bin/python3")
                
                let pythonScript = """
import asyncio, json, os, sys
from pathlib import Path
from monarchmoney import MonarchMoney

async def do_login():
    session_file = Path.home() / ".ares/.mm_session.pickle"
    session_file.parent.mkdir(parents=True, exist_ok=True)
    mm = MonarchMoney(session_file=str(session_file))
    email = sys.argv[1]
    pwd = sys.argv[2]
    mfa = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else None
    
    if mfa:
        await mm.login(email=email, password=pwd, mfa_code=mfa, save_session=True)
    else:
        await mm.login(email=email, password=pwd, save_session=True)
        
    mm.save_session(str(session_file))
    os.chmod(str(session_file), 0o600)
    
    accts = await mm.get_accounts()
    count = len(accts.get("accounts", [])) if isinstance(accts, dict) else len(accts)
    print(json.dumps({"ok": True, "count": count}))

try:
    asyncio.run(do_login())
except Exception as e:
    print(json.dumps({"ok": False, "error": str(e)}))
"""
                process.arguments = ["-c", pythonScript, userEmail, userPassword, code]
                let pipe = Pipe()
                process.standardOutput = pipe
                process.standardError = pipe
                
                try process.run()
                process.waitUntilExit()
                
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                guard let output = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) else {
                    throw NSError(domain: "MonarchAuth", code: 1, userInfo: [NSLocalizedDescriptionKey: "No response from Monarch bridge"])
                }
                
                // Find json line
                for line in output.components(separatedBy: "\n") {
                    if let lineData = line.data(using: .utf8),
                       let obj = try? JSONSerialization.jsonObject(with: lineData) as? [String: Any] {
                        if obj["ok"] as? Bool == true {
                            return obj["count"] as? Int ?? 0
                        } else if let err = obj["error"] as? String {
                            throw NSError(domain: "MonarchAuth", code: 2, userInfo: [NSLocalizedDescriptionKey: err])
                        }
                    }
                }
                throw NSError(domain: "MonarchAuth", code: 3, userInfo: [NSLocalizedDescriptionKey: output])
            }.value

            await MainActor.run {
                isConnecting = false
                onConnected(accountCount)
                onDismiss()
            }
        } catch {
            await MainActor.run {
                isConnecting = false
                errorMessage = error.localizedDescription
            }
        }
    }
}
