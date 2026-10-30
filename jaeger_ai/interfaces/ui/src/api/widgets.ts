/**
 * Widget generation API (Jenkins Robotics, 2026-10-30, original).
 *
 * Thin same-origin wrapper for POST /v1/widgets/generate. Like every other
 * /v1/* call in this app it goes through the Vite/WebUI proxy, which attaches
 * the caller token — the browser never holds one.
 */
export interface WidgetSpecResponse {
  spec: {
    v: 1;
    source: string;
    title: string;
    about: string;
    metrics: { key: string; label: string }[];
    chart: string;
    size: string;
    hosts: string[];
  };
  latency_s: number;
}

export async function generateWidgetSpec(prompt: string): Promise<WidgetSpecResponse> {
  const response = await fetch("/v1/widgets/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ prompt }),
  });
  if (!response.ok) {
    let message = `Widget generation failed (${response.status})`;
    try {
      const body = await response.json();
      if (body && typeof body.error === "string") message = body.error;
    } catch {
      /* keep generic message */
    }
    throw new Error(message);
  }
  return (await response.json()) as WidgetSpecResponse;
}
