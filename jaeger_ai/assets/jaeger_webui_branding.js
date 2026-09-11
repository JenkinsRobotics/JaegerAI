/* JaegerAI branding for a genuine Hermes WebUI instance.
 *
 * Loaded through Hermes WebUI's supported extension mechanism. This keeps the
 * upstream WebUI source unmodified while giving Safari Jaeger's Mac app icon.
 */
(() => {
  "use strict";

  const iconVersion = "jaeger-app-icon-v1";
  const extensionAsset = (name) => `/extensions/${name}?v=${iconVersion}`;

  const installJaegerIcons = () => {
    if (!document.head) return;

    document.head
      .querySelectorAll(
        'link[rel="icon"], link[rel="shortcut icon"], link[rel="apple-touch-icon"]'
      )
      .forEach((node) => node.remove());

    const icons = [
      { rel: "icon", sizes: "16x16", href: extensionAsset("jaeger_app_icon_16.png") },
      { rel: "icon", sizes: "32x32", href: extensionAsset("jaeger_app_icon_32.png") },
      { rel: "shortcut icon", sizes: "256x256", href: extensionAsset("jaeger_app_icon_256.png") },
      { rel: "apple-touch-icon", sizes: "256x256", href: extensionAsset("jaeger_app_icon_256.png") },
    ];

    for (const icon of icons) {
      const link = document.createElement("link");
      link.rel = icon.rel;
      link.type = "image/png";
      link.sizes = icon.sizes;
      link.href = icon.href;
      link.dataset.jaegerBranding = "true";
      document.head.appendChild(link);
    }
  };

  installJaegerIcons();
  window.addEventListener("pageshow", installJaegerIcons);

  const installJaegerSurfaceLabels = () => {
    // One SI/companion face: Jaeger owns the bookmark chrome. Runtime stays Hermes under the hood.
    try {
      document.title = "Jaeger";
      const apple = document.querySelector('meta[name="apple-mobile-web-app-title"]');
      if (apple) apple.setAttribute("content", "Jaeger");
      const titlebar = document.getElementById("appTitlebarTitle");
      if (titlebar) titlebar.textContent = "Jaeger";
      const msg = document.getElementById("msg");
      if (msg && /Message Hermes/i.test(msg.getAttribute("placeholder") || "")) {
        msg.setAttribute("placeholder", "Message Jaeger…");
      }
      // Prefer API display_name when present; only rewrite obvious Hermes Agent defaults.
      const profileLabel = document.getElementById("titlebarProfileLabel");
      if (profileLabel && profileLabel.textContent.trim() === "Hermes Agent") {
        // leave — API display_name / profile chip owns this once catalog loads
      }
    } catch (_) {}
  };

  installJaegerSurfaceLabels();
  window.addEventListener("pageshow", installJaegerSurfaceLabels);
  document.addEventListener("DOMContentLoaded", installJaegerSurfaceLabels);

})();
