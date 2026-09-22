//
//  KanbanView.swift
//  JaegerAI / Features / Kanban
//
//  Desktop-native Kanban board view ported and adapted from Hermex.
//

import SwiftUI

public struct KanbanView: View {
    @State private var board: KanbanBoard = KanbanBoard.sample
    @State private var selectedCard: KanbanCard? = nil
    @State private var showingAddCard = false
    @State private var filterQuery = ""
    @State private var newCardTitle = ""
    @State private var newCardBody = ""
    @State private var newCardStatus: KanbanStatus = .todo
    @State private var newCardPriority: Int = 3

    public init() {}

    private var filteredCards: [KanbanCard] {
        let q = filterQuery.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if q.isEmpty { return board.cards }
        return board.cards.filter {
            $0.title.lowercased().contains(q) || $0.body.lowercased().contains(q) || $0.tags.contains { $0.lowercased().contains(q) }
        }
    }

    public var body: some View {
        VStack(spacing: 0) {
            // Header bar
            HStack(spacing: 12) {
                HStack(spacing: 8) {
                    Image(systemName: "square.grid.3x1.folder.fill.badge.plus")
                        .font(.system(size: 14))
                        .foregroundColor(Color(red: 0.96, green: 0.55, blue: 0.16))
                    Text("Kanban Board")
                        .font(.system(size: 15, weight: .bold))
                        .foregroundColor(Term.ink)
                }

                Spacer()

                HStack(spacing: 8) {
                    Image(systemName: "magnifyingglass")
                        .foregroundColor(Term.inkDim)
                        .font(.system(size: 11))
                    TextField("Filter tasks...", text: $filterQuery)
                        .textFieldStyle(.plain)
                        .font(.system(size: 12))
                        .foregroundColor(Term.ink)
                        .frame(width: 140)
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .background(Color.white.opacity(0.06))
                .cornerRadius(6)

                Button {
                    showingAddCard = true
                } label: {
                    HStack(spacing: 4) {
                        Image(systemName: "plus")
                            .font(.system(size: 11, weight: .bold))
                        Text("Add Task")
                            .font(.system(size: 12, weight: .semibold))
                    }
                    .padding(.horizontal, 10)
                    .padding(.vertical, 4)
                    .background(Color(red: 0.96, green: 0.55, blue: 0.16))
                    .foregroundColor(.white)
                    .cornerRadius(6)
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background(Color.white.opacity(0.02))

            Rectangle().fill(Color.white.opacity(0.06)).frame(height: 1)

            // Board Columns
            ScrollView(.horizontal, showsIndicators: true) {
                HStack(alignment: .top, spacing: 14) {
                    ForEach(KanbanStatus.allCases) { status in
                        kanbanColumn(for: status)
                    }
                }
                .padding(16)
            }
        }
        .sheet(item: $selectedCard) { card in
            cardDetailSheet(for: card)
        }
        .sheet(isPresented: $showingAddCard) {
            addCardSheet
        }
    }

    private func kanbanColumn(for status: KanbanStatus) -> some View {
        let cards = filteredCards.filter { $0.status == status }
        return VStack(alignment: .leading, spacing: 10) {
            // Column Header
            HStack {
                HStack(spacing: 6) {
                    Circle()
                        .fill(status.color)
                        .frame(width: 8, height: 8)
                    Text(status.displayName)
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundColor(Term.ink)
                }
                Spacer()
                Text("\(cards.count)")
                    .font(.system(size: 11, weight: .bold, design: .monospaced))
                    .foregroundColor(Term.inkDim)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(Color.white.opacity(0.08))
                    .cornerRadius(4)
            }
            .padding(.horizontal, 4)
            .padding(.bottom, 2)

            // Cards in column
            ScrollView(.vertical, showsIndicators: false) {
                VStack(spacing: 8) {
                    ForEach(cards) { card in
                        cardRow(card)
                            .onTapGesture {
                                selectedCard = card
                            }
                    }
                }
            }
        }
        .frame(width: 240)
        .padding(10)
        .background(Color.white.opacity(0.02))
        .cornerRadius(10)
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .stroke(Color.white.opacity(0.06), lineWidth: 1)
        )
    }

    private func cardRow(_ card: KanbanCard) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(card.priorityLabel.uppercased())
                    .font(.system(size: 9, weight: .bold, design: .monospaced))
                    .foregroundColor(card.priorityColor)
                    .padding(.horizontal, 5)
                    .padding(.vertical, 2)
                    .background(card.priorityColor.opacity(0.15))
                    .cornerRadius(3)

                Spacer()

                if let assignee = card.assignee {
                    Text(assignee)
                        .font(.system(size: 10))
                        .foregroundColor(Term.inkDim)
                }
            }

            Text(card.title)
                .font(.system(size: 13, weight: .semibold))
                .foregroundColor(Term.ink)
                .lineLimit(2)

            if !card.body.isEmpty {
                Text(card.body)
                    .font(.system(size: 11))
                    .foregroundColor(Term.inkDim)
                    .lineLimit(3)
            }

            if !card.tags.isEmpty {
                HStack(spacing: 4) {
                    ForEach(card.tags.prefix(3), id: \.self) { tag in
                        Text("#\(tag)")
                            .font(.system(size: 9))
                            .foregroundColor(Color.blue.opacity(0.8))
                    }
                }
                .padding(.top, 2)
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(red: 0.12, green: 0.13, blue: 0.16))
        .cornerRadius(8)
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(Color.white.opacity(0.08), lineWidth: 1)
        )
    }

    private func cardDetailSheet(for card: KanbanCard) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text("Task Details")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundColor(Term.ink)
                Spacer()
                Button("Done") {
                    selectedCard = nil
                }
                .controlSize(.small)
            }

            VStack(alignment: .leading, spacing: 4) {
                Text("Title")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundColor(Term.inkDim)
                Text(card.title)
                    .font(.system(size: 14, weight: .medium))
                    .foregroundColor(Term.ink)
            }

            if !card.body.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Description")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundColor(Term.inkDim)
                    Text(card.body)
                        .font(.system(size: 12))
                        .foregroundColor(Term.ink)
                }
            }

            // Move Status Action
            VStack(alignment: .leading, spacing: 6) {
                Text("Move to Status:")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundColor(Term.inkDim)

                HStack(spacing: 8) {
                    ForEach(KanbanStatus.allCases) { status in
                        Button {
                            moveCard(card.id, to: status)
                        } label: {
                            HStack(spacing: 4) {
                                Image(systemName: status.icon)
                                    .font(.system(size: 10))
                                Text(status.displayName)
                                    .font(.system(size: 11))
                            }
                            .padding(.horizontal, 8)
                            .padding(.vertical, 4)
                            .background(card.status == status ? status.color.opacity(0.25) : Color.white.opacity(0.05))
                            .foregroundColor(card.status == status ? status.color : Term.inkDim)
                            .cornerRadius(5)
                        }
                        .buttonStyle(.plain)
                    }
                }
            }

            HStack {
                Button(role: .destructive) {
                    deleteCard(card.id)
                    selectedCard = nil
                } label: {
                    Label("Delete Task", systemImage: "trash")
                        .font(.system(size: 12))
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
            }
            .padding(.top, 8)

            Spacer()
        }
        .padding(20)
        .frame(width: 480, height: 360)
        .background(Color(red: 0.10, green: 0.11, blue: 0.14))
    }

    private var addCardSheet: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Create New Task")
                .font(.system(size: 16, weight: .bold))
                .foregroundColor(Term.ink)

            TextField("Task title...", text: $newCardTitle)
                .textFieldStyle(.roundedBorder)

            TextEditor(text: $newCardBody)
                .frame(height: 80)
                .border(Color.white.opacity(0.1), width: 1)

            HStack {
                Text("Status:")
                    .font(.system(size: 12))
                    .foregroundColor(Term.inkDim)
                Picker("", selection: $newCardStatus) {
                    ForEach(KanbanStatus.allCases) { st in
                        Text(st.displayName).tag(st)
                    }
                }
                .pickerStyle(.menu)
                .frame(width: 140)

                Spacer()

                Text("Priority:")
                    .font(.system(size: 12))
                    .foregroundColor(Term.inkDim)
                Picker("", selection: $newCardPriority) {
                    Text("Urgent").tag(1)
                    Text("High").tag(2)
                    Text("Medium").tag(3)
                    Text("Low").tag(4)
                }
                .pickerStyle(.menu)
                .frame(width: 110)
            }

            HStack {
                Spacer()
                Button("Cancel") {
                    showingAddCard = false
                }
                Button("Create Task") {
                    let card = KanbanCard(
                        title: newCardTitle,
                        body: newCardBody,
                        status: newCardStatus,
                        priority: newCardPriority,
                        assignee: "Jaeger"
                    )
                    board.cards.append(card)
                    newCardTitle = ""
                    newCardBody = ""
                    showingAddCard = false
                }
                .buttonStyle(.borderedProminent)
                .disabled(newCardTitle.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
            .padding(.top, 8)
        }
        .padding(20)
        .frame(width: 440, height: 280)
        .background(Color(red: 0.10, green: 0.11, blue: 0.14))
    }

    private func moveCard(_ id: String, to status: KanbanStatus) {
        if let idx = board.cards.firstIndex(where: { $0.id == id }) {
            board.cards[idx].status = status
            board.cards[idx].updatedAt = Date()
            selectedCard = board.cards[idx]
        }
    }

    private func deleteCard(_ id: String) {
        board.cards.removeAll { $0.id == id }
    }
}
