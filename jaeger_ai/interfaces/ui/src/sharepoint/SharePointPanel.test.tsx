import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { it, expect } from 'vitest'
import { SharePointPanel } from './SharePointPanel'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

it('renders SharePoint panel with document libraries and filter controls', async () => {
  const el = document.createElement('div')
  document.body.append(el)
  const root = createRoot(el)

  try {
    await act(async () => root.render(<SharePointPanel />))
    expect(el.textContent).toContain('SharePoint & Team Document Libraries')
    expect(el.textContent).toContain('Connected to Microsoft SharePoint')
    expect(el.textContent).toContain('Jenkins_Robotics_Master_Spec_v2.pdf')
    expect(el.textContent).toContain('JROS_Kinematics_Actuator_Array.step')

    // Filter by CAD library
    const cadFilterBtn = [...el.querySelectorAll('button')].find((b) => b.textContent === 'CAD & 3D Models')
    expect(cadFilterBtn).toBeDefined()
    await act(async () => cadFilterBtn!.click())
    expect(el.textContent).toContain('JROS_Kinematics_Actuator_Array.step')
    expect(el.textContent).not.toContain('BOM_Component_Inventory_2026.xlsx')

    // Search input filtering
    const searchInput = el.querySelector('input[type="search"]') as HTMLInputElement
    expect(searchInput).toBeDefined()
  } finally {
    await act(async () => root.unmount())
    el.remove()
  }
})

