/**
 * ChatGPT-Style Message Component
 *
 * Key differences from previous implementation:
 * 1. Assistant messages have NO bubble (transparent, ChatGPT style)
 * 2. User messages have subtle gray bubble (iMessage style)
 * 3. Consecutive messages are grouped (avatar hidden)
 * 4. SF Pro typography
 * 5. System colors
 * 6. Smooth animations (Apple spring)
 * 7. Voice orb visualization
 */

import { useState, useCallback, useRef, useEffect } from 'react'
import {
  Copy,
  Check,
  RefreshCw,
  ThumbsUp,
  ThumbsDown,
  MoreHorizontal,
  Pencil,
  Trash2,
  Share,
  Volume2,
} from 'lucide-react'
import { cn } from '../lib/utils'
import { MarkdownRenderer } from './MarkdownRenderer'
import { UploadedFile } from './FileUpload'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
  isStreaming?: boolean
  isGrouped?: boolean  // True if part of a group (no avatar)
  attachments?: UploadedFile[]
  toolCalls?: ToolCall[]
  error?: string
}

export interface ToolCall {
  id: string
  name: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  result?: string
}

interface ChatGPTMessageProps {
  message: ChatMessage
  isGrouped?: boolean
  onRegenerate?: () => void
  onEdit?: (content: string) => void
  onDelete?: () => void
  onCopy?: () => void
  onFeedback?: (type: 'up' | 'down') => void
  onShare?: () => void
  onReadAloud?: () => void
  className?: string
}

/**
 * Format timestamp — Apple style (relative)
 */
function formatTime(timestamp: number): string {
  const date = new Date(timestamp)
  const now = new Date()
  const diff = now.getTime() - date.getTime()

  if (diff < 60000) return 'Just now'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`
  if (diff < 86400000) {
    return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  }
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

/**
 * Get avatar content for message sender
 */
function getAvatarContent(role: string) {
  // Would use actual avatar image or initials
  return role === 'user' ? 'U' : 'J'
}

export function ChatGPTMessage({
  message,
  isGrouped = false,
  onRegenerate,
  onEdit,
  onDelete,
  onCopy,
  onFeedback,
  onShare,
  onReadAloud,
  className,
}: ChatGPTMessageProps) {
  const [copied, setCopied] = useState(false)
  const [feedback, setFeedback] = useState<'up' | 'down' | null>(null)
  const [isEditing, setIsEditing] = useState(false)
  const [editContent, setEditContent] = useState(message.content)
  const editRef = useRef<HTMLTextAreaElement>(null)

  const isUser = message.role === 'user'
  const isAssistant = message.role === 'assistant'

  useEffect(() => {
    if (isEditing && editRef.current) {
      editRef.current.focus()
      editRef.current.setSelectionRange(
        editRef.current.value.length,
        editRef.current.value.length
      )
    }
  }, [isEditing])

  const handleCopy = useCallback(async () => {
    await navigator.clipboard.writeText(message.content)
    setCopied(true)
    onCopy?.()
    setTimeout(() => setCopied(false), 2000)
  }, [message.content, onCopy])

  const handleEdit = useCallback(() => {
    setIsEditing(true)
  }, [])

  const handleSaveEdit = useCallback(() => {
    onEdit?.(editContent)
    setIsEditing(false)
  }, [editContent, onEdit])

  const handleCancelEdit = useCallback(() => {
    setEditContent(message.content)
    setIsEditing(false)
  }, [message.content])

  const handleFeedback = useCallback((type: 'up' | 'down') => {
    setFeedback(type)
    onFeedback?.(type)
  }, [onFeedback])

  return (
    <div
      className={cn(
        'message',
        message.role,
        isGrouped && 'grouped',
        className
      )}
    >
      {/* Avatar — hidden on grouped messages */}
      <div className="message-avatar" aria-hidden={isGrouped}>
        {getAvatarContent(message.role)}
      </div>

      <div className="message-content">
        {/* Message Content */}
        {isEditing ? (
          /* Edit Mode */
          <div className="edit-container">
            <textarea
              ref={editRef}
              value={editContent}
              onChange={e => setEditContent(e.target.value)}
              className="edit-textarea"
              rows={Math.min(editContent.split('\n').length, 10)}
            />
            <div className="edit-actions">
              <button onClick={handleCancelEdit} className="btn btn-ghost btn-sm">
                Cancel
              </button>
              <button onClick={handleSaveEdit} className="btn btn-primary btn-sm">
                Save
              </button>
            </div>
          </div>
        ) : (
          /* Display Mode */
          <>
            {/* User: Bubble, Assistant: Prose (no bubble) */}
            {isUser ? (
              <div className="message-bubble user">
                {message.content}
              </div>
            ) : (
              <div className="message-prose">
                <MarkdownRenderer
                  content={message.content}
                  isStreaming={message.isStreaming}
                />
                {message.isStreaming && (
                  <span className="streaming-caret" aria-hidden="true" />
                )}
              </div>
            )}

            {/* Tool calls */}
            {message.toolCalls && message.toolCalls.length > 0 && (
              <div className="tool-calls">
                {message.toolCalls.map(tool => (
                  <div key={tool.id} className="tool-call-badge">
                    <span className="tool-name">{tool.name}</span>
                    <span className={cn('tool-status', tool.status)}>
                      {tool.status === 'running' && '...'}
                      {tool.status === 'completed' && '✓'}
                      {tool.status === 'failed' && '✗'}
                    </span>
                  </div>
                ))}
              </div>
            )}

            {/* Attachments */}
            {message.attachments && message.attachments.length > 0 && (
              <div className="attachment-preview">
                {message.attachments.map(file => (
                  <div key={file.id} className="attachment-chip">
                    {file.preview ? (
                      <img src={file.preview} alt={file.name} />
                    ) : (
                      <span>{file.name}</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {/* Meta: Timestamp + Actions */}
        {!isEditing && (
          <div className="message-meta">
            <span className="message-time">{formatTime(message.timestamp)}</span>

            {/* Actions — visible on hover (desktop) or always (touch) */}
            <div className="message-actions">
              {/* Copy */}
              <button
                onClick={handleCopy}
                className="message-action-button"
                title="Copy"
                aria-label="Copy message"
              >
                {copied ? <Check size={16} /> : <Copy size={16} />}
              </button>

              {/* Assistant-only actions */}
              {isAssistant && !message.isStreaming && (
                <>
                  <button
                    onClick={onRegenerate}
                    className="message-action-button"
                    title="Regenerate"
                    aria-label="Regenerate response"
                  >
                    <RefreshCw size={16} />
                  </button>

                  <button
                    onClick={onReadAloud}
                    className="message-action-button"
                    title="Read aloud"
                    aria-label="Read message aloud"
                  >
                    <Volume2 size={16} />
                  </button>

                  <button
                    onClick={() => handleFeedback('up')}
                    className={cn(
                      'message-action-button',
                      feedback === 'up' && 'active'
                    )}
                    title="Good response"
                    aria-label="Good response"
                  >
                    <ThumbsUp size={16} />
                  </button>

                  <button
                    onClick={() => handleFeedback('down')}
                    className={cn(
                      'message-action-button',
                      feedback === 'down' && 'active'
                    )}
                    title="Bad response"
                    aria-label="Bad response"
                  >
                    <ThumbsDown size={16} />
                  </button>

                  <button
                    onClick={onShare}
                    className="message-action-button"
                    title="Share"
                    aria-label="Share message"
                  >
                    <Share size={16} />
                  </button>
                </>
              )}

              {/* User-only actions */}
              {isUser && (
                <>
                  <button
                    onClick={handleEdit}
                    className="message-action-button"
                    title="Edit"
                    aria-label="Edit message"
                  >
                    <Pencil size={16} />
                  </button>

                  <button
                    onClick={onDelete}
                    className="message-action-button"
                    title="Delete"
                    aria-label="Delete message"
                  >
                    <Trash2 size={16} />
                  </button>
                </>
              )}

              {/* More actions */}
              <button
                className="message-action-button"
                title="More"
                aria-label="More actions"
              >
                <MoreHorizontal size={16} />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

/**
 * Group messages by sender for ChatGPT-style display
 */
export function groupMessagesBySender(messages: ChatMessage[]): Map<string, ChatMessage[]> {
  const groups = new Map<string, ChatMessage[]>()
  
  messages.forEach(msg => {
    const existing = groups.get(msg.role) || []
    groups.set(msg.role, [...existing, msg])
  })
  
  return groups
}

/**
 * Check if message should be grouped with previous
 */
export function shouldGroupWithPrevious(
  current: ChatMessage,
  previous: ChatMessage | undefined
): boolean {
  if (!previous) return false
  if (current.role !== previous.role) return false
  // Group if within 5 minutes
  return (current.timestamp - previous.timestamp) < 300000
}

/**
 * Get grouped message list for rendering
 */
export function getGroupedMessages(messages: ChatMessage[]): ChatMessage[] {
  return messages.map((msg, i) => ({
    ...msg,
    isGrouped: shouldGroupWithPrevious(msg, messages[i - 1]),
  }))
}
