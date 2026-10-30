/**
 * Toast — Simple toast notification system
 *
 * Replaces console.log statements with user-visible notifications.
 * Auto-dismisses after a timeout.
 */

import { useState, useEffect, useCallback } from 'react'
import { X, CheckCircle, AlertCircle, Info } from './Icons'

type ToastType = 'info' | 'success' | 'warning' | 'error'

interface Toast {
  id: string
  type: ToastType
  message: string
  duration?: number
}

// Simple toast store
let toastListeners: ((toasts: Toast[]) => void)[] = []
let toasts: Toast[] = []

export function addToast(message: string, type: ToastType = 'info', duration = 3000) {
  const id = `toast-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
  const toast: Toast = { id, type, message, duration }
  toasts = [...toasts, toast]
  toastListeners.forEach(listener => listener(toasts))
  
  if (duration > 0) {
    setTimeout(() => removeToast(id), duration)
  }
  
  return id
}

export function removeToast(id: string) {
  toasts = toasts.filter(t => t.id !== id)
  toastListeners.forEach(listener => listener(toasts))
}

// Convenience functions
export const toast = {
  info: (msg: string, duration?: number) => addToast(msg, 'info', duration),
  success: (msg: string, duration?: number) => addToast(msg, 'success', duration),
  warning: (msg: string, duration?: number) => addToast(msg, 'warning', duration),
  error: (msg: string, duration?: number) => addToast(msg, 'error', duration),
  comingSoon: (feature: string) => addToast(`${feature} — coming soon!`, 'info', 2500),
}

// Toast Container Component
export function ToastContainer() {
  const [currentToasts, setCurrentToasts] = useState<Toast[]>([])

  useEffect(() => {
    const listener = (newToasts: Toast[]) => setCurrentToasts([...newToasts])
    toastListeners.push(listener)
    return () => {
      toastListeners = toastListeners.filter(l => l !== listener)
    }
  }, [])

  if (currentToasts.length === 0) return null

  return (
    <div className="toast-container" role="region" aria-label="Notifications">
      {currentToasts.map(toast => (
        <ToastItem key={toast.id} toast={toast} />
      ))}
    </div>
  )
}

function ToastItem({ toast }: { toast: Toast }) {
  const [isExiting, setIsExiting] = useState(false)

  const handleClose = useCallback(() => {
    setIsExiting(true)
    setTimeout(() => removeToast(toast.id), 200)
  }, [toast.id])

  useEffect(() => {
    if (toast.duration && toast.duration > 0) {
      const timer = setTimeout(() => {
        setIsExiting(true)
        setTimeout(() => removeToast(toast.id), 200)
      }, toast.duration)
      return () => clearTimeout(timer)
    }
  }, [toast.id, toast.duration])

  const icons = {
    info: <Info size={18} />,
    success: <CheckCircle size={18} />,
    warning: <AlertCircle size={18} />,
    error: <AlertCircle size={18} />,
  }

  return (
    <div 
      className={`toast toast--${toast.type} ${isExiting ? 'toast--exiting' : ''}`}
      role="alert"
      aria-live="polite"
    >
      <div className="toast__icon">{icons[toast.type]}</div>
      <div className="toast__message">{toast.message}</div>
      <button 
        className="toast__close"
        onClick={handleClose}
        aria-label="Dismiss notification"
      >
        <X size={14} />
      </button>
    </div>
  )
}

export default ToastContainer
