/**
 * Command Palette — Cmd+K global command palette
 *
 * Ported from OpenClaw's UI pattern.
 * Provides quick access to all actions via keyboard.
 */

import { useState, useEffect, useCallback, useMemo } from 'react'
import { Command } from 'cmdk'
import {
  Search,
  MessageSquare,
  Plus,
  Settings,
  Moon,
  Sun,
  FolderOpen,
  Terminal,
  Mic,
  MicOff,
  RefreshCw,
  Trash2,
  Download,
  Upload,
  User,
  Bot,
  Zap,
  Clock,
  Star,
  Archive,
  type LucideIcon,
} from 'lucide-react'
import { cn } from '../lib/utils'

export interface CommandItem {
  id: string
  label: string
  shortcut?: string
  icon?: LucideIcon
  category?: string
  action: () => void
  keywords?: string[]
}

interface CommandPaletteProps {
  commands: CommandItem[]
  placeholder?: string
}

export function CommandPalette({
  commands,
  placeholder = 'Type a command or search...',
}: CommandPaletteProps) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')

  // Toggle with Cmd+K / Ctrl+K
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === 'k' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        setOpen((open) => !open)
      }
      // Close on Escape
      if (e.key === 'Escape') {
        setOpen(false)
      }
    }

    document.addEventListener('keydown', down)
    return () => document.removeEventListener('keydown', down)
  }, [])

  // Group commands by category
  const groupedCommands = useMemo(() => {
    const groups: Record<string, CommandItem[]> = {}
    commands.forEach((cmd) => {
      const category = cmd.category || 'General'
      if (!groups[category]) groups[category] = []
      groups[category].push(cmd)
    })
    return groups
  }, [commands])

  const handleSelect = useCallback((command: CommandItem) => {
    setOpen(false)
    setSearch('')
    command.action()
  }, [])

  return (
    <Command.Dialog
      open={open}
      onOpenChange={setOpen}
      label="Command Palette"
      className="fixed inset-0 z-50"
      overlayClassName="fixed inset-0 bg-black/50 backdrop-blur-sm"
    >
      <div className="fixed left-1/2 top-1/2 w-full max-w-2xl -translate-x-1/2 -translate-y-1/2 rounded-xl border border-border bg-popover shadow-2xl">
        <div className="flex items-center border-b border-border px-4">
          <Search className="mr-2 h-4 w-4 shrink-0 opacity-50" />
          <Command.Input
            value={search}
            onValueChange={setSearch}
            placeholder={placeholder}
            className="flex h-12 w-full rounded-md bg-transparent py-3 text-sm outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50"
          />
          <kbd className="pointer-events-none ml-2 hidden h-5 select-none items-center gap-1 rounded border border-border bg-muted px-1.5 font-mono text-[10px] font-medium opacity-100 sm:flex">
            ESC
          </kbd>
        </div>

        <Command.List className="max-h-[400px] overflow-y-auto p-2">
          <Command.Empty className="py-6 text-center text-sm text-muted-foreground">
            No results found.
          </Command.Empty>

          {Object.entries(groupedCommands).map(([category, items]) => (
            <Command.Group
              key={category}
              heading={category}
              className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground"
            >
              {items.map((command) => {
                const Icon = command.icon
                return (
                  <Command.Item
                    key={command.id}
                    value={`${command.label} ${command.keywords?.join(' ') || ''}`}
                    onSelect={() => handleSelect(command)}
                    className="relative flex cursor-pointer select-none items-center rounded-md px-2 py-2 text-sm outline-none hover:bg-accent hover:text-accent-foreground aria-selected:bg-accent aria-selected:text-accent-foreground"
                  >
                    {Icon && <Icon className="mr-2 h-4 w-4 opacity-70" />}
                    <span className="flex-1">{command.label}</span>
                    {command.shortcut && (
                      <kbd className="pointer-events-none ml-2 hidden h-5 select-none items-center gap-1 rounded border border-border bg-muted px-1.5 font-mono text-[10px] font-medium opacity-100 sm:flex">
                        {command.shortcut}
                      </kbd>
                    )}
                  </Command.Item>
                )
              })}
            </Command.Group>
          ))}
        </Command.List>

        <div className="flex items-center justify-between border-t border-border px-4 py-2 text-xs text-muted-foreground">
          <div className="flex items-center gap-4">
            <span className="flex items-center gap-1">
              <kbd className="rounded border border-border bg-muted px-1">↑</kbd>
              <kbd className="rounded border border-border bg-muted px-1">↓</kbd>
              to navigate
            </span>
            <span className="flex items-center gap-1">
              <kbd className="rounded border border-border bg-muted px-1">↵</kbd>
              to select
            </span>
          </div>
          <span>JaegerAI Command Palette</span>
        </div>
      </div>
    </Command.Dialog>
  )
}

// ─────────────────────────────────────────────────────────────
// Default commands factory
// ─────────────────────────────────────────────────────────────

export function createDefaultCommands(actions: {
  newChat: () => void
  openSettings: () => void
  toggleTheme: () => void
  toggleSidebar: () => void
  openFiles: () => void
  openTerminal: () => void
  toggleVoice: () => void
  refresh: () => void
  clearSession: () => void
  exportSession: () => void
  importSession: () => void
  switchAgent: () => void
  openShortcuts: () => void
  scheduleTask: () => void
  viewMemory: () => void
  runBenchmark: () => void
}): CommandItem[] {
  return [
    // Chat
    {
      id: 'new-chat',
      label: 'New Chat',
      shortcut: '⌘N',
      icon: Plus,
      category: 'Chat',
      action: actions.newChat,
      keywords: ['create', 'start', 'conversation'],
    },
    {
      id: 'clear-session',
      label: 'Clear Current Session',
      shortcut: '⌘K',
      icon: Trash2,
      category: 'Chat',
      action: actions.clearSession,
      keywords: ['delete', 'reset', 'clear'],
    },
    {
      id: 'export-session',
      label: 'Export Session',
      icon: Download,
      category: 'Chat',
      action: actions.exportSession,
      keywords: ['save', 'download', 'backup'],
    },
    {
      id: 'import-session',
      label: 'Import Session',
      icon: Upload,
      category: 'Chat',
      action: actions.importSession,
      keywords: ['load', 'restore', 'upload'],
    },

    // View
    {
      id: 'toggle-theme',
      label: 'Toggle Theme',
      shortcut: '⌘⇧L',
      icon: Sun,
      category: 'View',
      action: actions.toggleTheme,
      keywords: ['dark', 'light', 'mode', 'appearance'],
    },
    {
      id: 'toggle-sidebar',
      label: 'Toggle Sidebar',
      shortcut: '⌘B',
      icon: FolderOpen,
      category: 'View',
      action: actions.toggleSidebar,
      keywords: ['hide', 'show', 'panel'],
    },

    // Tools
    {
      id: 'open-files',
      label: 'Open Files',
      shortcut: '⌘O',
      icon: FolderOpen,
      category: 'Tools',
      action: actions.openFiles,
      keywords: ['file', 'explorer', 'browse'],
    },
    {
      id: 'open-terminal',
      label: 'Open Terminal',
      shortcut: '⌘`',
      icon: Terminal,
      category: 'Tools',
      action: actions.openTerminal,
      keywords: ['shell', 'console', 'command'],
    },
    {
      id: 'toggle-voice',
      label: 'Toggle Voice Mode',
      shortcut: '⌘M',
      icon: Mic,
      category: 'Tools',
      action: actions.toggleVoice,
      keywords: ['audio', 'speech', 'talk', 'mic'],
    },

    // Agent
    {
      id: 'switch-agent',
      label: 'Switch Agent',
      icon: Bot,
      category: 'Agent',
      action: actions.switchAgent,
      keywords: ['change', 'personality', 'character'],
    },
    {
      id: 'view-memory',
      label: 'View Memory',
      icon: Clock,
      category: 'Agent',
      action: actions.viewMemory,
      keywords: ['remember', 'recall', 'history', 'knowledge'],
    },

    // System
    {
      id: 'refresh',
      label: 'Refresh',
      shortcut: '⌘R',
      icon: RefreshCw,
      category: 'System',
      action: actions.refresh,
      keywords: ['reload', 'update'],
    },
    {
      id: 'open-settings',
      label: 'Settings',
      shortcut: '⌘,',
      icon: Settings,
      category: 'System',
      action: actions.openSettings,
      keywords: ['preferences', 'config', 'options'],
    },
    {
      id: 'open-shortcuts',
      label: 'Keyboard Shortcuts',
      shortcut: '⌘/',
      icon: Zap,
      category: 'System',
      action: actions.openShortcuts,
      keywords: ['hotkeys', 'keys', 'help'],
    },
    {
      id: 'schedule-task',
      label: 'Schedule Task',
      icon: Clock,
      category: 'System',
      action: actions.scheduleTask,
      keywords: ['cron', 'reminder', 'timer', 'later'],
    },
    {
      id: 'run-benchmark',
      label: 'Run Benchmark',
      icon: Zap,
      category: 'System',
      action: actions.runBenchmark,
      keywords: ['test', 'performance', 'speed'],
    },
  ]
}

// ─────────────────────────────────────────────────────────────
// Hook for using command palette
// ─────────────────────────────────────────────────────────────

export function useCommandPalette(commands: CommandItem[]) {
  const [isOpen, setIsOpen] = useState(false)

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === 'k' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        setIsOpen((open) => !open)
      }
    }
    document.addEventListener('keydown', down)
    return () => document.removeEventListener('keydown', down)
  }, [])

  return { isOpen, setIsOpen, CommandPalette: () => <CommandPalette commands={commands} /> }
}
