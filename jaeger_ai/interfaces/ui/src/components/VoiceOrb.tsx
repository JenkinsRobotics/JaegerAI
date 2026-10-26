/**
 * VoiceOrb — Animated voice visualization orb
 *
 * Apple-inspired gradient orb that responds to voice input/output.
 * Features:
 * - Animated gradient (blue → purple → pink)
 * - Audio-reactive visualization
 * - Multiple states: idle, listening, processing, speaking
 * - Smooth spring animations
 *
 * Usage:
 *   <VoiceOrb state="listening" audioLevel={0.7} />
 *   <VoiceOrb state="speaking" audioLevel={0.5} />
 */

import { useEffect, useRef, useState, useCallback } from 'react'

export type VoiceOrbState = 'idle' | 'listening' | 'processing' | 'speaking' | 'muted'

interface VoiceOrbProps {
  state?: VoiceOrbState
  audioLevel?: number // 0.0 - 1.0
  size?: number
  className?: string
  onClick?: () => void
}

// ─────────────────────────────────────────────────────────────
// CSS-based VoiceOrb (No WebGL required, works everywhere)
// ─────────────────────────────────────────────────────────────

export function VoiceOrb({
  state = 'idle',
  audioLevel = 0,
  size = 120,
  className = '',
  onClick,
}: VoiceOrbProps) {
  const [displayLevel, setDisplayLevel] = useState(0)

  // Smooth audio level transitions
  useEffect(() => {
    const target = state === 'idle' || state === 'muted' ? 0 : audioLevel
    const interval = setInterval(() => {
      setDisplayLevel(prev => {
        const diff = target - prev
        return prev + diff * 0.2 // Ease towards target
      })
    }, 16) // ~60fps

    return () => clearInterval(interval)
  }, [audioLevel, state])

  // Calculate scale based on audio level
  const baseScale = 1 + displayLevel * 0.3
  const pulseScale = state === 'listening' || state === 'speaking'
    ? 1 + Math.sin(Date.now() / 200) * 0.05 * displayLevel
    : 1

  const scale = baseScale * pulseScale

  // State-based colors
  const getGradient = () => {
    switch (state) {
      case 'listening':
        return 'linear-gradient(135deg, #007AFF 0%, #5856D6 50%, #AF52DE 100%)'
      case 'processing':
        return 'linear-gradient(135deg, #5856D6 0%, #AF52DE 50%, #FF2D55 100%)'
      case 'speaking':
        return 'linear-gradient(135deg, #34C759 0%, #30D158 50%, #5AC8FA 100%)'
      case 'muted':
        return 'linear-gradient(135deg, #8E8E93 0%, #636366 100%)'
      default: // idle
        return 'linear-gradient(135deg, #007AFF 0%, #5856D6 50%, #AF52DE 100%)'
    }
  }

  return (
    <div
      className={`voice-orb voice-orb-${state} ${className}`}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      aria-label={`Voice ${state}`}
      style={{
        width: size,
        height: size,
        transform: `scale(${scale})`,
        transition: 'transform 0.1s ease-out',
      }}
    >
      {/* Outer glow */}
      <div
        className="voice-orb-glow"
        style={{
          background: getGradient(),
          opacity: 0.3 + displayLevel * 0.4,
        }}
      />

      {/* Main orb */}
      <div
        className="voice-orb-core"
        style={{
          background: getGradient(),
          boxShadow: `0 0 ${20 + displayLevel * 40}px ${getGradient().match(/#[0-9A-Fa-f]{6}/)?.[0] || '#007AFF'}40`,
        }}
      >
        {/* Inner highlight */}
        <div className="voice-orb-highlight" />

        {/* Waveform bars (visible when active) */}
        {(state === 'listening' || state === 'speaking') && (
          <div className="voice-orb-waveform">
            {[...Array(5)].map((_, i) => (
              <div
                key={i}
                className="voice-orb-bar"
                style={{
                  height: `${20 + displayLevel * 60}%`,
                  animationDelay: `${i * 0.1}s`,
                  opacity: 0.6 + displayLevel * 0.4,
                }}
              />
            ))}
          </div>
        )}

        {/* Processing spinner */}
        {state === 'processing' && (
          <div className="voice-orb-spinner">
            <svg viewBox="0 0 24 24" width="40%" height="40%">
              <circle
                cx="12"
                cy="12"
                r="10"
                fill="none"
                stroke="white"
                strokeWidth="2"
                strokeDasharray="60"
                strokeDashoffset={60 - displayLevel * 60}
                strokeLinecap="round"
                style={{
                  transform: 'rotate(-90deg)',
                  transformOrigin: 'center',
                  transition: 'stroke-dashoffset 0.3s ease',
                }}
              />
            </svg>
          </div>
        )}
      </div>

      {/* Click ripple effect */}
      {onClick && (
        <div className="voice-orb-ripple" />
      )}

      <style>{`
        .voice-orb {
          position: relative;
          display: flex;
          align-items: center;
          justify-content: center;
          cursor: ${onClick ? 'pointer' : 'default'};
          user-select: none;
        }

        .voice-orb-glow {
          position: absolute;
          inset: -20%;
          border-radius: 50%;
          filter: blur(20px);
          transition: opacity 0.3s ease;
          animation: voice-orb-pulse 2s ease-in-out infinite;
        }

        .voice-orb-core {
          position: relative;
          width: 100%;
          height: 100%;
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          overflow: hidden;
          transition: box-shadow 0.3s ease;
        }

        .voice-orb-highlight {
          position: absolute;
          top: 15%;
          left: 20%;
          width: 30%;
          height: 20%;
          background: rgba(255, 255, 255, 0.4);
          border-radius: 50%;
          filter: blur(8px);
        }

        .voice-orb-waveform {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 8%;
          width: 60%;
          height: 40%;
        }

        .voice-orb-bar {
          width: 8%;
          background: white;
          border-radius: 9999px;
          animation: voice-orb-wave 1s ease-in-out infinite;
        }

        .voice-orb-spinner {
          position: absolute;
          inset: 0;
          display: flex;
          align-items: center;
          justify-content: center;
          animation: voice-orb-spin 1s linear infinite;
        }

        .voice-orb-ripple {
          position: absolute;
          inset: 0;
          border-radius: 50%;
          pointer-events: none;
        }

        .voice-orb:active .voice-orb-ripple {
          animation: voice-orb-ripple-effect 0.6s ease-out;
        }

        .voice-orb-muted {
          opacity: 0.6;
        }

        .voice-orb-idle {
          opacity: 0.8;
        }

        @keyframes voice-orb-pulse {
          0%, 100% { transform: scale(1); opacity: 0.3; }
          50% { transform: scale(1.1); opacity: 0.5; }
        }

        @keyframes voice-orb-wave {
          0%, 100% { transform: scaleY(0.3); }
          50% { transform: scaleY(1); }
        }

        @keyframes voice-orb-spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }

        @keyframes voice-orb-ripple-effect {
          from {
            box-shadow: 0 0 0 0 rgba(0, 122, 255, 0.4);
          }
          to {
            box-shadow: 0 0 0 20px rgba(0, 122, 255, 0);
          }
        }

        @media (prefers-reduced-motion: reduce) {
          .voice-orb-glow,
          .voice-orb-bar,
          .voice-orb-spinner {
            animation: none;
          }
        }
      `}</style>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// WaveformVisualizer — Real-time audio waveform
// ─────────────────────────────────────────────────────────────

interface WaveformProps {
  audioLevel: number // 0.0 - 1.0
  barCount?: number
  height?: number
  color?: string
  className?: string
}

export function Waveform({
  audioLevel,
  barCount = 48,
  height = 60,
  color = 'var(--system-blue, #007AFF)',
  className = '',
}: WaveformProps) {
  const [bars, setBars] = useState<number[]>(() => Array(barCount).fill(0))

  useEffect(() => {
    // Simulate waveform with audio level + randomness
    const interval = setInterval(() => {
      setBars(prev =>
        prev.map(() => 0.3 + Math.random() * audioLevel * 0.7)
      )
    }, 50)

    return () => clearInterval(interval)
  }, [audioLevel])

  return (
    <div
      className={`waveform ${className}`}
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: '2px',
        height: `${height}px`,
        width: '100%',
      }}
      role="img"
      aria-label="Audio waveform visualization"
    >
      {bars.map((level, i) => (
        <div
          key={i}
          style={{
            width: '3px',
            height: `${Math.max(4, level * height)}px`,
            backgroundColor: color,
            borderRadius: '9999px',
            transition: 'height 0.05s ease-out',
            opacity: 0.6 + level * 0.4,
          }}
        />
      ))}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// VoiceButton — Combines VoiceOrb with click handling
// ─────────────────────────────────────────────────────────────

interface VoiceButtonProps {
  isRecording: boolean
  isProcessing: boolean
  audioLevel: number
  onToggle: () => void
  size?: number
}

export function VoiceButton({
  isRecording,
  isProcessing,
  audioLevel,
  onToggle,
  size = 56,
}: VoiceButtonProps) {
  const state: VoiceOrbState = isProcessing
    ? 'processing'
    : isRecording
    ? 'listening'
    : 'idle'

  return (
    <div style={{ position: 'relative' }}>
      <VoiceOrb
        state={state}
        audioLevel={audioLevel}
        size={size}
        onClick={onToggle}
      />
      {/* Label */}
      <div
        style={{
          position: 'absolute',
          bottom: -24,
          left: '50%',
          transform: 'translateX(-50%)',
          fontSize: '11px',
          color: 'var(--tertiary-label)',
          whiteSpace: 'nowrap',
        }}
      >
        {isProcessing ? 'Thinking...' : isRecording ? 'Listening...' : 'Tap to speak'}
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// useAudioLevel — Hook for real audio level detection
// ─────────────────────────────────────────────────────────────

export function useAudioLevel(isActive: boolean): number {
  const [level, setLevel] = useState(0)
  const audioContextRef = useRef<AudioContext | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const animationRef = useRef<number | null>(null)

  useEffect(() => {
    if (!isActive) {
      // Clean up
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current)
      }
      if (streamRef.current) {
        streamRef.current.getTracks().forEach(track => track.stop())
        streamRef.current = null
      }
      if (audioContextRef.current) {
        audioContextRef.current.close()
        audioContextRef.current = null
      }
      setLevel(0)
      return
    }

    // Set up audio analysis
    const setupAudio = async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
        streamRef.current = stream

        const audioContext = new AudioContext()
        audioContextRef.current = audioContext

        const analyser = audioContext.createAnalyser()
        analyser.fftSize = 256
        analyserRef.current = analyser

        const source = audioContext.createMediaStreamSource(stream)
        source.connect(analyser)

        const dataArray = new Uint8Array(analyser.frequencyBinCount)

        const updateLevel = () => {
          if (!analyserRef.current) return

          analyserRef.current.getByteFrequencyData(dataArray)

          // Calculate average level
          const average = dataArray.reduce((a, b) => a + b, 0) / dataArray.length
          const normalized = Math.min(1, average / 128)

          setLevel(normalized)
          animationRef.current = requestAnimationFrame(updateLevel)
        }

        updateLevel()
      } catch (err) {
        console.error('[VoiceOrb] Failed to access microphone:', err)
        setLevel(0)
      }
    }

    setupAudio()

    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current)
      }
      if (streamRef.current) {
        streamRef.current.getTracks().forEach(track => track.stop())
      }
      if (audioContextRef.current) {
        audioContextRef.current.close()
      }
    }
  }, [isActive])

  return level
}

export default VoiceOrb
