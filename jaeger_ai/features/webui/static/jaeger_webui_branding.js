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
})();
