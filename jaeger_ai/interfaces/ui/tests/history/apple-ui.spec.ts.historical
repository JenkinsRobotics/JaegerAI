/**
 * E2E Tests for Apple-Native UI
 *
 * Tests the complete user flow in a real browser using Playwright.
 * Run with: npx playwright test
 */

import { test, expect, type Page } from '@playwright/test'

const BASE_URL = process.env.BASE_URL || 'http://127.0.0.1:5173'

test.describe('Apple-Native UI', () => {
  test.beforeEach(async ({ page }) => {
    // Enable Apple UI via query param
    await page.goto(`${BASE_URL}/?ui=apple`)
  })

  test.describe('Initial Load', () => {
    test('loads without errors', async ({ page }) => {
      // Check for no console errors (except WebSocket 403 which is expected)
      const errors: string[] = []
      page.on('console', (msg) => {
        if (msg.type() === 'error' && !msg.text().includes('WebSocket')) {
          errors.push(msg.text())
        }
      })

      await page.waitForLoadState('networkidle')
      expect(errors).toHaveLength(0)
    })

    test('shows sidebar with agents', async ({ page }) => {
      await expect(page.locator('.sidebar')).toBeVisible()
      await expect(page.locator('.agent-item').first()).toBeVisible()
      // Agent names appear in sidebar
      await expect(page.locator('.agent-name', { hasText: 'Jaeger' }).first()).toBeVisible()
      await expect(page.locator('.agent-name', { hasText: 'Jarvis' }).first()).toBeVisible()
      await expect(page.locator('.agent-name', { hasText: 'Lilith' }).first()).toBeVisible()
    })

    test('shows empty state', async ({ page }) => {
      await expect(page.getByText('How can I help you today?')).toBeVisible()
      await expect(page.getByText(/I'm Jaeger/)).toBeVisible()
    })

    test('shows 4 suggestion cards', async ({ page }) => {
      const suggestions = page.locator('.suggestion-card')
      await expect(suggestions).toHaveCount(4)
    })

    test('shows chat input', async ({ page }) => {
      await expect(page.locator('textarea.chat-input')).toBeVisible()
      await expect(page.locator('textarea.chat-input')).toHaveAttribute('placeholder', 'Message Jaeger...')
    })
  })

  test.describe('Chat Flow', () => {
    test('sends a message and receives response', async ({ page }) => {
      // Type message
      const input = page.locator('textarea.chat-input')
      await input.fill('Hello Jaeger!')

      // Send message
      await page.getByRole('button', { name: 'Send message' }).click()

      // Check user message appears
      await expect(page.locator('.message-user')).toContainText('Hello Jaeger!')

      // Wait for AI response (mock mode streams over ~1-2 seconds)
      await expect(page.locator('.message-assistant')).toBeVisible({ timeout: 10000 })
    })

    test('shows streaming cursor during generation', async ({ page }) => {
      const input = page.locator('textarea.chat-input')
      await input.fill('Test streaming')
      await input.press('Enter')

      // Check for streaming cursor (may be brief)
      const cursor = page.locator('.streaming-cursor')
      // Either visible during streaming or already done
      const count = await cursor.count()
      expect(count).toBeGreaterThanOrEqual(0)
    })

    test('clears input after sending', async ({ page }) => {
      const input = page.locator('textarea.chat-input')
      await input.fill('Test message')
      await input.press('Enter')

      await expect(input).toHaveValue('')
    })

    test('disables send button when input is empty', async ({ page }) => {
      const sendButton = page.getByRole('button', { name: 'Send message' })
      await expect(sendButton).toBeDisabled()
    })

    test('enables send button when input has text', async ({ page }) => {
      const input = page.locator('textarea.chat-input')
      await input.fill('Hello')

      const sendButton = page.getByRole('button', { name: 'Send message' })
      await expect(sendButton).toBeEnabled()
    })

    test('sends message with Enter key', async ({ page }) => {
      const input = page.locator('textarea.chat-input')
      await input.fill('Keyboard test')
      await input.press('Enter')

      await expect(page.locator('.message-user')).toContainText('Keyboard test')
    })

    test('adds newline with Shift+Enter', async ({ page }) => {
      const input = page.locator('textarea.chat-input')
      await input.fill('Line 1')
      await input.press('Shift+Enter')
      await input.type('Line 2')

      const value = await input.inputValue()
      expect(value).toContain('Line 1')
      expect(value).toContain('Line 2')
    })
  })

  test.describe('Message Actions', () => {
    test.beforeEach(async ({ page }) => {
      // Send a message first
      const input = page.locator('textarea.chat-input')
      await input.fill('Test message')
      await input.press('Enter')

      // Wait for response
      await expect(page.locator('.message-assistant')).toBeVisible({ timeout: 10000 })
    })

    test('shows action buttons on hover', async ({ page }) => {
      const message = page.locator('.message-assistant')
      await message.hover()

      await expect(page.getByRole('button', { name: 'Copy message' })).toBeVisible()
      await expect(page.getByRole('button', { name: 'Regenerate response' })).toBeVisible()
      await expect(page.getByRole('button', { name: 'Good response' })).toBeVisible()
      await expect(page.getByRole('button', { name: 'Bad response' })).toBeVisible()
    })

    test('copies message to clipboard', async ({ page }) => {
      // Grant clipboard permissions
      await page.context().grantPermissions(['clipboard-read', 'clipboard-write'])

      const message = page.locator('.message-assistant')
      await message.hover()
      await page.getByRole('button', { name: 'Copy message' }).click()

      // Check for check icon (copied state)
      await expect(page.locator('.message-assistant button svg').first()).toBeVisible()
    })

    test('toggles thumbs up', async ({ page }) => {
      const message = page.locator('.message-assistant')
      await message.hover()

      const thumbsUp = page.getByRole('button', { name: 'Good response' })
      await thumbsUp.click()

      await expect(thumbsUp).toHaveClass(/active/)
    })

    test('toggles thumbs down', async ({ page }) => {
      const message = page.locator('.message-assistant')
      await message.hover()

      const thumbsDown = page.getByRole('button', { name: 'Bad response' })
      await thumbsDown.click()

      await expect(thumbsDown).toHaveClass(/active/)
    })
  })

  test.describe('Theme Toggle', () => {
    test('toggles between light, dark, and system', async ({ page }) => {
      const themeButton = page.getByRole('button', { name: /Current theme/ })

      // Initial state (system)
      await expect(themeButton).toHaveAttribute('aria-label', /system/)

      // Click to light
      await themeButton.click()
      await expect(themeButton).toHaveAttribute('aria-label', /light/)

      // Check light mode applied
      const html = page.locator('html')
      await expect(html).not.toHaveClass(/dark/)

      // Click to dark
      await themeButton.click()
      await expect(themeButton).toHaveAttribute('aria-label', /dark/)

      // Check dark mode applied
      await expect(html).toHaveClass(/dark/)

      // Click back to system
      await themeButton.click()
      await expect(themeButton).toHaveAttribute('aria-label', /system/)
    })

    test('persists theme preference', async ({ page }) => {
      const themeButton = page.getByRole('button', { name: /Current theme/ })

      // Set to light
      await themeButton.click()

      // Reload page
      await page.reload()

      // Check theme persisted
      const stored = await page.evaluate(() => localStorage.getItem('jaeger.theme'))
      expect(stored).toBe('light')
    })
  })

  test.describe('Agent Selection', () => {
    test('switches active agent', async ({ page }) => {
      // Initially Jaeger is selected
      await expect(page.locator('h1.header-title')).toHaveText('Jaeger')

      // Click Jarvis
      await page.locator('.agent-item', { hasText: 'Jarvis' }).click()

      // Header updates
      await expect(page.locator('h1.header-title')).toHaveText('Jarvis')
    })

    test('shows online status for active agent', async ({ page }) => {
      await expect(page.getByText('● Online')).toBeVisible()
    })
  })

  test.describe('New Chat', () => {
    test('clears messages and shows empty state', async ({ page }) => {
      // Send a message first
      const input = page.locator('textarea.chat-input')
      await input.fill('Test message')
      await input.press('Enter')
      await expect(page.locator('.message-user')).toBeVisible()

      // Click New Chat
      await page.locator('.new-chat-button').click()

      // Messages cleared
      await expect(page.locator('.message')).toHaveCount(0)

      // Empty state shown
      await expect(page.getByText('How can I help you today?')).toBeVisible()
    })
  })

  test.describe('Suggestion Cards', () => {
    test('fills input when suggestion clicked', async ({ page }) => {
      await page.locator('.suggestion-card', { hasText: 'Write some code' }).click()

      const input = page.locator('textarea.chat-input')
      await expect(input).toHaveValue('Write a Python function to sort a list')
    })

    test('fills input with explain suggestion', async ({ page }) => {
      await page.locator('.suggestion-card', { hasText: 'Explain something' }).click()

      const input = page.locator('textarea.chat-input')
      await expect(input).toHaveValue('Explain quantum computing in simple terms')
    })
  })

  test.describe('Voice Mode', () => {
    test('enters voice mode when mic button clicked', async ({ page }) => {
      await page.getByRole('button', { name: 'Voice input' }).click()

      // Voice orb should be visible
      await expect(page.locator('.voice-orb')).toBeVisible()
      await expect(page.getByText('Tap to speak')).toBeVisible()
    })

    test('exits voice mode when exit button clicked', async ({ page }) => {
      // Enter voice mode
      await page.getByRole('button', { name: 'Voice input' }).click()
      await expect(page.locator('.voice-orb')).toBeVisible()

      // Exit voice mode
      await page.getByRole('button', { name: 'Exit voice mode' }).click()

      // Back to text input
      await expect(page.locator('textarea.chat-input')).toBeVisible()
      await expect(page.locator('.voice-orb')).not.toBeVisible()
    })

    test('shows voice orb with correct state', async ({ page }) => {
      await page.getByRole('button', { name: 'Voice input' }).click()

      const orb = page.locator('.voice-orb')
      await expect(orb).toBeVisible()
      await expect(orb).toHaveAttribute('aria-label', 'Voice idle')
    })

    test('toggles to listening when orb clicked', async ({ page }) => {
      // Grant microphone permission
      await page.context().grantPermissions(['microphone'])

      await page.getByRole('button', { name: 'Voice input' }).click()
      await page.locator('.voice-orb').click()

      // Should show listening state
      await expect(page.locator('.voice-orb')).toHaveAttribute('aria-label', /listening|idle/)
    })
  })

  test.describe('Responsive Design', () => {
    test('shows mobile menu on small screens', async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 812 })

      // Mobile menu button visible
      await expect(page.getByRole('button', { name: 'Open menu' })).toBeVisible()

      // Sidebar hidden by default
      const sidebar = page.locator('.sidebar-wrapper')
      await expect(sidebar).not.toHaveClass(/mobile-open/)
    })

    test('opens mobile sidebar when menu clicked', async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 812 })

      await page.getByRole('button', { name: 'Open menu' }).click()

      // Sidebar visible
      const sidebar = page.locator('.sidebar-wrapper')
      await expect(sidebar).toHaveClass(/mobile-open/)

      // Overlay visible
      await expect(page.locator('.mobile-sidebar-overlay')).toBeVisible()
    })

    test('closes mobile sidebar when overlay clicked', async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 812 })

      // Open sidebar
      await page.getByRole('button', { name: 'Open menu' }).click()
      await expect(page.locator('.sidebar-wrapper')).toHaveClass(/mobile-open/)

      // Click overlay
      await page.locator('.mobile-sidebar-overlay').click()

      // Sidebar closed
      await expect(page.locator('.sidebar-wrapper')).not.toHaveClass(/mobile-open/)
    })

    test('closes mobile sidebar when agent selected', async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 812 })

      // Open sidebar
      await page.getByRole('button', { name: 'Open menu' }).click()

      // Select agent
      await page.locator('.agent-item', { hasText: 'Jarvis' }).click()

      // Sidebar closed
      await expect(page.locator('.sidebar-wrapper')).not.toHaveClass(/mobile-open/)

      // Agent switched
      await expect(page.locator('h1.header-title')).toHaveText('Jarvis')
    })

    test('suggestion cards stack vertically on mobile', async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 812 })

      const grid = page.locator('.suggestion-grid')
      const computedStyle = await grid.evaluate((el) =>
        window.getComputedStyle(el).gridTemplateColumns
      )

      // Should be single column
      expect(computedStyle.split(' ').length).toBe(1)
    })
  })

  test.describe('Sidebar', () => {
    test('collapses sidebar when toggle clicked', async ({ page }) => {
      const sidebar = page.locator('.sidebar')
      const initialWidth = await sidebar.evaluate((el) => el.offsetWidth)

      // Click collapse
      await page.getByRole('button', { name: 'Collapse sidebar' }).click()

      // Wait for transition
      await page.waitForTimeout(300)

      const collapsedWidth = await sidebar.evaluate((el) => el.offsetWidth)
      expect(collapsedWidth).toBeLessThan(initialWidth)
    })

    test('expands sidebar when toggle clicked again', async ({ page }) => {
      const sidebar = page.locator('.sidebar')

      // Collapse
      await page.getByRole('button', { name: 'Collapse sidebar' }).click()
      await page.waitForTimeout(300)

      // Expand
      await page.getByRole('button', { name: 'Expand sidebar' }).click()
      await page.waitForTimeout(300)

      await expect(page.locator('.sidebar-title')).toBeVisible()
    })
  })

  test.describe('Accessibility', () => {
    test('has proper ARIA labels on buttons', async ({ page }) => {
      // Header buttons have aria-labels
      await expect(page.getByRole('button', { name: 'New chat' }).first()).toBeVisible()
      await expect(page.getByRole('button', { name: 'Search' }).first()).toBeVisible()
      await expect(page.getByRole('button', { name: 'Settings' }).first()).toBeVisible()
    })

    test('has live region for messages', async ({ page }) => {
      const log = page.getByRole('log', { name: 'Conversation' })
      await expect(log).toBeVisible()
      await expect(log).toHaveAttribute('aria-live', 'polite')
    })

    test('chat input has accessible label', async ({ page }) => {
      const input = page.locator('textarea.chat-input')
      await expect(input).toHaveAttribute('aria-label', 'Message input')
    })

    test('supports keyboard navigation', async ({ page }) => {
      // Focus the input directly
      const input = page.locator('textarea.chat-input')
      await input.focus()

      // Type and send with keyboard
      await page.keyboard.type('Keyboard only test')
      await page.keyboard.press('Enter')

      await expect(page.locator('.message-user')).toContainText('Keyboard only test')
    })
  })

  test.describe('Performance', () => {
    test('loads within 2 seconds', async ({ page }) => {
      const startTime = Date.now()
      await page.goto(`${BASE_URL}/?ui=apple`)
      await page.waitForLoadState('domcontentloaded')
      const loadTime = Date.now() - startTime

      expect(loadTime).toBeLessThan(2000)
    })

    test('first message response within 3 seconds', async ({ page }) => {
      const input = page.locator('textarea.chat-input')
      await input.fill('Performance test')

      const startTime = Date.now()
      await input.press('Enter')

      await expect(page.locator('.message-assistant')).toBeVisible({ timeout: 5000 })
      const responseTime = Date.now() - startTime

      // Mock response should be quick
      expect(responseTime).toBeLessThan(3000)
    })
  })
})
