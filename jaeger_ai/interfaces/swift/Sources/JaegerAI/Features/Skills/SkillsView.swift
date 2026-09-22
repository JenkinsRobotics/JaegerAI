//
//  SkillsView.swift
//  JaegerAI / Features / Skills
//
//  Desktop skills explorer view ported from Hermex architecture.
//

import SwiftUI

public struct SkillsView: View {
    @State private var skills = SkillItem.sampleCatalog
    @State private var searchText = ""
    @State private var selectedCategory: String? = nil

    public init() {}

    private var categories: [String] {
        Array(Set(skills.map(\.category))).sorted()
    }

    private var filteredSkills: [SkillItem] {
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

                Text("\(skills.count) installed")
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

    private func skillCard(_ skill: SkillItem) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(skill.category.uppercased())
                    .font(.system(size: 9, weight: .bold, design: .monospaced))
                    .foregroundColor(skill.categoryColor)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(skill.categoryColor.opacity(0.15))
                    .cornerRadius(4)

                Spacer()

                Text("\(skill.toolCount) tools")
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
