import { useEffect, useState } from "react";
import { api } from "./api";

/** Fetch JSON for a path; refetches when the path changes. */
export function useApi<T>(path: string | null): { data: T | null; error: string | null; reload: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!path) return;
    let live = true;
    setError(null);
    api<T>(path).then((d) => live && setData(d)).catch((e) => live && setError(String(e.message)));
    return () => { live = false; };
  }, [path, tick]);
  return { data, error, reload: () => setTick((t) => t + 1) };
}
