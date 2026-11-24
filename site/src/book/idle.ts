export function onIdle(callback: () => void, timeout: number) {
  if (typeof window.requestIdleCallback === 'function') {
    const id = window.requestIdleCallback(callback, {timeout});
    return () => window.cancelIdleCallback(id);
  }
  const id = window.setTimeout(callback, Math.min(timeout, 32));
  return () => window.clearTimeout(id);
}
