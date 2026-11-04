"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, get } from "./api";

/** Carrega um recurso da API com atualização periódica opcional. */
export function useApi<T>(path: string | null, intervalMs = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const alive = useRef(true);

  const load = useCallback(async () => {
    if (!path) return;
    try {
      const d = await get<T>(path);
      if (alive.current) {
        setData(d);
        setError(null);
      }
    } catch (e) {
      if (alive.current) setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    alive.current = true;
    setLoading(true);
    load();
    if (!intervalMs) return () => { alive.current = false; };
    const id = setInterval(() => {
      if (document.visibilityState === "visible") load();
    }, intervalMs);
    return () => {
      alive.current = false;
      clearInterval(id);
    };
  }, [load, intervalMs]);

  return { data, error, loading, reload: load, setData };
}

/** Executa uma ação com estado de carregamento e mensagem de erro. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
      return undefined;
    } finally {
      setBusy(false);
    }
  }, []);
  return { busy, error, run, setError };
}
