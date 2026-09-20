export default function BackendStatus({ status }) {
  return <div className={`backend-status ${status}`} role="status" aria-live="polite"><span className="status-dot" aria-hidden="true" />Backend {status === 'online' ? 'Online' : status === 'offline' ? 'Offline' : 'Checking'}</div>;
}
