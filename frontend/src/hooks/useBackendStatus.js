import { useEffect, useState } from 'react';
import { apiClient } from '../api/client';
export function useBackendStatus() {
  const [status,setStatus] = useState('checking');
  useEffect(() => {
    let disposed = false, timer, active;
    async function check() {
      if (disposed || document.hidden || active) return;
      clearTimeout(timer); active = new AbortController();
      try {
        const health = await apiClient.get('/health',{ signal: active.signal, timeout: 10000 });
        if (!disposed) setStatus(health?.status === 'ok' || health?.status === 'healthy' ? 'online' : 'offline');
      } catch { if (!disposed) setStatus('offline'); }
      finally { active = null; if (!disposed) timer = setTimeout(check,45000); }
    }
    function visible() { if (!document.hidden) check(); else clearTimeout(timer); }
    document.addEventListener('visibilitychange',visible); check();
    return () => { disposed = true; clearTimeout(timer); active?.abort(); document.removeEventListener('visibilitychange',visible); };
  },[]);
  return status;
}
