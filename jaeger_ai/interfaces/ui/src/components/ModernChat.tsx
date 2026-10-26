/**
 * Modern Chat — Premium messaging interface
 *
 * Features:
 * - Beautiful message bubbles
 * - Typing indicators
 * - Message actions (copy, regenerate, etc.)
 * - Auto-expanding input
 * - File attachments
 * - Voice input
 * - Streaming responses
 * - Timestamps
 */

import { useState, useRef, useEffect, useCallback } from 'react'
import {
  Send,
  Paperclip,
  Mic,
  MicOff,
  Copy,
  Check,
  RefreshCw,
  ThumbsUp,
  ThumbsDown,
  MoreHorizontal,
  Square,
  Sparkles,
  Bot,
  User,
} from 'lucide-react'
import { cn } from '../lib/utils'
import { MarkdownRenderer } from './MarkdownRenderer'
import { FileUpload, UploadedFile } from './FileUpload'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
  isStreaming?: boolean
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

interface ModernChatProps {
  messages: ChatMessage[]
  onSendMessage: (message: string, attachments?: UploadedFile[]) => void
  onStopGeneration?: () => void
  isGenerating?: boolean
  className?: string
}

function formatTime(timestamp: number): string {
  const date = new Date(timestamp)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  
  if (diff < 60000) return 'Just now'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`
  if (diff < 86400000) return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const [copied, setCopied] = useState(false)
  const [feedback, setFeedback] = useState<'up' | 'down' | null>(null)

  const copyToClipboard = useCallback(async () => {
    await navigator.clipboard.writeText(message.content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }, [message.content])

  const isUser = message.role === 'user'

  return (
    <div className={cn('message', message.role)}>
      <div className="message-avatar">
        {isUser ? <User size={18} /> : <Bot size={18} />}
      </div>
      <div className="message-content">
        <div className="message-bubble">
          {message.isStreaming ? (
            <MarkdownRenderer content={message.content} />
          ) : isUser ? (
            <span style={{ whiteSpace: 'pre-wrap' }}>{message.content}</span>
          ) : (
            <MarkdownRenderer content={message.content} />
          )}
          {message.isStreaming && (
            <span className="typing-indicator" style={{ display: 'inline-flex', marginLeft: 'var(--space-2)' }}>
              <span className="typing-dot" />
              <span className="typing-dot" />
              <span className="typing-dot" />
            </span>
          )}
        </div>
        
        {/* Tool calls */}
        {message.toolCalls && message.toolCalls.length > 0 && (
          <div className="tool-calls" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
            {message.toolCalls.map(tool => (
              <div
                key={tool.id}
                className="badge badge-primary"
                style={{ alignSelf: 'flex-start' }}
              >
                <Sparkles size={12} />
                {tool.name}
                {tool.status === 'running' && '...'}
                {tool.status === 'completed' && ' ✓'}
                {tool.status === 'failed' && ' ✗'}
              </div>
            ))}
          </div>
        )}
        
        {/* Attachments */}
        {message.attachments && message.attachments.length > 0 && (
          <div className="attachment-preview">
            {message.attachments.map(file => (
              <div key={file.id} className="attachment-item">
                {file.preview ? (
                  <img src={file.preview} alt={file.name} style={{ width: 40, height: 40, objectFit: 'cover', borderRadius: 'var(--radius-md)' }} />
                ) : (
                  <span style={{ fontSize: 'var(--text-xs)' }}>{file.name}</span>
                )}
              </div>
            ))}
          </div>
        )}
        
        {/* Meta & Actions */}
        <div className="message-meta">
          <span>{formatTime(message.timestamp)}</span>
          {!isUser && !message.isStreaming && (
            <div className="message-actions">
              <button
                className="message-action-button"
                onClick={copyToClipboard}
                title="Copy"
              >
                {copied ? <Check size={14} /> : <Copy size={14} />}
              </button>
              <button
                className="message-action-button"
                title="Regenerate"
              >
                <RefreshCw size={14} />
              </button>
              <button
                className={cn('message-action-button', feedback === 'up' && 'text-green-500')}
                onClick={() => setFeedback(feedback === 'up' ? null : 'up')}
                title="Good response"
              >
                <ThumbsUp size={14} />
              </button>
              <button
                className={cn('message-action-button', feedback === 'down' && 'text-red-500')}
                onClick={() => setFeedback(feedback === 'down' ? null : 'down')}
                title="Bad response"
              >
                <ThumbsDown size={14} />
              </button>
              <button
                className="message-action-button"
                title="More actions"
              >
                <MoreHorizontal size={14} />
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function EmptyState({ onSuggestionClick }: { onSuggestionClick: (text: string) => void }) {
  const suggestions = [
    { icon: Sparkles, text: 'Explain a complex topic', prompt: 'Explain quantum computing in simple terms' },
    { icon: Bot, text: 'Write some code', prompt: 'Write a Python function to sort a list' },
    { icon: RefreshCw, text: 'Brainstorm ideas', prompt: 'Give me 5 creative project ideas' },
  ]

  return (
    <div className="empty-state" style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ textAlign: 'center', maxWidth: 500 }}>
        <div className="empty-state-icon" style={{ margin: '0 auto var(--space-6)' }}>
          <Sparkles size={40} />
        </div>
        <h2 className="empty-state-title">How can I help you today?</h2>
        <p className="empty-state-description">
          I'm Jaeger — your AI companion. Ask me anything, upload files, or let me help with your projects.
        </p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)', marginTop: 'var(--space-6)' }}>
          {suggestions.map((s, i) => (
            <button
              key={i}
              className="card"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 'var(--space-3)',
                padding: 'var(--space-3) var(--space-4)',
                cursor: 'pointer',
                textAlign: 'left',
                width: '100%',
              }}
              onClick={() => onSuggestionClick(s.prompt)}
            >
              <s.icon size={20} style={{ color: 'var(--brand-primary)' }} />
              <div>
                <div style={{ fontWeight: 'var(--font-medium)', color: 'var(--text-primary)' }}>{s.text}</div>
                <div style={{ fontSize: 'var(--text-sm)', color: 'var(--text-muted)' }}>{s.prompt}</div>
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

export function ModernChat({
  messages,
  onSendMessage,
  onStopGeneration,
  isGenerating = false,
  className,
}: ModernChatProps) {
  const [input, setInput] = useState('')
  const [attachments, setAttachments] = useState<UploadedFile[]>([])
  const [isRecording, setIsRecording] = useState(false)
  const [showFileUpload, setShowFileUpload] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`
    }
  }, [input])

  const handleSend = useCallback(() => {
    if (!input.trim() && attachments.length === 0) return
    if (isGenerating) return
    
    onSendMessage(input, attachments.length > 0 ? attachments : undefined)
    setInput('')
    setAttachments([])
    setShowFileUpload(false)
  }, [input, attachments, isGenerating, onSendMessage])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }, [handleSend])

  const handleFilesUploaded = useCallback((files: UploadedFile[]) => {
    setAttachments(prev => [...prev, ...files])
    setShowFileUpload(false)
  }, [])

  const removeAttachment = useCallback((fileId: string) => {
    setAttachments(prev => prev.filter(f => f.id !== fileId))
  }, [])

  return (
    <div className={cn('chat-container', className)}>
      {/* Messages */}
      <div className="chat-messages">
        {messages.length === 0 ? (
          <EmptyState onSuggestionClick={(text) => setInput(text)} />
        ) : (
          <>
            {messages.map(message => (
              <MessageBubble key={message.id} message={message} />
            ))}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* Input */}
      <div className="chat-input-container">
        {/* File Upload Panel */}
        {showFileUpload && (
          <div style={{ marginBottom: 'var(--space-3)' }}>
            <FileUpload
              onUpload={handleFilesUploaded}
              onRemove={removeAttachment}
              maxFiles={5}
            />
          </div>
        )}

        {/* Attachments Preview */}
        {attachments.length > 0 && (
          <div className="attachment-preview" style={{ padding: 'var(--space-2) 0' }}>
            {attachments.map(file => (
              <div key={file.id} className="attachment-item">
                {file.preview ? (
                  <img
                    src={file.preview}
                    alt={file.name}
                    style={{ width: 32, height: 32, objectFit: 'cover', borderRadius: 'var(--radius-md)' }}
                  />
                ) : (
                  <span style={{ fontSize: 'var(--text-xs)', maxWidth: 100, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {file.name}
                  </span>
                )}
                <button
                  className="attachment-remove"
                  onClick={() => removeAttachment(file.id)}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Input Wrapper */}
        <div className="chat-input-wrapper">
          <div className="chat-input-actions">
            <button
              className="input-action-button"
              onClick={() => setShowFileUpload(!showFileUpload)}
              title="Attach file"
            >
              <Paperclip size={20} />
            </button>
            <button
              className={cn('input-action-button', isRecording && 'text-red-500')}
              onClick={() => setIsRecording(!isRecording)}
              title={isRecording ? 'Stop recording' : 'Voice input'}
            >
              {isRecording ? <MicOff size={20} /> : <Mic size={20} />}
            </button>
          </div>
          
          <textarea
            ref={textareaRef}
            className="chat-input"
            placeholder="Message Jaeger..."
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={1}
          />
          
          <div className="chat-input-actions">
            {isGenerating ? (
              <button
                className="send-button"
                onClick={onStopGeneration}
                title="Stop generation"
                style={{ background: 'var(--error)' }}
              >
                <Square size={16} />
              </button>
            ) : (
              <button
                className="send-button"
                onClick={handleSend}
                disabled={!input.trim() && attachments.length === 0}
                title="Send message"
              >
                <Send size={18} />
              </button>
            )}
          </div>
        </div>
        
        <p style={{ 
          textAlign: 'center', 
          fontSize: 'var(--text-xs)', 
          color: 'var(--text-muted)', 
          marginTop: 'var(--space-2)' 
        }}>
          Jaeger can make mistakes. Consider verifying important information.
        </p>
      </div>
    </div>
  )
}
