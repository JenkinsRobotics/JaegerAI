/**
 * Tests for VoiceOrb component
 *
 * Verifies orb rendering, state transitions, and audio reactivity.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { VoiceOrb, VoiceButton, Waveform, useAudioLevel } from '../VoiceOrb'
import { renderHook } from '@testing-library/react'

describe('VoiceOrb', () => {
  it('renders in idle state by default', () => {
    const { container } = render(<VoiceOrb />)
    const orb = container.querySelector('.voice-orb')

    expect(orb).toBeInTheDocument()
    expect(orb).toHaveClass('voice-orb-idle')
  })

  it('renders with correct size', () => {
    const { container } = render(<VoiceOrb size={120} />)
    const orb = container.querySelector('.voice-orb')

    expect(orb).toHaveStyle({ width: '120px', height: '120px' })
  })

  it('applies state-specific class', () => {
    const states = ['idle', 'listening', 'processing', 'speaking', 'muted'] as const

    states.forEach((state) => {
      const { container, unmount } = render(<VoiceOrb state={state} />)
      const orb = container.querySelector('.voice-orb')

      expect(orb).toHaveClass(`voice-orb-${state}`)
      unmount()
    })
  })

  it('shows waveform bars when listening', () => {
    const { container } = render(<VoiceOrb state="listening" audioLevel={0.5} />)
    const bars = container.querySelectorAll('.voice-orb-bar')

    expect(bars).toHaveLength(5)
  })

  it('shows waveform bars when speaking', () => {
    const { container } = render(<VoiceOrb state="speaking" audioLevel={0.5} />)
    const bars = container.querySelectorAll('.voice-orb-bar')

    expect(bars).toHaveLength(5)
  })

  it('shows spinner when processing', () => {
    const { container } = render(<VoiceOrb state="processing" />)
    const spinner = container.querySelector('.voice-orb-spinner')

    expect(spinner).toBeInTheDocument()
  })

  it('hides waveform when idle', () => {
    const { container } = render(<VoiceOrb state="idle" />)
    const waveform = container.querySelector('.voice-orb-waveform')

    expect(waveform).not.toBeInTheDocument()
  })

  it('renders glow effect', () => {
    const { container } = render(<VoiceOrb state="listening" />)
    const glow = container.querySelector('.voice-orb-glow')

    expect(glow).toBeInTheDocument()
  })

  it('renders highlight effect', () => {
    const { container } = render(<VoiceOrb />)
    const highlight = container.querySelector('.voice-orb-highlight')

    expect(highlight).toBeInTheDocument()
  })

  it('handles click events', () => {
    const onClick = vi.fn()
    const { container } = render(<VoiceOrb onClick={onClick} />)
    const orb = container.querySelector('.voice-orb')

    fireEvent.click(orb!)
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('is clickable when onClick provided', () => {
    const { container } = render(<VoiceOrb onClick={() => {}} />)
    const orb = container.querySelector('.voice-orb')

    expect(orb).toHaveAttribute('role', 'button')
    expect(orb).toHaveAttribute('tabIndex', '0')
  })

  it('has correct aria-label', () => {
    const { container } = render(<VoiceOrb state="listening" />)
    const orb = container.querySelector('.voice-orb')

    expect(orb).toHaveAttribute('aria-label', 'Voice listening')
  })

  it('applies custom className', () => {
    const { container } = render(<VoiceOrb className="custom-class" />)
    const orb = container.querySelector('.voice-orb')

    expect(orb).toHaveClass('custom-class')
  })
})

describe('VoiceButton', () => {
  it('renders with idle state when not recording', () => {
    const { container } = render(
      <VoiceButton
        isRecording={false}
        isProcessing={false}
        audioLevel={0}
        onToggle={() => {}}
      />
    )
    const orb = container.querySelector('.voice-orb')

    expect(orb).toHaveClass('voice-orb-idle')
  })

  it('renders with listening state when recording', () => {
    const { container } = render(
      <VoiceButton
        isRecording={true}
        isProcessing={false}
        audioLevel={0.5}
        onToggle={() => {}}
      />
    )
    const orb = container.querySelector('.voice-orb')

    expect(orb).toHaveClass('voice-orb-listening')
  })

  it('renders with processing state when processing', () => {
    const { container } = render(
      <VoiceButton
        isRecording={false}
        isProcessing={true}
        audioLevel={0}
        onToggle={() => {}}
      />
    )
    const orb = container.querySelector('.voice-orb')

    expect(orb).toHaveClass('voice-orb-processing')
  })

  it('shows correct label for each state', () => {
    const { rerender, container } = render(
      <VoiceButton
        isRecording={false}
        isProcessing={false}
        audioLevel={0}
        onToggle={() => {}}
      />
    )

    expect(container.textContent).toContain('Tap to speak')

    rerender(
      <VoiceButton
        isRecording={true}
        isProcessing={false}
        audioLevel={0.5}
        onToggle={() => {}}
      />
    )
    expect(container.textContent).toContain('Listening...')

    rerender(
      <VoiceButton
        isRecording={false}
        isProcessing={true}
        audioLevel={0}
        onToggle={() => {}}
      />
    )
    expect(container.textContent).toContain('Thinking...')
  })

  it('calls onToggle when clicked', () => {
    const onToggle = vi.fn()
    const { container } = render(
      <VoiceButton
        isRecording={false}
        isProcessing={false}
        audioLevel={0}
        onToggle={onToggle}
      />
    )
    const orb = container.querySelector('.voice-orb')

    fireEvent.click(orb!)
    expect(onToggle).toHaveBeenCalledTimes(1)
  })
})

describe('Waveform', () => {
  it('renders correct number of bars', () => {
    const { container } = render(<Waveform audioLevel={0.5} barCount={24} />)
    // Select bars within the waveform container specifically
    const waveform = container.querySelector('.waveform')
    const bars = waveform?.querySelectorAll(':scope > div') || []

    expect(bars).toHaveLength(24)
  })

  it('renders with custom height', () => {
    const { container } = render(<Waveform audioLevel={0.5} height={80} />)
    const waveform = container.querySelector('.waveform')

    expect(waveform).toHaveStyle({ height: '80px' })
  })

  it('applies custom color', () => {
    const { container } = render(<Waveform audioLevel={0.5} color="#FF0000" />)
    const bars = container.querySelectorAll('.waveform > div')

    bars.forEach((bar) => {
      expect(bar).toHaveStyle({ backgroundColor: '#FF0000' })
    })
  })

  it('updates bars based on audio level', async () => {
    const { container, rerender } = render(<Waveform audioLevel={0} />)
    const barsBefore = container.querySelectorAll('.waveform > div')

    rerender(<Waveform audioLevel={1} />)

    await waitFor(() => {
      const barsAfter = container.querySelectorAll('.waveform > div')
      // Bars should have different heights with higher audio level
      const heights = Array.from(barsAfter).map((bar) =>
        parseInt((bar as HTMLElement).style.height)
      )
      expect(Math.max(...heights)).toBeGreaterThan(4)
    })
  })

  it('has accessibility label', () => {
    const { container } = render(<Waveform audioLevel={0.5} />)
    const waveform = container.querySelector('.waveform')

    expect(waveform).toHaveAttribute('role', 'img')
    expect(waveform).toHaveAttribute('aria-label', 'Audio waveform visualization')
  })
})

describe('useAudioLevel', () => {
  it('returns 0 when not active', () => {
    const { result } = renderHook(() => useAudioLevel(false))
    expect(result.current).toBe(0)
  })

  it('starts audio capture when active', async () => {
    const { result } = renderHook(() => useAudioLevel(true))

    // Should eventually return a value (even if 0 without real audio)
    await waitFor(() => {
      expect(typeof result.current).toBe('number')
    })
  })

  it('cleans up when deactivated', async () => {
    const { result, rerender } = renderHook(
      ({ active }) => useAudioLevel(active),
      { initialProps: { active: true } }
    )

    rerender({ active: false })

    await waitFor(() => {
      expect(result.current).toBe(0)
    })
  })
})
