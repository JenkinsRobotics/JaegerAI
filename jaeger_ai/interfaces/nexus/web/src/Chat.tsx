// The chat, copied from Omni's screen (Claude-style: replies as plain text, the person's in a soft block on the right,
// tool calls folded under a reply, one composer at the bottom) and fitted to the Gateway, which takes text only.
// Swift counterparts here: files.pick (＋), clipboard.read with ClipboardPreview, mic.start/stop, tts.speak (Read aloud).
import { useEffect, useRef, useState } from 'react';
import type { Chat as ChatState, Message } from './chat.ts';
import { act, type Clip } from './agent.ts';

type Props = {
  name: string; chat: ChatState; suggestions: string[]; mic: boolean; compact?: boolean;
  onSend: (text: string) => void; onStop: () => void; onNew: () => void; onMic: () => void; onFile: (f: File) => void;
};

function Tools({ m }: { m: Message }) {
  if (!m.tools.length) return null;
  return (
    <details className="tools">
      <summary>{m.tools.length === 1 ? `Used ${m.tools[0].name}` : `Used ${m.tools.length} tools`}</summary>
      <ul>{m.tools.map((t, i) => <li key={i}><b>{t.name}</b>{t.detail ? <code>{t.detail}</code> : null}</li>)}</ul>
    </details>
  );
}

// Voice tags ([laugh], [sigh]…) are for her voice (Kokoro 0.14.0 plays a recorded laugh); the chat shows the words only.
const shown = (t: string) => t.replace(/\s*\[(laugh|laughs|chuckle|giggle|sigh|gasp)\]\s*/gi, ' ').trim();

function Reply({ m }: { m: Message }) {
  const [copied, setCopied] = useState(false), [speaking, setSpeaking] = useState(false);
  const copy = () => act('clipboard.write', m.text).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1200); });
  const speak = () => {   // the Swift app's tts.speak is Apple speech; WebKit's speechSynthesis is the same engine
    if (speaking) { speechSynthesis.cancel(); return setSpeaking(false); }
    const u = new SpeechSynthesisUtterance(shown(m.text)); u.onend = u.onerror = () => setSpeaking(false);
    setSpeaking(true); speechSynthesis.speak(u);
  };
  return (
    <div className="msg agent">
      <Tools m={m} />
      {m.text ? <div className="text">{shown(m.text)}{m.open ? <span className="caret" /> : null}</div> : null}
      {!m.open && m.text ? <div className="reply-row">
        <button className="copy" onClick={copy}>{copied ? 'Copied' : 'Copy'}</button>
        <button className="copy" onClick={speak}>{speaking ? 'Stop reading' : 'Read aloud'}</button>
      </div> : null}
    </div>
  );
}

// ClipboardPreview: text only after an explicit read, shown before it goes anywhere, refused above the limit.
function ClipboardPreview({ onUse, onClose }: { onUse: (t: string) => void; onClose: () => void }) {
  const [clip, setClip] = useState<Clip | null>(null), [err, setErr] = useState('');
  useEffect(() => { act('clipboard.read').then(setClip, e => setErr(String(e.message || e))); }, []);
  const text = clip?.state === 'text_available' ? clip.text ?? '' : '';
  return (
    <div className="clip">
      <div className="clip-head"><b>Clipboard</b><span className="dim">{clip ? `${clip.state.replaceAll('_', ' ')} · max ${Math.round(clip.max_bytes / 1000)} kB` : err || 'Reading…'}</span></div>
      {text ? <pre>{text.length > 1200 ? `${text.slice(0, 1200)}…` : text}</pre> : null}
      <div className="camera-row">
        <button className="ghost" disabled={!text} onClick={() => onUse(text)}>Insert</button>
        <button className="ghost" onClick={onClose}>Close</button>
      </div>
    </div>
  );
}

export function Chat({ name, chat, suggestions, mic, compact, onSend, onStop, onNew, onMic, onFile }: Props) {
  const [draft, setDraft] = useState(''), [clip, setClip] = useState(false), [drop, setDrop] = useState(false);
  const pick = useRef<HTMLInputElement>(null), list = useRef<HTMLDivElement>(null), box = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { list.current?.scrollTo({ top: list.current.scrollHeight, behavior: 'smooth' }); }, [chat.messages]);
  useEffect(() => { const t = box.current; if (t) { t.style.height = 'auto'; t.style.height = `${Math.min(t.scrollHeight, 200)}px`; } }, [draft]);
  useEffect(() => { if (compact) box.current?.focus(); }, [compact]);
  const add = (files: FileList | null) => Array.from(files ?? []).forEach(async f => {
    if (f.type.startsWith('text/') || /\.(md|txt|json|csv|py|ts|tsx|js|swift|yaml|yml|toml|log)$/i.test(f.name)) {
      const body = (await f.text()).slice(0, 20000);
      setDraft(d => `${d}${d ? '\n\n' : ''}${f.name}:\n${body}`);
    } else onFile(f);
  });

  const send = (text = draft) => { if (!text.trim()) return; onSend(text.trim()); setDraft(''); };
  const waiting = chat.busy && !chat.messages.some(m => m.role === 'assistant' && m.open && m.text);
  const shown = compact ? chat.messages.slice(-2) : chat.messages;

  return (
    <div className={`chat ${compact ? 'compact' : ''}`}>
      {compact ? null : <div className="chat-head">
        <div><b>{name}</b><span className={`dot ${chat.busy ? 'busy' : ''}`} />{chat.status}</div>
        <button className="ghost" onClick={onNew}>New chat</button>
      </div>}
      <div className="messages" ref={list}>
        <div className="column">
          {shown.length === 0 && !compact ? (
            <div className="hello">
              <h2>Talk with {name}</h2>
              <p>Type below, or press Mic and speak.</p>
              <div className="chips">{suggestions.map(s => <button key={s} onClick={() => send(s)}>{s}</button>)}</div>
            </div>
          ) : shown.map((m, i) =>
            m.role === 'user' ? <div key={i} className="msg user"><div className="text">{m.text}</div></div>
            : m.role === 'note' ? <div key={i} className="msg note">{m.text}</div>
            : <Reply key={i} m={m} />)}
          {waiting ? <div className="msg agent thinking">{chat.status}</div> : null}
        </div>
      </div>
      <div className="composer-wrap">
        {clip ? <ClipboardPreview onUse={t => { setDraft(d => d + t); setClip(false); }} onClose={() => setClip(false)} /> : null}
        <div className={`composer ${drop ? 'drop' : ''}`}
          onDragOver={e => { e.preventDefault(); setDrop(true); }} onDragLeave={() => setDrop(false)}
          onDrop={e => { e.preventDefault(); setDrop(false); add(e.dataTransfer.files); }}>
          <textarea ref={box} rows={1} value={draft} placeholder={compact ? 'Ask Jaeger anything…' : `Message ${name}`}
            onChange={e => setDraft(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Escape' && compact) window.close();
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); }
            }} />
          <div className="composer-row">
            <div className="tools-row">
              <input ref={pick} type="file" hidden multiple onChange={e => { add(e.target.files); e.target.value = ''; }} />
              {compact ? <span className="dim hint">↵ to send · Esc to close</span> : <>
                <button className="ghost" title="Attach text files or a sound clip" onClick={() => pick.current?.click()}>＋</button>
                <button className={`ghost ${clip ? 'on' : ''}`} title="Paste from the clipboard, with a preview" onClick={() => setClip(c => !c)}>Clipboard</button>
              </>}
              <button className={`ghost mic ${mic ? 'on' : ''}`} onClick={onMic}>{mic ? 'Stop & send' : 'Mic'}</button>
            </div>
            {chat.busy
              ? <button className="send stop" title="Stop waiting" onClick={onStop}>■</button>
              : <button className="send" title="Send" disabled={!draft.trim()} onClick={() => send()}>↑</button>}
          </div>
        </div>
      </div>
    </div>
  );
}
