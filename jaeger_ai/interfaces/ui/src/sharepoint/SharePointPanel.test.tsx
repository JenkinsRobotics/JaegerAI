import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { it, expect } from 'vitest'
import { SharePointPanel } from './SharePointPanel'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

// The panel no longer ships mock SharePoint libraries (5ddcd495): with no source it must say
// honestly that the connector is disconnected and that no artifact catalog is available.
it('renders the honest artifacts state when no gateway source is given', async () => {
  const el = document.createElement('div')
  document.body.append(el)
  const root = createRoot(el)
  try {
    await act(async () => root.render(<SharePointPanel />))
    expect(el.textContent).toContain('Artifacts')
    expect(el.textContent).toContain('SharePoint connector is disconnected')
    expect(el.textContent).not.toContain('Jenkins_Robotics_Master_Spec_v2.pdf')
  } finally {
    await act(async () => root.unmount())
    el.remove()
  }
})
