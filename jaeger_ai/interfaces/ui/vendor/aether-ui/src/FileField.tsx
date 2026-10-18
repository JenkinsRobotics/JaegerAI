import { useId, useRef, useState } from "react";
import type { DragEvent, ReactNode } from "react";
import { Button } from "./Button";

export interface FileFieldProps {
  files?: readonly File[];
  defaultFiles?: readonly File[];
  onFilesChange?: (files: readonly File[]) => void;
  label: ReactNode;
  accept?: string;
  multiple?: boolean;
  disabled?: boolean;
  help?: ReactNode;
  error?: ReactNode;
  className?: string;
}

export function FileField({ files, defaultFiles = [], onFilesChange, label, accept, multiple = false, disabled = false, help, error, className }: FileFieldProps) {
  const [internal, setInternal] = useState<readonly File[]>(defaultFiles);
  const [dragging, setDragging] = useState(false);
  const current = files ?? internal;
  const inputRef = useRef<HTMLInputElement>(null);
  const inputID = useId();
  const update = (next: readonly File[]) => {
    const bounded = multiple ? next : next.slice(0, 1);
    if (files === undefined) setInternal(bounded);
    onFilesChange?.(bounded);
  };
  const drop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    if (!disabled) update([...event.dataTransfer.files]);
  };
  return <div className={["aui-file-field", dragging ? "aui-file-field--dragging" : "", className].filter(Boolean).join(" ")} aria-invalid={Boolean(error) || undefined}>
    <label htmlFor={inputID}>{label}</label>
    <div className="aui-file-drop" onDragEnter={(event) => { event.preventDefault(); if (!disabled) setDragging(true); }} onDragOver={(event) => event.preventDefault()} onDragLeave={() => setDragging(false)} onDrop={drop}>
      <input id={inputID} ref={inputRef} type="file" accept={accept} multiple={multiple} disabled={disabled} onChange={(event) => update([...(event.target.files ?? [])])} />
      <Button disabled={disabled} onClick={() => inputRef.current?.click()}>Browse…</Button>
      <span>{current.length > 0 ? `${current.length} ${current.length === 1 ? "file" : "files"} selected` : "Drop files here"}</span>
    </div>
    {current.length > 0 ? <ul>{current.map((file, index) => <li key={`${file.name}-${file.size}-${index}`}><span>{file.name}</span><small>{file.size.toLocaleString()} B</small></li>)}</ul> : null}
    {current.length > 0 ? <button type="button" className="aui-file-clear" disabled={disabled} onClick={() => update([])}>Clear files</button> : null}
    {help && !error ? <div className="aui-field-help">{help}</div> : null}
    {error ? <div className="aui-field-error" role="alert">{error}</div> : null}
  </div>;
}
