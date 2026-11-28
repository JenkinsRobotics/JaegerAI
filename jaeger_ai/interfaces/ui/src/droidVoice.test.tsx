import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DroidVoice, isSleepVoiceCommand } from "../../../../packages/jaeger-ui-features/src/DroidVoice";
import { JaegerApp } from "@jaeger/ui-features";

const originalMediaDevices = Object.getOwnPropertyDescriptor(navigator, "mediaDevices");
const originalSpeechSynthesis = Object.getOwnPropertyDescriptor(window, "speechSynthesis");
const originalUtterance = Object.getOwnPropertyDescriptor(globalThis, "SpeechSynthesisUtterance");

let currentAudioLevel = 0;
let lastAudioContext: FakeAudioContext | null = null;
let lastRecorder: FakeMediaRecorder | null = null;

class FakeAudioContext {
  state = "running";
  resume = vi.fn(async () => undefined);
  close = vi.fn(async () => {
    this.state = "closed";
  });
  constructor() {
    lastAudioContext = this;
  }
  createAnalyser() {
    return {
      fftSize: 0,
      getFloatTimeDomainData: (samples: Float32Array) => samples.fill(currentAudioLevel),
    };
  }
  createMediaStreamSource() {
    return { connect: <T,>(target: T) => target };
  }
  createDelay() {
    return { delayTime: { value: 0 }, connect: <T,>(target: T) => target };
  }
  createMediaStreamDestination() {
    return { stream: {} as MediaStream };
  }
}

class FakeMediaRecorder {
  state: "inactive" | "recording" = "inactive";
  mimeType = "audio/webm";
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;

  constructor(_stream: MediaStream) {
    lastRecorder = this;
  }

  start() {
    this.state = "recording";
  }

  stop() {
    if (this.state !== "recording") return;
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["voice"], { type: this.mimeType }) });
    this.onstop?.();
  }
}

function setupMediaSession() {
  currentAudioLevel = 0;
  lastAudioContext = null;
  lastRecorder = null;
  const stopTrack = vi.fn();
  const track = { label: "Studio microphone", enabled: true, stop: stopTrack };
  const stream = {
    getAudioTracks: () => [track],
    getTracks: () => [track],
  } as unknown as MediaStream;
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia: vi.fn(async () => stream) },
  });
  vi.stubGlobal("AudioContext", FakeAudioContext);
  vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
  return { stopTrack, track, stream };
}

async function triggerUtterance(clock: { offset: number }) {
  currentAudioLevel = 0.25;
  await waitFor(() => expect(lastRecorder?.state).toBe("recording"));
  currentAudioLevel = 0;
  clock.offset += 1200;
}

describe("isSleepVoiceCommand", () => {
  it("matches explicit sleep and camera-park commands", () => {
    const positives = [
      "Jaeger, go to sleep",
      "Truth, go to sleep",
      "hey jaeger go to sleep",
      "go to sleep",
      "turn off droid",
      "Jaeger, turn off droid mode",
      "turn off droid mode",
      "turn droid mode off",
      "exit droid mode",
      "leave droid mode",
      "disable droid mode",
      "stop droid mode",
      "shut off droid mode",
      "droid mode off",
      "Truth, droid mode off please",
      "droid sleep",
      "park camera",
      "park the camera",
      "shut down droid",
      "power down droid",
      "Okay Truth, park the camera please.",
    ];
    for (const phrase of positives) {
      expect(isSleepVoiceCommand(phrase), phrase).toBe(true);
    }
  });

  it("does not false-trigger on conversational questions or mentions", () => {
    const negatives = [
      "why do people go to sleep?",
      "Jaeger, why do people go to sleep?",
      "how do I turn off droid mode?",
      "how do I turn off droid mode",
      "Jaeger, how do I turn off droid mode",
      "why turn off droid mode",
      "what does exit droid mode do",
      "Tell me why people go to sleep",
      "I need to go to sleep early tonight",
      "Truth, what time is it",
      "sleep",
    ];
    for (const phrase of negatives) {
      expect(isSleepVoiceCommand(phrase), phrase).toBe(false);
    }
  });
});

describe("DroidVoice", () => {
  afterEach(() => {
    currentAudioLevel = 0;
    lastAudioContext = null;
    lastRecorder = null;
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    if (originalMediaDevices) Object.defineProperty(navigator, "mediaDevices", originalMediaDevices);
    else Reflect.deleteProperty(navigator, "mediaDevices");
    if (originalSpeechSynthesis) Object.defineProperty(window, "speechSynthesis", originalSpeechSynthesis);
    else Reflect.deleteProperty(window, "speechSynthesis");
    if (originalUtterance) Object.defineProperty(globalThis, "SpeechSynthesisUtterance", originalUtterance);
    else Reflect.deleteProperty(globalThis, "SpeechSynthesisUtterance");
    window.history.pushState(null, "", "/");
  });

  it("opens the floating orb in document.body, minimizes/expands cleanly, and closes owned media on End", async () => {
    const { stopTrack } = setupMediaSession();
    const onCamera = vi.fn();

    render(<DroidVoice baseUrl="" reply="" busy={false} onCamera={onCamera} onTranscript={vi.fn(async () => true)} />);
    fireEvent.click(screen.getByRole("button", { name: "Start Droid Conversation" }));

    const dialog = await screen.findByRole("dialog", { name: "Droid voice conversation" });
    expect(dialog).toBeVisible();
    expect(dialog.parentElement).toBe(document.body);
    expect(screen.getByText("Listening for “Jaeger”")).toBeVisible();
    expect(onCamera).toHaveBeenCalledWith(true);

    // Minimize via button -> compact floating orb
    fireEvent.click(screen.getByRole("button", { name: "Minimize Droid voice orb" }));
    expect(screen.queryByRole("dialog", { name: "Droid voice conversation" })).toBeNull();
    const expandBtn = screen.getByRole("button", { name: "Expand Droid voice orb" });
    expect(expandBtn.closest(".jg-droid-voice-popover")).toHaveAttribute("data-compact", "true");

    // Expand back -> full dialog
    fireEvent.click(expandBtn);
    expect(await screen.findByRole("dialog", { name: "Droid voice conversation" })).toBeVisible();

    // Escape minimizes, Shift+Escape ends
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getByRole("button", { name: "Expand Droid voice orb" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Expand Droid voice orb" }));
    expect(await screen.findByRole("dialog", { name: "Droid voice conversation" })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "End" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Droid voice conversation" })).toBeNull());
    expect(stopTrack).toHaveBeenCalled();
    expect(lastAudioContext?.close).toHaveBeenCalled();
    expect(onCamera).toHaveBeenLastCalledWith(false);
  });

  it("handles spoken 'Jaeger, go to sleep' by invoking onSleep, closing mic/camera, and skipping onTranscript", async () => {
    const { stopTrack } = setupMediaSession();
    const realNow = performance.now.bind(performance);
    const clock = { offset: 0 };
    vi.spyOn(performance, "now").mockImplementation(() => realNow() + clock.offset);

    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({ transcript: "Jaeger, go to sleep", intent: "sleep" }),
    }));
    vi.stubGlobal("fetch", fetchMock);

    const onCamera = vi.fn();
    const onTranscript = vi.fn(async () => true);
    const onSleep = vi.fn(async () => true);

    render(
      <DroidVoice
        baseUrl="http://127.0.0.1:33418"
        reply=""
        busy={false}
        onCamera={onCamera}
        onTranscript={onTranscript}
        onSleep={onSleep}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Start Droid Conversation" }));
    expect(await screen.findByRole("dialog", { name: "Droid voice conversation" })).toBeVisible();

    await triggerUtterance(clock);

    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Droid voice conversation" })).toBeNull());
    expect(onSleep).toHaveBeenCalledTimes(1);
    expect(onTranscript).not.toHaveBeenCalled();
    expect(stopTrack).toHaveBeenCalled();
    expect(lastAudioContext?.close).toHaveBeenCalled();
    expect(onCamera).toHaveBeenLastCalledWith(false);
    expect(screen.getByText("Droid asleep — camera parked.")).toBeVisible();
  });

  it("falls back to POST /v1/droid/sleep when onSleep prop is omitted", async () => {
    setupMediaSession();
    const realNow = performance.now.bind(performance);
    const clock = { offset: 0 };
    vi.spyOn(performance, "now").mockImplementation(() => realNow() + clock.offset);

    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("/v1/droid/transcribe")) {
        return { ok: true, json: async () => ({ transcript: "park the camera" }) };
      }
      return { ok: true, json: async () => ({ ok: true, sleeping: true, camera: "parked" }) };
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<DroidVoice baseUrl="http://127.0.0.1:33418" reply="" busy={false} onCamera={vi.fn()} onTranscript={vi.fn(async () => true)} />);
    fireEvent.click(screen.getByRole("button", { name: "Start Droid Conversation" }));
    expect(await screen.findByRole("dialog", { name: "Droid voice conversation" })).toBeVisible();

    await triggerUtterance(clock);

    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Droid voice conversation" })).toBeNull());
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:33418/v1/droid/sleep",
      expect.objectContaining({ method: "POST" }),
    );
    expect(screen.getByText("Droid asleep — camera parked.")).toBeVisible();
  });

  it("triggers sleep, parks camera, and closes orb when Sleep button is clicked", async () => {
    const { stopTrack } = setupMediaSession();
    const onCamera = vi.fn();
    const onSleep = vi.fn(async () => true);

    render(
      <DroidVoice
        baseUrl=""
        reply=""
        busy={false}
        onCamera={onCamera}
        onTranscript={vi.fn(async () => true)}
        onSleep={onSleep}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Start Droid Conversation" }));
    expect(await screen.findByRole("dialog", { name: "Droid voice conversation" })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Sleep" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Droid voice conversation" })).toBeNull());
    expect(onSleep).toHaveBeenCalledTimes(1);
    expect(stopTrack).toHaveBeenCalled();
    expect(onCamera).toHaveBeenLastCalledWith(false);
    expect(screen.getByText("Droid asleep — camera parked.")).toBeVisible();
  });

  it("does not trigger sleep on conversational mention like 'why do people go to sleep?'", async () => {
    setupMediaSession();
    const realNow = performance.now.bind(performance);
    const clock = { offset: 0 };
    vi.spyOn(performance, "now").mockImplementation(() => realNow() + clock.offset);

    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => ({ transcript: "Jaeger, why do people go to sleep?" }),
      })),
    );

    const onSleep = vi.fn(async () => true);
    const onTranscript = vi.fn(async () => true);

    render(
      <DroidVoice
        baseUrl=""
        reply=""
        busy={false}
        onCamera={vi.fn()}
        onTranscript={onTranscript}
        onSleep={onSleep}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Start Droid Conversation" }));
    expect(await screen.findByRole("dialog", { name: "Droid voice conversation" })).toBeVisible();

    await triggerUtterance(clock);

    await waitFor(() => expect(onTranscript).toHaveBeenCalledWith("Jaeger, why do people go to sleep?"));
    expect(onSleep).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: "Droid voice conversation" })).toBeVisible();
  });

  it("closes an active voice orb automatically when sleeping prop changes to true", async () => {
    const { stopTrack } = setupMediaSession();
    const onCamera = vi.fn();

    const { rerender } = render(
      <DroidVoice
        baseUrl=""
        reply=""
        busy={false}
        sleeping={false}
        onCamera={onCamera}
        onTranscript={vi.fn(async () => true)}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Start Droid Conversation" }));
    expect(await screen.findByRole("dialog", { name: "Droid voice conversation" })).toBeVisible();

    rerender(
      <DroidVoice
        baseUrl=""
        reply=""
        busy={false}
        sleeping={true}
        onCamera={onCamera}
        onTranscript={vi.fn(async () => true)}
      />,
    );

    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Droid voice conversation" })).toBeNull());
    expect(stopTrack).toHaveBeenCalled();
    expect(onCamera).toHaveBeenLastCalledWith(false);
    expect(screen.getByText("Droid asleep — camera parked.")).toBeVisible();
  });

  it("auto-wakes before opening mic when sleeping is true, and aborts cleanly if wake fails", async () => {
    setupMediaSession();
    const onWakeFail = vi.fn(async () => false);
    const onCamera = vi.fn();

    const { rerender } = render(
      <DroidVoice
        baseUrl=""
        reply=""
        busy={false}
        sleeping={true}
        onWake={onWakeFail}
        onCamera={onCamera}
        onTranscript={vi.fn(async () => true)}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Start Droid Conversation" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not wake Droid");
    expect(onWakeFail).toHaveBeenCalledTimes(1);
    expect(onCamera).not.toHaveBeenCalledWith(true);

    const onWakeOk = vi.fn(async () => true);
    rerender(
      <DroidVoice
        baseUrl=""
        reply=""
        busy={false}
        sleeping={true}
        onWake={onWakeOk}
        onCamera={onCamera}
        onTranscript={vi.fn(async () => true)}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Start Droid Conversation" }));
    expect(await screen.findByRole("dialog", { name: "Droid voice conversation" })).toBeVisible();
    expect(onWakeOk).toHaveBeenCalledTimes(1);
    expect(onCamera).toHaveBeenCalledWith(true);
  });

  it("supports configured aiName='Truth' alongside 'Jaeger' wake words", async () => {
    setupMediaSession();
    const realNow = performance.now.bind(performance);
    const clock = { offset: 0 };
    vi.spyOn(performance, "now").mockImplementation(() => realNow() + clock.offset);

    const transcripts = ["Truth, what time is it", "Jaeger, check status"];
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => ({ transcript: transcripts.shift() || "" }),
      })),
    );

    const onTranscript = vi.fn(async () => true);

    render(
      <DroidVoice
        baseUrl=""
        aiName="Truth"
        reply=""
        busy={false}
        onCamera={vi.fn()}
        onTranscript={onTranscript}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Start Droid Conversation" }));
    expect(await screen.findByRole("dialog", { name: "Droid voice conversation" })).toBeVisible();
    expect(screen.getByText("Listening for “Truth”")).toBeVisible();

    await triggerUtterance(clock);
    await waitFor(() => expect(onTranscript).toHaveBeenCalledWith("Truth, what time is it"));

    await triggerUtterance(clock);
    await waitFor(() => expect(onTranscript).toHaveBeenCalledWith("Jaeger, check status"));
  });

  it("speaks replies without failing prematurely when getVoices() is initially empty", async () => {
    setupMediaSession();
    const speak = vi.fn();
    const cancel = vi.fn();
    const synth = {
      pending: false,
      getVoices: vi.fn(() => []),
      speak,
      cancel,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    };
    Object.defineProperty(window, "speechSynthesis", { configurable: true, value: synth });
    class FakeUtterance {
      text: string;
      lang = "";
      voice: SpeechSynthesisVoice | null = null;
      onstart: (() => void) | null = null;
      onend: (() => void) | null = null;
      onerror: (() => void) | null = null;
      constructor(text: string) {
        this.text = text;
      }
    }
    vi.stubGlobal("SpeechSynthesisUtterance", FakeUtterance);

    const { rerender } = render(
      <DroidVoice baseUrl="" reply="" replyId="r1" busy={false} onCamera={vi.fn()} onTranscript={vi.fn(async () => true)} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Start Droid Conversation" }));
    expect(await screen.findByRole("dialog", { name: "Droid voice conversation" })).toBeVisible();

    rerender(
      <DroidVoice
        baseUrl=""
        reply="All systems nominal."
        replyId="r2"
        busy={false}
        onCamera={vi.fn()}
        onTranscript={vi.fn(async () => true)}
      />,
    );

    await waitFor(() => expect(speak).toHaveBeenCalledTimes(1));
    expect(screen.queryByText(/No local English playback voice/)).toBeNull();
  });

  it("keeps microphone permission errors visible beside the launcher", async () => {
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn(async () => { throw new Error("denied"); }) },
    });
    vi.stubGlobal("AudioContext", FakeAudioContext);

    render(<DroidVoice baseUrl="" reply="" busy={false} onCamera={vi.fn()} onTranscript={vi.fn(async () => true)} />);
    fireEvent.click(screen.getByRole("button", { name: "Start Droid Conversation" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Microphone unavailable");
  });
});

describe("JaegerApp Droid tab status and sleep/wake controls", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    window.history.pushState(null, "", "/");
  });

  it("syncs /v1/droid/status, disables gimbal while asleep, and keeps Go to Sleep enabled under E-Stop", async () => {
    window.history.pushState(null, "", "/droid");
    let droidState = {
      ok: true,
      awake: false,
      sleeping: true,
      camera: "parked",
      pose: { pan_deg: 0, tilt_deg: -85, zoom: 1, tracking: false },
      estop_active: true,
    };

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/v1/droid/status")) {
        return { ok: true, status: 200, json: async () => droidState };
      }
      if (url.includes("/v1/droid/sleep") && init?.method === "POST") {
        droidState = { ...droidState, awake: false, sleeping: true, camera: "parked" };
        return {
          ok: true,
          status: 200,
          json: async () => ({
            ok: true,
            action: "sleep",
            awake: false,
            sleeping: true,
            camera: "parked",
            pose: { pan_deg: 0, tilt_deg: -85, zoom: 1, tracking: false },
            hardware_dispatched: true,
          }),
        };
      }
      if (url.includes("/v1/system/resources")) {
        return { ok: true, status: 200, json: async () => ({ resources: { estop_active: true } }) };
      }
      if (url.includes("/v1/identity")) {
        return { ok: true, status: 200, json: async () => ({ identity: { ai_name: "Truth", owner_name: "Owner" } }) };
      }
      if (url.includes("/v1/chat/session")) {
        return { ok: true, status: 200, json: async () => ({ session: { session_id: "sess-1" } }) };
      }
      if (url.includes("/messages")) {
        return { ok: true, status: 200, json: async () => ({ messages: [], has_older: false, after_seq: 0 }) };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<JaegerApp baseUrl="" />);

    expect(await screen.findByText("State: Asleep (Camera Parked)")).toBeVisible();
    expect(screen.getByText(/tilt -85°/)).toBeVisible();

    // Under E-Stop + Asleep: Wake Droid, gimbal, and camera are disabled, but Go to Sleep MUST stay enabled!
    expect(screen.getByRole("button", { name: "Wake Droid" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Look Left" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Center Gimbal" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Look Right" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Start Live Camera" })).toBeDisabled();

    const sleepBtn = screen.getByRole("button", { name: "Go to Sleep" });
    expect(sleepBtn).toBeEnabled();
    fireEvent.click(sleepBtn);

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/v1/droid/sleep",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("renders a 1-click Droid Mode ON/OFF switch that toggles wake/sleep and never blocks Turn Off on E-Stop", async () => {
    window.history.pushState(null, "", "/droid");
    let droidState = {
      ok: true,
      awake: true,
      sleeping: false,
      camera: "ready",
      pose: { pan_deg: 0, tilt_deg: 0, zoom: 1, tracking: false },
      estop_active: true,
    };

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/v1/droid/status")) {
        return { ok: true, status: 200, json: async () => droidState };
      }
      if (url.includes("/v1/droid/sleep") && init?.method === "POST") {
        droidState = { ...droidState, awake: false, sleeping: true, camera: "parked", pose: { pan_deg: 0, tilt_deg: -85, zoom: 1, tracking: false } };
        return { ok: true, status: 200, json: async () => ({ ...droidState, action: "sleep", hardware_dispatched: true }) };
      }
      if (url.includes("/v1/droid/wake") && init?.method === "POST") {
        droidState = { ...droidState, awake: true, sleeping: false, camera: "ready", pose: { pan_deg: 0, tilt_deg: 0, zoom: 1, tracking: false } };
        return { ok: true, status: 200, json: async () => ({ ...droidState, action: "wake", hardware_dispatched: true }) };
      }
      if (url.includes("/v1/system/estop") && init?.method === "POST") {
        droidState = { ...droidState, estop_active: false };
        return { ok: true, status: 200, json: async () => ({ ok: true, resources: { estop_active: false } }) };
      }
      if (url.includes("/v1/system/resources")) {
        return { ok: true, status: 200, json: async () => ({ resources: { estop_active: droidState.estop_active } }) };
      }
      if (url.includes("/v1/identity")) {
        return { ok: true, status: 200, json: async () => ({ identity: { ai_name: "Truth", owner_name: "Owner" } }) };
      }
      if (url.includes("/v1/chat/session")) {
        return { ok: true, status: 200, json: async () => ({ session: { session_id: "sess-toggle" } }) };
      }
      if (url.includes("/messages")) {
        return { ok: true, status: 200, json: async () => ({ messages: [], has_older: false, after_seq: 0 }) };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<JaegerApp baseUrl="" />);

    // Awake + E-Stop ON: Droid Mode switch is checked and STILL enabled so Turn Off / Sleep is never blocked!
    const modeSwitch = await screen.findByRole("switch", { name: /Droid Mode: ON/i });
    expect(modeSwitch).toHaveAttribute("aria-checked", "true");
    expect(modeSwitch).toHaveTextContent("Turn Off Droid Mode");
    expect(modeSwitch).toBeEnabled();

    fireEvent.click(modeSwitch);
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/v1/droid/sleep",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    await waitFor(() => expect(modeSwitch).toHaveAttribute("aria-checked", "false"));
    expect(modeSwitch).toHaveTextContent("Droid Mode: OFF");
    expect(modeSwitch).toHaveTextContent("Turn On Droid Mode");
    // Now asleep while E-Stop is still ON -> Turn On is blocked fail-closed.
    expect(modeSwitch).toBeDisabled();

    // Release E-Stop -> Turn On Droid Mode becomes enabled and wakes via /v1/droid/wake.
    fireEvent.click(screen.getByRole("button", { name: "E-STOP ON" }));
    await waitFor(() => expect(modeSwitch).toBeEnabled());

    fireEvent.click(modeSwitch);
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/v1/droid/wake",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    await waitFor(() => expect(modeSwitch).toHaveAttribute("aria-checked", "true"));
    expect(modeSwitch).toHaveTextContent("Droid Mode: ON");
  });

  it("defaults both sidebars to closed on narrow mobile viewports (e.g. 390px iPhone Safari)", () => {
    const originalWidth = window.innerWidth;
    window.localStorage.setItem("jaeger.shell.leftSidebar", "open");
    window.localStorage.setItem("jaeger.shell.rightSidebar", "open");
    Object.defineProperty(window, "innerWidth", { configurable: true, writable: true, value: 390 });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, status: 200, json: async () => ({}) })),
    );

    try {
      render(<JaegerApp baseUrl="" />);
      const shell = screen.getByTestId("jaeger-modular-app");
      expect(shell).toHaveAttribute("data-left-open", "false");
      expect(shell).toHaveAttribute("data-right-open", "false");
    } finally {
      Object.defineProperty(window, "innerWidth", { configurable: true, writable: true, value: originalWidth });
      window.localStorage.clear();
    }
  });
});
