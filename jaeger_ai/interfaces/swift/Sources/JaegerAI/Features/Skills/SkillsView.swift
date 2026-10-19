//
//  SkillsView.swift
//  JaegerAI / Features / Skills
//
//  Desktop skills explorer view ported from Hermex architecture.
//

import SwiftUI

public struct SkillsView: View {
    @State private var skills: [GatewayClient.RuntimeSkill] = []
    @State private var loading = false
    @State private var loadError: String?
    @State private var loaded = false
    @State private var searchText = ""
    @State private var selectedCategory: String? = nil

    public init() {}

    private var categories: [String] {
        Array(Set(skills.map(\.category))).sorted()
    }

    private var filteredSkills: [GatewayClient.RuntimeSkill] {
        skills.filter { skill in
            let matchesCategory = selectedCategory == nil || skill.category == selectedCategory
            let q = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            let matchesSearch = q.isEmpty || skill.name.lowercased().contains(q) || skill.description.lowercased().contains(q)
            return matchesCategory && matchesSearch
        }
    }

    public var body: some View {
        VStack(spacing: 0) {
            // Header Bar
            HStack(spacing: 12) {
                HStack(spacing: 8) {
                    Image(systemName: "wrench.and.screwdriver.fill")
                        .font(.system(size: 14))
                        .foregroundColor(Color.orange)
                    Text("Agent Skills & Tools")
                        .font(.system(size: 15, weight: .bold))
                        .foregroundColor(Term.ink)
                }

                Spacer()

                HStack(spacing: 8) {
                    Image(systemName: "magnifyingglass")
                        .foregroundColor(Term.inkDim)
                        .font(.system(size: 11))
                    TextField("Search skills...", text: $searchText)
                        .textFieldStyle(.plain)
                        .font(.system(size: 12))
                        .foregroundColor(Term.ink)
                        .frame(width: 140)
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .background(Color.white.opacity(0.06))
                .cornerRadius(6)

                Button { Task { await refresh() } } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .disabled(loading)
                .help("Refresh Gateway skill catalog")

                Text("\(skills.count) available")
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundColor(Term.inkDim)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background(Color.white.opacity(0.02))

            Rectangle().fill(Color.white.opacity(0.06)).frame(height: 1)

            // Category Filter Bar
            HStack(spacing: 8) {
                categoryFilterPill(title: "All", category: nil)
                ForEach(categories, id: \.self) { cat in
                    categoryFilterPill(title: cat.capitalized, category: cat)
                }
                Spacer()
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 8)
            .background(Color.white.opacity(0.01))

            Rectangle().fill(Color.white.opacity(0.04)).frame(height: 1)

            if loading {
                ProgressView("Loading Gateway skills…").padding()
            } else if let loadError {
                Text(loadError).foregroundColor(.orange).padding()
            } else if loaded && skills.isEmpty {
                Text("The Gateway returned no skills.").foregroundColor(Term.inkDim).padding()
            } else if loaded && filteredSkills.isEmpty {
                Text("No skills match these filters.").foregroundColor(Term.inkDim).padding()
            }

            // Skill Grid
            ScrollView {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 260), spacing: 14)], spacing: 14) {
                    ForEach(filteredSkills) { skill in
                        skillCard(skill)
                    }
                }
                .padding(16)
            }
        }
        .task { await refresh() }
    }

    @MainActor
    private func refresh() async {
        guard !loading else { return }
        loading = true
        loadError = nil
        // Do not keep another endpoint's or an earlier request's catalog visible.
        skills = []
        defer { loading = false }
        do {
            let client = GatewayClient(baseURL: GatewayEndpoint.resolve(ProcessInfo.processInfo.environment))
            skills = try await client.runtimeSkills()
            loaded = true
            if let category = selectedCategory, !categories.contains(category) {
                selectedCategory = nil
            }
        } catch let error as GatewayClient.Failure where error.statusCode == 404 || error.statusCode == 501 {
            loaded = false
            loadError = "This Gateway does not support the runtime skills catalog."
        } catch let error as GatewayClient.Failure where error.statusCode == 401 || error.statusCode == 403 {
            loaded = false
            loadError = "Gateway access denied. Check the Mac app caller authorization, then refresh."
        } catch is CancellationError {
            loaded = false
        } catch let error as URLError where error.code == .cancelled {
            loaded = false
        } catch {
            loaded = false
            loadError = "Gateway catalog unavailable. Check the connection and caller authorization, then refresh. " + error.localizedDescription
        }
    }

    private func categoryFilterPill(title: String, category: String?) -> some View {
        let isSelected = selectedCategory == category
        return Button {
            selectedCategory = category
        } label: {
            Text(title)
                .font(.system(size: 11, weight: isSelected ? .semibold : .regular))
                .foregroundColor(isSelected ? Term.ink : Term.inkDim)
                .padding(.horizontal, 10)
                .padding(.vertical, 4)
                .background(isSelected ? Color.white.opacity(0.12) : Color.white.opacity(0.03))
                .cornerRadius(12)
        }
        .buttonStyle(.plain)
    }

    private func skillCard(_ skill: GatewayClient.RuntimeSkill) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(skill.category.uppercased())
                    .font(.system(size: 9, weight: .bold, design: .monospaced))
                    .foregroundColor(Color.orange)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(Color.orange.opacity(0.15))
                    .cornerRadius(4)

                Spacer()

                Text(skill.lifecycle)
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundColor(Term.inkDim)
            }

            Text(skill.name)
                .font(.system(size: 14, weight: .semibold))
                .foregroundColor(Term.ink)

            Text(skill.description)
                .font(.system(size: 12))
                .foregroundColor(Term.inkDim)
                .lineLimit(3)

            Spacer(minLength: 0)
        }
        .padding(12)
        .frame(height: 120, alignment: .topLeading)
        .background(Color.white.opacity(0.02))
        .cornerRadius(8)
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(Color.white.opacity(0.06), lineWidth: 1)
        )
    }
}
