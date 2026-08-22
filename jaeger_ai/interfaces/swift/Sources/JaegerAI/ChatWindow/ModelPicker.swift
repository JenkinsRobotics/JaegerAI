//
//  ModelPicker.swift
//  JaegerAI / ChatWindow
//
//  Hermes-style two-stage model picker as a clickable overlay. Stage 1
//  is the provider list; stage 2 is the models under the chosen
//  provider. Fed by the bridge ``model_picker`` query (the same grouping
//  the terminal TUI picker uses) and applied via ``configure_model``.
//

import SwiftUI

/// Wire shape of ``query("model_picker")``.
struct ModelPickerCatalog: Decodable {
    let currentProvider: String
    let currentModel: String
    let providers: [Provider]
    let localPaths: [String: String]?

    enum CodingKeys: String, CodingKey {
        case currentProvider = "current_provider"
        case currentModel = "current_model"
        case providers
        case localPaths = "local_paths"
    }

    struct Provider: Decodable, Identifiable, Hashable {
        let slug: String
        let name: String
        let models: [String]?
        let typeAModel: Bool?
        let isCurrent: Bool?

        var id: String { slug }
        var typeA: Bool { typeAModel == true }
        var modelList: [String] { models ?? [] }

        enum CodingKeys: String, CodingKey {
            case slug, name, models
            case typeAModel = "type_a_model"
            case isCurrent = "is_current"
        }
    }
}

private let typeAModelLabel = "✎ Type a different model…"

/// Clickable two-stage picker sheet. Loading / applying / error are
/// in-sheet so nothing about the switch lands in the transcript until
/// a brain actually changed.
struct ModelPickerSheet: View {
    @ObservedObject var agent: AgentBridge
    var onDismiss: () -> Void
    var onSwitched: (String) -> Void

    @State private var catalog: ModelPickerCatalog?
    @State private var error: String?
    @State private var loading = true
    @State private var applying = false
    @State private var selected: ModelPickerCatalog.Provider?
    @State private var typedModel = ""
    @State private var showTypeField = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Rectangle().fill(Term.rule).frame(height: 1)
            content
        }
        .frame(width: 440, height: 480)
        .background(Term.canvas)
        .interactiveDismissDisabled(applying)
        .task { await loadCatalog() }
    }

    private var header: some View {
        HStack(spacing: 10) {
            if selected != nil {
                Button {
                    selected = nil
                    showTypeField = false
                    typedModel = ""
                } label: {
                    Label("Back", systemImage: "chevron.left")
                        .font(.system(size: 11, design: .monospaced))
                }
                .buttonStyle(.plain)
                .foregroundColor(Term.accent)
            }
            Text(selected.map { "⚙ \($0.name)" } ?? "⚙ Model Picker")
                .font(.system(size: 13, weight: .semibold, design: .monospaced))
                .foregroundColor(Term.accent)
            Spacer()
            if applying {
                ProgressView().controlSize(.mini)
            }
            Button("Cancel", action: onDismiss)
                .font(.system(size: 11, design: .monospaced))
                .buttonStyle(.plain)
                .foregroundColor(Term.inkDim)
                .keyboardShortcut(.cancelAction)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(Term.panel)
    }

    @ViewBuilder
    private var content: some View {
        if loading {
            VStack(spacing: 10) {
                ProgressView()
                Text("scanning for models…")
                    .font(.system(size: 12, design: .monospaced))
                    .foregroundColor(Term.inkDim)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if let error {
            Text(error)
                .font(.system(size: 12, design: .monospaced))
                .foregroundColor(Term.ink)
                .padding(16)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        } else if showTypeField, let provider = selected {
            typeField(for: provider)
        } else if let provider = selected {
            modelList(provider)
        } else {
            providerList
        }
    }

    private var providerList: some View {
        let current = catalog.map { "\($0.currentModel) on \($0.currentProvider)" }
            ?? "unknown"
        return VStack(alignment: .leading, spacing: 0) {
            Text("Current: \(current)")
                .font(.system(size: 11, design: .monospaced))
                .foregroundColor(Term.inkDim)
                .padding(.horizontal, 14)
                .padding(.vertical, 8)
            Divider().overlay(Term.rule)
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    ForEach(catalog?.providers ?? []) { p in
                        pickerRow(
                            title: providerLabel(p),
                            current: p.isCurrent == true
                        ) {
                            if p.typeA {
                                selected = p
                                showTypeField = true
                            } else {
                                selected = p
                            }
                        }
                        Divider().overlay(Term.rule.opacity(0.5))
                    }
                }
            }
        }
    }

    private func modelList(_ provider: ModelPickerCatalog.Provider) -> some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 0) {
                ForEach(provider.modelList, id: \.self) { name in
                    pickerRow(title: name, current: isCurrent(provider, name)) {
                        if name == typeAModelLabel {
                            showTypeField = true
                        } else {
                            Task { await apply(provider: provider, model: name) }
                        }
                    }
                    Divider().overlay(Term.rule.opacity(0.5))
                }
            }
        }
    }

    private func typeField(for provider: ModelPickerCatalog.Provider) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("\(provider.name) model")
                .font(.system(size: 12, design: .monospaced))
                .foregroundColor(Term.inkDim)
            TextField("model id", text: $typedModel)
                .textFieldStyle(.plain)
                .font(Term.mono)
                .foregroundColor(Term.ink)
                .padding(8)
                .background(RoundedRectangle(cornerRadius: 6).fill(Term.panel))
                .overlay(
                    RoundedRectangle(cornerRadius: 6)
                        .strokeBorder(Term.rule, lineWidth: 1)
                )
                .onSubmit { Task { await submitTyped(provider) } }
            HStack {
                Spacer()
                Button("Switch") { Task { await submitTyped(provider) } }
                    .disabled(typedModel.trimmingCharacters(in: .whitespaces).isEmpty
                              || applying)
                    .buttonStyle(.borderedProminent)
                    .tint(Term.accent)
                    .keyboardShortcut(.defaultAction)
            }
            Spacer()
        }
        .padding(16)
    }

    private func pickerRow(title: String, current: Bool,
                           action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 8) {
                Text(title)
                    .font(.system(size: 12, design: .monospaced))
                    .foregroundColor(Term.ink)
                    .lineLimit(1)
                if current {
                    Text("← current")
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundColor(Term.accent)
                }
                Spacer()
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 8)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(applying)
    }

    private func providerLabel(_ p: ModelPickerCatalog.Provider) -> String {
        if p.typeA { return "\(p.name) (type a model)" }
        let n = p.modelList.filter { $0 != typeAModelLabel }.count
        return "\(p.name) (\(n) model\(n == 1 ? "" : "s"))"
    }

    private func isCurrent(_ provider: ModelPickerCatalog.Provider,
                           _ name: String) -> Bool {
        guard let catalog else { return false }
        return provider.isCurrent == true && name == catalog.currentModel
    }

    private func loadCatalog() async {
        loading = true
        error = nil
        let result = await agent.query("model_picker")
        loading = false
        guard result.ok, let data = result.json else {
            error = result.error ?? "couldn't load the model list"
            return
        }
        do {
            catalog = try JSONDecoder().decode(ModelPickerCatalog.self, from: data)
        } catch {
            self.error = "couldn't read the model list: \(error.localizedDescription)"
        }
    }

    private func submitTyped(_ provider: ModelPickerCatalog.Provider) async {
        let name = typedModel.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { return }
        await apply(provider: provider, model: name)
    }

    private func apply(provider: ModelPickerCatalog.Provider, model: String) async {
        applying = true
        defer { applying = false }
        var resolved = model
        if ["local", "mlx"].contains(provider.slug),
           let path = catalog?.localPaths?[model] {
            resolved = path
        }
        let result = await agent.command("configure_model", args: [
            "provider": SlashRouting.configureProvider(provider.slug),
            "model": resolved,
        ])
        if result.ok {
            await agent.refreshIdentity()
            onSwitched("✓ Brain is now \(provider.slug) · \(model)")
            onDismiss()
        } else {
            error = result.error ?? "couldn't switch model"
        }
    }
}
