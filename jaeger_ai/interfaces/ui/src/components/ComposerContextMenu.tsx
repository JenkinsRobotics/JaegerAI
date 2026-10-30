/**
 * ComposerContextMenu — ChatGPT-style "+" menu for the chat composer
 *
 * Opens when clicking the "+" button in the chat input.
 * Provides context options like:
 * - Add files/photos
 * - Add from apps (plugins/connectors)
 * - Create image
 * - Web search
 * - Deep research
 * - Canvas
 * - etc.
 */

import React, { useEffect, useRef, useState } from 'react'
import {
  Paperclip,
  Image as ImageIcon,
  Globe,
  Search,
  Sparkles,
  FileText,
  Link,
  GraduationCap,
  Bot,
  X,
} from './Icons'

// ─────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────

export interface ContextMenuItem {
  id: string
  label: string
  description?: string
  icon: React.ComponentType<{ size?: number; className?: string }>
  onClick: () => void
  disabled?: boolean
  badge?: string
  shortcut?: string
}

export interface ContextMenuGroup {
  items: ContextMenuItem[]
  separator?: boolean
}

interface ComposerContextMenuProps {
  isOpen: boolean
  anchorRef: React.RefObject<HTMLElement | null>
  onClose: () => void
  onAddFiles: () => void
  onAddImages: () => void
  onAddFromApps?: () => void
  onCreateImage?: () => void
  onWebSearch?: () => void
  onDeepResearch?: () => void
  onCanvas?: () => void
  onStudyAndLearn?: () => void
  onAgentMode?: () => void
  availablePlugins?: Array<{ id: string; name: string; icon?: string }>
}

// ─────────────────────────────────────────────────────────────
// ComposerContextMenu Component
// ─────────────────────────────────────────────────────────────

export function ComposerContextMenu({
  isOpen,
  anchorRef,
  onClose,
  onAddFiles,
  onAddImages,
  onAddFromApps,
  onCreateImage,
  onWebSearch,
  onDeepResearch,
  onCanvas,
  onStudyAndLearn,
  onAgentMode,
  availablePlugins = [],
}: ComposerContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null)
  const [position, setPosition] = useState({ bottom: 0, left: 0 })

  // Calculate position relative to anchor
  useEffect(() => {
    if (isOpen && anchorRef.current && menuRef.current) {
      const anchorRect = anchorRef.current.getBoundingClientRect()
      setPosition({
        bottom: window.innerHeight - anchorRect.top + 8,
        left: anchorRect.left,
      })
    }
  }, [isOpen, anchorRef])

  // Close on click outside
  useEffect(() => {
    if (!isOpen) return

    const handleClickOutside = (e: MouseEvent) => {
      if (
        menuRef.current &&
        !menuRef.current.contains(e.target as Node) &&
        anchorRef.current &&
        !anchorRef.current.contains(e.target as Node)
      ) {
        onClose()
      }
    }

    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }

    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('keydown', handleEscape)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleEscape)
    }
  }, [isOpen, onClose, anchorRef])

  if (!isOpen) return null

  // Build menu groups
  const groups: ContextMenuGroup[] = [
    {
      items: [
        {
          id: 'add-files',
          label: 'Add files',
          description: 'Upload documents, PDFs, and more',
          icon: Paperclip,
          onClick: () => { onAddFiles(); onClose() },
        },
        {
          id: 'add-photos',
          label: 'Add photos & images',
          description: 'Upload images for analysis',
          icon: ImageIcon,
          onClick: () => { onAddImages(); onClose() },
        },
        ...(onAddFromApps ? [{
          id: 'add-from-apps',
          label: 'Add from apps',
          description: 'Connect Google Drive, Dropbox, etc.',
          icon: Link,
          onClick: () => { onAddFromApps(); onClose() },
        }] : []),
      ],
    },
    {
      separator: true,
      items: [
        ...(onCreateImage ? [{
          id: 'create-image',
          label: 'Create image',
          description: 'Generate images with DALL·E',
          icon: Sparkles,
          onClick: () => { onCreateImage(); onClose() },
        }] : []),
        ...(onWebSearch ? [{
          id: 'web-search',
          label: 'Web search',
          description: 'Search the web for current information',
          icon: Globe,
          onClick: () => { onWebSearch(); onClose() },
        }] : []),
        ...(onDeepResearch ? [{
          id: 'deep-research',
          label: 'Deep research',
          description: 'Get in-depth analysis on complex topics',
          icon: Search,
          onClick: () => { onDeepResearch(); onClose() },
        }] : []),
      ],
    },
    {
      separator: true,
      items: [
        ...(onCanvas ? [{
          id: 'canvas',
          label: 'Canvas',
          description: 'Edit text and code with AI assistance',
          icon: FileText,
          onClick: () => { onCanvas(); onClose() },
        }] : []),
        ...(onStudyAndLearn ? [{
          id: 'study',
          label: 'Study and learn',
          description: 'Interactive learning mode',
          icon: GraduationCap,
          onClick: () => { onStudyAndLearn(); onClose() },
        }] : []),
      ],
    },
    {
      separator: true,
      items: [
        ...(onAgentMode ? [{
          id: 'agent-mode',
          label: 'Agent mode',
          description: 'Let the AI browse and act autonomously',
          icon: Bot,
          onClick: () => { onAgentMode(); onClose() },
          badge: 'Beta',
        }] : []),
      ],
    },
    // Add connected apps/plugins if available
    ...(availablePlugins.length > 0 ? [{
      separator: true,
      items: availablePlugins.map((plugin) => ({
        id: `plugin-${plugin.id}`,
        label: plugin.name,
        description: 'Connect and use this app',
        icon: Link,
        onClick: () => { onClose(); /* TODO: handle plugin */ },
      })),
    }] : []),
  ]

  return (
    <div
      ref={menuRef}
      className="composer-context-menu"
      style={{
        position: 'fixed',
        bottom: `${position.bottom}px`,
        left: `${position.left}px`,
        zIndex: 10001,
      }}
      role="menu"
      aria-label="Add context"
    >
      <div className="composer-context-menu__content">
        {groups.map((group, groupIndex) => (
          <div key={groupIndex}>
            {groupIndex > 0 && group.separator && (
              <div className="composer-context-menu__separator" />
            )}
            {group.items.map((item) => {
              const Icon = item.icon
              return (
                <button
                  key={item.id}
                  className="composer-context-menu__item"
                  onClick={item.onClick}
                  disabled={item.disabled}
                  role="menuitem"
                >
                  <div className="composer-context-menu__icon">
                    <Icon size={20} />
                  </div>
                  <div className="composer-context-menu__text">
                    <div className="composer-context-menu__label">
                      {item.label}
                      {item.badge && (
                        <span className="composer-context-menu__badge">{item.badge}</span>
                      )}
                    </div>
                    {item.description && (
                      <div className="composer-context-menu__description">
                        {item.description}
                      </div>
                    )}
                  </div>
                  {item.shortcut && (
                    <div className="composer-context-menu__shortcut">{item.shortcut}</div>
                  )}
                </button>
              )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// Attachment Chips Component
// ─────────────────────────────────────────────────────────────

export interface Attachment {
  id: string
  name: string
  type: string
  size: number
  preview?: string // URL for image previews
  isImage?: boolean
}

interface AttachmentChipsProps {
  attachments: Attachment[]
  onRemove: (id: string) => void
}

export function AttachmentChips({ attachments, onRemove }: AttachmentChipsProps) {
  if (attachments.length === 0) return null

  const formatSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  }

  return (
    <div className="attachment-chips">
      {attachments.map((attachment) => (
        <div
          key={attachment.id}
          className={`attachment-chip${attachment.isImage ? ' attachment-chip--image' : ''}`}
        >
          {attachment.isImage && attachment.preview ? (
            <img
              src={attachment.preview}
              alt={attachment.name}
              className="attachment-chip__preview"
            />
          ) : (
            <div className="attachment-chip__icon">
              <FileText size={16} />
            </div>
          )}
          <div className="attachment-chip__info">
            <div className="attachment-chip__name" title={attachment.name}>
              {attachment.name}
            </div>
            <div className="attachment-chip__size">{formatSize(attachment.size)}</div>
          </div>
          <button
            className="attachment-chip__remove"
            onClick={() => onRemove(attachment.id)}
            aria-label={`Remove ${attachment.name}`}
          >
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  )
}

export default ComposerContextMenu
