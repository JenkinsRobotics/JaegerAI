"""An app in its own desktop window: the one desktop UI standard (JaegerAvatar dev/docs/vision/20261124_one_desktop_ui.md).

The window is pywebview around the app's own loopback page, as NexusUI does (VisualReactpy, nexusui/desktop.py).
On macOS pywebview has no answer for a page's microphone or camera request, so the page would wait forever; grant_media
adds one, for the app's own page only (proved November 24, 2026, pywebview 6.2.1).
"""
import sys


def own_page(host):
    """Only the app's own loopback page gets the microphone and camera."""
    return host in ('127.0.0.1', 'localhost')


def grant_media():
    """Answer WebKit's microphone/camera request for our own page (macOS). Elsewhere pywebview's engine asks itself."""
    if sys.platform != 'darwin': return
    import objc
    import WebKit
    from webview.platforms import cocoa
    objc.registerMetaDataForSelector(   # the decision handler is a block taking one WKPermissionDecision (an integer)
        b'NSObject', b'webView:requestMediaCapturePermissionForOrigin:initiatedByFrame:type:decisionHandler:',
        {'arguments': {6: {'callable': {'retval': {'type': b'v'}, 'arguments': {0: {'type': b'^v'}, 1: {'type': b'q'}}}}}})

    class Delegate(cocoa.BrowserView.BrowserDelegate):
        @objc.signature(b'v@:@@@q@?')   # webview, origin, frame, WKMediaCaptureType (an integer), decision block
        def webView_requestMediaCapturePermissionForOrigin_initiatedByFrame_type_decisionHandler_(self, webview, origin, frame, kind, decide):
            decide(WebKit.WKPermissionDecisionGrant if own_page(str(origin.host())) else WebKit.WKPermissionDecisionDeny)

    cocoa.BrowserView.BrowserDelegate = Delegate


def open_window(url, title='Jaeger', width=1440, height=900):
    """Show `url` in a desktop window; returns when the window is closed."""
    import webview
    grant_media()
    webview.create_window(title, url, width=width, height=height, min_size=(900, 600), background_color='#111722')
    webview.start()
