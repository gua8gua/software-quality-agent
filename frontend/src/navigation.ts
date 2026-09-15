import { useMemo, useSyncExternalStore } from "react";

export function navigate(path: string) {
  window.location.hash = path;
}

function subscribe(update: () => void) {
  window.addEventListener("hashchange", update);
  return () => window.removeEventListener("hashchange", update);
}

export function useHashRoute() {
  const hash = useSyncExternalStore(subscribe, () => window.location.hash);
  return useMemo(() => {
    try { return hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent); }
    catch { return []; }
  }, [hash]);
}
