import { useEffect, useState, type ReactNode } from "react";
import { Splitter } from "antd";

/** Use the existing UI library for pointer/keyboard resize and size constraints. */
export function LibrarySplit({storageKey, children}: {storageKey: string; children: [ReactNode, ReactNode]}) {
  const [narrow, setNarrow] = useState(() => matchMedia("(max-width: 900px)").matches);
  const [ratio, setRatio] = useState(() => {
    try { const saved = Number(localStorage.getItem(storageKey)); return saved >= 12 && saved <= 45 ? saved : 20; }
    catch { return 20; }
  });
  useEffect(() => {
    const media = matchMedia("(max-width: 900px)"); const change = () => setNarrow(media.matches);
    media.addEventListener("change", change); return () => media.removeEventListener("change", change);
  }, []);
  function resize(sizes: number[]) { const total = sizes[0] + sizes[1]; if (total) setRatio(100 * sizes[0] / total); }
  function save(sizes: number[]) {
    resize(sizes); const total = sizes[0] + sizes[1];
    try { if (total) localStorage.setItem(storageKey, String(100 * sizes[0] / total)); } catch { /* storage is optional */ }
  }
  if (narrow) return <div className="library-browser library-browser-stacked">{children}</div>;
  return <Splitter className="library-browser" onResize={resize} onResizeEnd={save}
    onDraggerDoubleClick={() => {setRatio(20); try {localStorage.removeItem(storageKey);} catch { /* optional */ }}}>
    <Splitter.Panel size={`${ratio}%`} min={170} max="45%">{children[0]}</Splitter.Panel>
    <Splitter.Panel size={`${100 - ratio}%`} min="45%">{children[1]}</Splitter.Panel>
  </Splitter>;
}
