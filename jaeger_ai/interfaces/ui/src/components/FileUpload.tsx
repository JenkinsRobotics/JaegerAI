/**
 * File Upload Component
 *
 * Drag-and-drop file upload with preview.
 * Supports: images, documents, code files, archives.
 */

import { useState, useCallback, useRef } from 'react'
import { Upload, X, File, Image, FileText, FileCode, Archive, AlertCircle } from 'lucide-react'
import { cn } from '../lib/utils'

export interface UploadedFile {
  id: string
  name: string
  size: number
  type: string
  content?: string // base64 or text
  preview?: string // URL for images
  status: 'pending' | 'uploading' | 'completed' | 'error'
  progress?: number
  error?: string
}

interface FileUploadProps {
  onUpload?: (files: UploadedFile[]) => void
  onRemove?: (fileId: string) => void
  accept?: string
  maxSize?: number // bytes
  maxFiles?: number
  multiple?: boolean
  className?: string
  disabled?: boolean
}

const DEFAULT_MAX_SIZE = 10 * 1024 * 1024 // 10MB

function getFileIcon(type: string) {
  if (type.startsWith('image/')) return Image
  if (type.startsWith('text/') || type.includes('json') || type.includes('xml')) return FileText
  if (type.includes('javascript') || type.includes('typescript') || type.includes('python')) return FileCode
  if (type.includes('zip') || type.includes('tar') || type.includes('gzip')) return Archive
  return File
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function FileUpload({
  onUpload,
  onRemove,
  accept,
  maxSize = DEFAULT_MAX_SIZE,
  maxFiles = 10,
  multiple = true,
  className,
  disabled = false,
}: FileUploadProps) {
  const [files, setFiles] = useState<UploadedFile[]>([])
  const [isDragging, setIsDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const processFile = useCallback(async (file: File): Promise<UploadedFile> => {
    const id = `file-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
    const uploadedFile: UploadedFile = {
      id,
      name: file.name,
      size: file.size,
      type: file.type,
      status: 'uploading',
      progress: 0,
    }

    // Check size
    if (file.size > maxSize) {
      uploadedFile.status = 'error'
      uploadedFile.error = `File too large (max ${formatSize(maxSize)})`
      return uploadedFile
    }

    // Read file content
    try {
      if (file.type.startsWith('image/')) {
        // Create preview URL for images
        uploadedFile.preview = URL.createObjectURL(file)
      }

      // Read as base64 for upload
      const reader = new FileReader()
      uploadedFile.content = await new Promise((resolve, reject) => {
        reader.onload = () => {
          const result = reader.result as string
          // Remove data URL prefix
          const base64 = result.split(',')[1] || result
          resolve(base64)
        }
        reader.onerror = reject
        reader.readAsDataURL(file)
      })

      uploadedFile.status = 'completed'
      uploadedFile.progress = 100
    } catch (error) {
      uploadedFile.status = 'error'
      uploadedFile.error = error instanceof Error ? error.message : 'Failed to read file'
    }

    return uploadedFile
  }, [maxSize])

  const handleFiles = useCallback(async (fileList: FileList | null) => {
    if (!fileList || disabled) return

    const newFiles: UploadedFile[] = []
    const remaining = maxFiles - files.length

    for (let i = 0; i < Math.min(fileList.length, remaining); i++) {
      const file = fileList[i]
      const uploadedFile = await processFile(file)
      newFiles.push(uploadedFile)
      setFiles(prev => [...prev, uploadedFile])
    }

    if (newFiles.length > 0) {
      onUpload?.(newFiles)
    }
  }, [files.length, maxFiles, disabled, processFile, onUpload])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    handleFiles(e.dataTransfer.files)
  }, [handleFiles])

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
  }, [])

  const handleRemove = useCallback((fileId: string) => {
    setFiles(prev => {
      const file = prev.find(f => f.id === fileId)
      if (file?.preview) URL.revokeObjectURL(file.preview)
      return prev.filter(f => f.id !== fileId)
    })
    onRemove?.(fileId)
  }, [onRemove])

  const handleClick = useCallback(() => {
    inputRef.current?.click()
  }, [])

  return (
    <div className={cn('space-y-4', className)}>
      {/* Drop zone */}
      <div
        onClick={handleClick}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        className={cn(
          'relative flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-8 transition-colors cursor-pointer',
          isDragging
            ? 'border-primary bg-primary/5'
            : 'border-border hover:border-primary/50 hover:bg-accent/50',
          disabled && 'opacity-50 cursor-not-allowed'
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          multiple={multiple}
          onChange={(e) => handleFiles(e.target.files)}
          className="hidden"
          disabled={disabled}
        />

        <Upload className={cn(
          'h-10 w-10 mb-4',
          isDragging ? 'text-primary' : 'text-muted-foreground'
        )} />

        <p className="text-sm font-medium">
          {isDragging ? 'Drop files here' : 'Click to upload or drag and drop'}
        </p>
        <p className="text-xs text-muted-foreground mt-1">
          {accept ? `Accepted: ${accept}` : 'Any file type'} • Max {formatSize(maxSize)}
        </p>
      </div>

      {/* File list */}
      {files.length > 0 && (
        <div className="space-y-2">
          {files.map((file) => {
            const Icon = getFileIcon(file.type)
            return (
              <div
                key={file.id}
                className="flex items-center gap-3 rounded-lg border border-border p-3"
              >
                {/* Preview/Icon */}
                {file.preview ? (
                  <img
                    src={file.preview}
                    alt={file.name}
                    className="h-10 w-10 rounded object-cover"
                  />
                ) : (
                  <div className="flex h-10 w-10 items-center justify-center rounded bg-muted">
                    <Icon className="h-5 w-5 text-muted-foreground" />
                  </div>
                )}

                {/* Info */}
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{file.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {formatSize(file.size)} • {file.type || 'Unknown type'}
                  </p>

                  {/* Progress bar */}
                  {file.status === 'uploading' && (
                    <div className="mt-1 h-1 w-full rounded-full bg-muted">
                      <div
                        className="h-1 rounded-full bg-primary transition-all"
                        style={{ width: `${file.progress || 0}%` }}
                      />
                    </div>
                  )}

                  {/* Error */}
                  {file.status === 'error' && (
                    <p className="text-xs text-destructive flex items-center gap-1 mt-1">
                      <AlertCircle className="h-3 w-3" />
                      {file.error}
                    </p>
                  )}
                </div>

                {/* Status/Remove */}
                <div className="flex items-center gap-2">
                  {file.status === 'completed' && (
                    <span className="text-xs text-green-500">✓</span>
                  )}
                  <button
                    onClick={() => handleRemove(file.id)}
                    className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// Hook for file upload state
// ─────────────────────────────────────────────────────────────

export function useFileUpload(options: Omit<FileUploadProps, 'onUpload' | 'onRemove'> = {}) {
  const [files, setFiles] = useState<UploadedFile[]>([])

  const addFiles = useCallback((newFiles: UploadedFile[]) => {
    setFiles(prev => [...prev, ...newFiles])
  }, [])

  const removeFile = useCallback((fileId: string) => {
    setFiles(prev => prev.filter(f => f.id !== fileId))
  }, [])

  const clearFiles = useCallback(() => {
    setFiles([])
  }, [])

  return {
    files,
    addFiles,
    removeFile,
    clearFiles,
    hasFiles: files.length > 0,
  }
}
