/**
 * Tests for Icons component
 *
 * Verifies all SVG icons render correctly with proper attributes.
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import * as Icons from '../Icons'

describe('Icons', () => {
  // Test all exported icons
  const iconNames = [
    'Send',
    'Stop',
    'Square',
    'Mic',
    'MicOff',
    'Paperclip',
    'Search',
    'Plus',
    'Settings',
    'Menu',
    'X',
    'ChevronLeft',
    'ChevronRight',
    'Copy',
    'Check',
    'RefreshCw',
    'Trash2',
    'Edit2',
    'Share',
    'ThumbsUp',
    'ThumbsDown',
    'Volume2',
    'Sun',
    'Moon',
    'Circle',
    'Loader',
    'Zap',
    'Clock',
    'Star',
    'MessageSquare',
    'MoreHorizontal',
  ]

  iconNames.forEach((name) => {
    it(`renders ${name} icon`, () => {
      const Icon = (Icons as any)[name]
      expect(Icon).toBeDefined()

      const { container } = render(<Icon />)
      const svg = container.querySelector('svg')

      expect(svg).toBeInTheDocument()
      expect(svg).toHaveAttribute('width', '24')
      expect(svg).toHaveAttribute('height', '24')
      expect(svg).toHaveAttribute('viewBox', '0 0 24 24')
      expect(svg).toHaveAttribute('fill', 'none')
      expect(svg).toHaveAttribute('stroke', 'currentColor')
    })
  })

  it('renders icon with custom size', () => {
    const { container } = render(<Icons.Send size={32} />)
    const svg = container.querySelector('svg')

    expect(svg).toHaveAttribute('width', '32')
    expect(svg).toHaveAttribute('height', '32')
  })

  it('renders icon with custom stroke width', () => {
    const { container } = render(<Icons.Send strokeWidth={3} />)
    const svg = container.querySelector('svg')

    expect(svg).toHaveAttribute('stroke-width', '3')
  })

  it('renders icon with custom className', () => {
    const { container } = render(<Icons.Send className="text-blue-500" />)
    const svg = container.querySelector('svg')

    expect(svg).toHaveClass('text-blue-500')
  })

  it('renders icon with aria-hidden', () => {
    const { container } = render(<Icons.Send />)
    const svg = container.querySelector('svg')

    expect(svg).toHaveAttribute('aria-hidden', 'true')
  })

  it('passes through additional SVG props', () => {
    const { container } = render(<Icons.Send data-testid="send-icon" />)
    const svg = container.querySelector('svg')

    expect(svg).toHaveAttribute('data-testid', 'send-icon')
  })

  describe('Spinner', () => {
    it('renders spinner with animation', () => {
      const { container } = render(<Icons.Spinner />)
      const svg = container.querySelector('svg.spinner')

      expect(svg).toBeInTheDocument()
      expect(svg).toHaveStyle({ animation: 'spin 1s linear infinite' })
    })

    it('renders spinner with custom size', () => {
      const { container } = render(<Icons.Spinner size={48} />)
      const svg = container.querySelector('svg')

      expect(svg).toHaveAttribute('width', '48')
      expect(svg).toHaveAttribute('height', '48')
    })
  })

  describe('Icons collection', () => {
    it('exports all icons in Icons object', () => {
      expect(Icons.Icons).toBeDefined()
      expect(Object.keys(Icons.Icons)).toHaveLength(iconNames.length)

      iconNames.forEach((name) => {
        expect((Icons.Icons as any)[name]).toBeDefined()
      })
    })
  })
})
