import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { LiveVideo } from './DroidView'

class Peer {
  static instances: Peer[] = []
  localDescription = { type: 'offer' as RTCSdpType, sdp: 'offer-sdp' }
  connectionState: RTCPeerConnectionState = 'new'
  ontrack: RTCPeerConnection['ontrack'] = null
  onconnectionstatechange: RTCPeerConnection['onconnectionstatechange'] = null
  close = vi.fn()
  addTransceiver = vi.fn()
  createOffer = vi.fn(async () => this.localDescription)
  setLocalDescription = vi.fn(async () => undefined)
  setRemoteDescription = vi.fn(async () => undefined)
  constructor() { Peer.instances.push(this) }
}

describe('Droid live camera', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    Peer.instances = []
  })

  it('negotiates one receive-only WebRTC video track instead of polling images', async () => {
    vi.stubGlobal('RTCPeerConnection', Peer)
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify({ type: 'answer', sdp: 'answer-sdp' }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    )))

    const { unmount } = render(<LiveVideo live empty="Camera off" />)

    expect(screen.getByLabelText('What the droid sees, live').tagName).toBe('VIDEO')
    await waitFor(() => expect(Peer.instances[0]?.setRemoteDescription).toHaveBeenCalledWith(
      { type: 'answer', sdp: 'answer-sdp' },
    ))
    expect(Peer.instances[0]?.addTransceiver).toHaveBeenCalledWith('video', { direction: 'recvonly' })
    expect(fetch).toHaveBeenCalledTimes(1)
    unmount()
    expect(Peer.instances[0]?.close).toHaveBeenCalled()
  })
})
