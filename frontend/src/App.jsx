import IPCameraPanel from "./components/IPCameraPanel";
import { useCallback, useEffect, useState } from "react";
import DemoVideo from "./components/DemoVideo";
import { Video } from "lucide-react";
import {
  Activity,
  AlertTriangle,
  BellRing,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  Clock3,
  Gauge,
  LayoutDashboard,
  Radio,
  RefreshCw,
  Server,
  Settings,
  ShieldAlert,
  ShieldCheck,
  Signal,
  Siren,
  Waves,
  Wifi,
  WifiOff,
  XCircle,
} from "lucide-react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, getApiUrl, saveApiUrl } from "./api";
import "./App.css";

const NAV_ITEMS = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "sensors", label: "Sensor monitoring", icon: Activity },
  { id: "events", label: "Event history", icon: Clock3 },
  { id: "settings", label: "Settings", icon: Settings },
  { id: "demo", label: "Demo video", icon: Video },
];

const AXES = [
  { key: "ax", label: "Acceleration X", unit: "m/s²", color: "#67d9e8" },
  { key: "ay", label: "Acceleration Y", unit: "m/s²", color: "#9b91ff" },
  { key: "az", label: "Acceleration Z", unit: "m/s²", color: "#f2b866" },
  { key: "gx", label: "Gyroscope X", unit: "°/s", color: "#67d9e8" },
  { key: "gy", label: "Gyroscope Y", unit: "°/s", color: "#9b91ff" },
  { key: "gz", label: "Gyroscope Z", unit: "°/s", color: "#f2b866" },
];

function formatNumber(value, digits = 2) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return value.toFixed(digits);
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function timeLabel(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function eventTone(type = "") {
  const name = type.toUpperCase();
  if (name.includes("SOS") || name.includes("FALL")) return "danger";
  if (name.includes("WARNING") || name.includes("POTENTIAL")) return "warning";
  return "neutral";
}

function eventDescription(event) {
  if (event.details?.message) return event.details.message;
  if (event.event_type === "SOS_ACTIVE") return "Software SOS was activated.";
  if (event.event_type === "SOS_CLEARED") return "Software SOS was cleared.";
  return event.event_type?.replaceAll("_", " ") || "System event";
}

function MetricCard({ label, value, suffix, icon: Icon, tone = "cyan", detail }) {
  return (
    <article className="metric-card">
      <div className={`metric-icon ${tone}`}>
        <Icon size={19} />
      </div>
      <div className="metric-label">{label}</div>
      <div className="metric-value">
        {value}
        {suffix && <span className="metric-suffix">{suffix}</span>}
      </div>
      {detail && <div className="metric-detail">{detail}</div>}
    </article>
  );
}

function StatusPill({ good, children }) {
  return (
    <span className={`status-pill ${good ? "good" : "bad"}`}>
      <span className="status-dot" />
      {children}
    </span>
  );
}

function Panel({ title, subtitle, action, children, className = "" }) {
  return (
    <section className={`panel ${className}`}>
      <div className="panel-heading">
        <div>
          <h2>{title}</h2>
          {subtitle && <p>{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

function EmptyState({ icon: Icon = CircleHelp, title, message }) {
  return (
    <div className="empty-state">
      <Icon size={28} />
      <strong>{title}</strong>
      <p>{message}</p>
    </div>
  );
}

export default function App() {
  const [page, setPage] = useState("dashboard");
  const [apiUrl, setApiUrl] = useState(getApiUrl());
  const [apiDraft, setApiDraft] = useState(getApiUrl());
  const [backendOnline, setBackendOnline] = useState(false);
  const [backendVersion, setBackendVersion] = useState("—");
  const [serverTime, setServerTime] = useState(null);
  const [sensorStatus, setSensorStatus] = useState(null);
  const [events, setEvents] = useState([]);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [sosBusy, setSosBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [lastRefresh, setLastRefresh] = useState(null);

  const latest = sensorStatus?.latest_sensor ?? null;
  const sensorConnected = sensorStatus?.sensor_connected === true;
  const sosActive = sensorStatus?.sos_active === true;
  const threshold = sensorStatus?.fall_threshold;
  const probability = latest?.fall_probability;
  const predictionAvailable =
    typeof probability === "number" && Number.isFinite(probability);
  const apiBase = apiUrl.replace(/\/+$/, "");

  const refresh = useCallback(async (manual = false) => {
    if (manual) setRefreshing(true);

    try {
      const [healthResult, statusResult, eventsResult] = await Promise.allSettled([
        api.health(),
        api.status(),
        api.events(),
      ]);

      if (healthResult.status === "fulfilled") {
        setBackendOnline(true);
        setBackendVersion(healthResult.value.version || "—");
        setServerTime(healthResult.value.timestamp || null);
        setError("");
      } else {
        setBackendOnline(false);
        setError(healthResult.reason?.message || "Cannot connect to backend.");
      }

      if (statusResult.status === "fulfilled") {
        const nextStatus = statusResult.value;
        setSensorStatus(nextStatus);

        const sample = nextStatus.latest_sensor;
        if (sample?.timestamp) {
          setHistory((previous) => {
            if (previous.some((item) => item.timestamp === sample.timestamp)) {
              return previous;
            }

            return [
              ...previous,
              {
                ...sample,
                chartTime: timeLabel(sample.timestamp),
              },
            ].slice(-60);
          });
        }
      } else {
        setSensorStatus(null);
      }

      if (eventsResult.status === "fulfilled") {
        const list = eventsResult.value.events;
        setEvents(Array.isArray(list) ? [...list].reverse() : []);
      }

      setLastRefresh(new Date().toISOString());
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = window.setInterval(() => refresh(), 3000);
    return () => window.clearInterval(interval);
  }, [refresh, apiUrl]);

  function applyApiUrl(event) {
    event.preventDefault();
    const cleaned = apiDraft.trim().replace(/\/+$/, "");
    if (!/^https?:\/\/.+/i.test(cleaned)) {
      setNotice("Enter a valid URL beginning with http:// or https://.");
      return;
    }

    saveApiUrl(cleaned);
    setApiUrl(cleaned);
    setApiDraft(cleaned);
    setNotice("API address saved. Checking the connection…");
    refresh(true);
  }

  async function toggleSos() {
    const nextActive = !sosActive;
    const message = nextActive
      ? "Activate the software SOS alert? This changes the backend's software state only; it does not call emergency services."
      : "Clear the active software SOS alert?";

    if (!window.confirm(message)) return;

    setSosBusy(true);
    setNotice("");

    try {
      const result = await api.setSos(nextActive);
      setSensorStatus((previous) => ({
        ...(previous || {}),
        sos_active: result.sos_active,
      }));
      setNotice(result.message || "SOS state updated.");
      await refresh();
    } catch (err) {
      setNotice(`Could not update SOS: ${err.message}`);
    } finally {
      setSosBusy(false);
    }
  }

  const currentPage = NAV_ITEMS.find((item) => item.id === page);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><Activity size={23} /></div>
          <div>
            <div className="brand-name">WORKER<span>MONITOR</span></div>
            <div className="brand-caption">INDUSTRIAL SAFETY LAB</div>
          </div>
        </div>

        <div className="nav-caption">WORKSPACE</div>
        <nav className="main-nav" aria-label="Main navigation">
          {NAV_ITEMS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              className={`nav-item ${page === id ? "active" : ""}`}
              onClick={() => setPage(id)}
            >
              <Icon size={18} />
              <span>{label}</span>
              {page === id && <ChevronRight className="nav-chevron" size={15} />}
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className="environment-card">
            <div className="environment-top">
              <span className={`status-dot ${backendOnline ? "dot-good" : "dot-bad"}`} />
              <span>{backendOnline ? "API reachable" : "API unavailable"}</span>
            </div>
            <p>Prototype monitoring environment</p>
            <small>Version {backendVersion}</small>
          </div>
          <div className="sidebar-foot"><ShieldCheck size={15} /> Development build</div>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div className="breadcrumb">
            <span>Workspace</span><ChevronRight size={14} /><strong>{currentPage?.label}</strong>
          </div>
          <div className="topbar-right">
            <div className="live-indicator">
              <span className={`status-dot ${backendOnline ? "dot-good" : "dot-bad"}`} />
              {backendOnline ? "API connected" : "API disconnected"}
            </div>
            <button
              className="icon-button"
              title="Refresh data"
              aria-label="Refresh data"
              onClick={() => refresh(true)}
              disabled={refreshing}
            >
              <RefreshCw size={17} className={refreshing ? "spin" : ""} />
            </button>
          </div>
        </header>

        <div className="page-content">
          <div className="page-title-row">
            <div>
              <div className="eyebrow">INDUSTRIAL MONITORING / DEMO</div>
              <h1>{currentPage?.label || "Dashboard"}</h1>
              <p className="page-description">
                {page === "demo" && <DemoVideo />}
                {page === "dashboard" && "A live view of backend health and the latest reported sensor measurements."}
                {page === "sensors" && "Inspect the latest accelerometer and gyroscope measurements received by the backend."}
                {page === "events" && "Review events saved by the backend during this prototype session."}
                {page === "settings" && "Configure the backend address and review the active monitoring settings."}
              </p>
            </div>
            <div className="updated-label">
              <span className="status-dot dot-cyan" />
              Updated {lastRefresh ? timeLabel(lastRefresh) : "—"}
            </div>
          </div>

          {error && (
            <div className="error-banner">
              <WifiOff size={19} />
              <div><strong>Backend connection problem</strong><p>{error}</p></div>
              <button className="text-button" onClick={() => refresh(true)}>Retry</button>
            </div>
          )}

          {notice && (
            <div className="notice-banner">
              <CircleHelp size={17} />
              <span>{notice}</span>
              <button className="dismiss-button" aria-label="Dismiss notice" onClick={() => setNotice("")}>×</button>
            </div>
          )}

          {page === "dashboard" && (
            <>
              <div className="status-strip">
                <div className="strip-item">
                  <div className={`strip-icon ${backendOnline ? "healthy" : "unhealthy"}`}>
                    <Server size={18} />
                  </div>
                  <div className="strip-copy">
                    <span>Backend service</span>
                    <strong>{backendOnline ? "Operational" : "Unavailable"}</strong>
                  </div>
                  <StatusPill good={backendOnline}>{backendOnline ? "Online" : "Offline"}</StatusPill>
                </div>
                <div className="strip-divider" />
                <div className="strip-item">
                  <div className={`strip-icon ${sensorConnected ? "healthy" : "unhealthy"}`}>
                    <Radio size={18} />
                  </div>
                  <div className="strip-copy">
                    <span>Sensor stream</span>
                    <strong>{sensorConnected ? "Receiving data" : "No fresh data"}</strong>
                  </div>
                  <StatusPill good={sensorConnected}>{sensorConnected ? "Connected" : "Stale / offline"}</StatusPill>
                </div>
                <div className="strip-divider" />
                <div className="strip-item">
                  <div className={`strip-icon ${sosActive ? "unhealthy" : "healthy"}`}>
                    <Siren size={18} />
                  </div>
                  <div className="strip-copy">
                    <span>Software SOS</span>
                    <strong>{sosActive ? "Alert active" : "Not active"}</strong>
                  </div>
                  <StatusPill good={!sosActive}>{sosActive ? "Active" : "Clear"}</StatusPill>
                </div>
              </div>

              <div className="section-heading">
                <div><h2>Live measurements</h2><p>Latest sensor payload received by the backend</p></div>
                <span className="subtle-tag"><Waves size={13} /> Auto-refresh · 3 sec</span>
              </div>

              <div className="metrics-grid">
                <MetricCard
                  label="Acceleration X"
                  value={formatNumber(latest?.ax)}
                  suffix="m/s²"
                  icon={Activity}
                  tone="cyan"
                  detail="MPU6050 · X axis"
                />
                <MetricCard
                  label="Acceleration Y"
                  value={formatNumber(latest?.ay)}
                  suffix="m/s²"
                  icon={Activity}
                  tone="purple"
                  detail="MPU6050 · Y axis"
                />
                <MetricCard
                  label="Acceleration Z"
                  value={formatNumber(latest?.az)}
                  suffix="m/s²"
                  icon={Gauge}
                  tone="amber"
                  detail="MPU6050 · Z axis"
                />
                <MetricCard
                  label="Fall probability"
                  value={predictionAvailable ? `${(probability * 100).toFixed(1)}` : "N/A"}
                  suffix={predictionAvailable ? "%" : ""}
                  icon={ShieldAlert}
                  tone="red"
                  detail={predictionAvailable ? "Reported by sender; not independently verified" : "No prediction supplied"}
                />
              </div>

              <div className="content-grid">
                <Panel
                  title="Motion overview"
                  subtitle="Recent received samples · values are not interpolated"
                  action={<span className="small-label">{history.length} samples</span>}
                >
                  {history.length > 1 ? (
                    <div className="chart-wrap">
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={history} margin={{ top: 8, right: 12, left: -18, bottom: 0 }}>
                          <CartesianGrid stroke="#26333f" strokeDasharray="3 4" />
                          <XAxis dataKey="chartTime" tick={{ fill: "#8393a2", fontSize: 10 }} minTickGap={30} />
                          <YAxis tick={{ fill: "#8393a2", fontSize: 10 }} />
                          <Tooltip
                            contentStyle={{ background: "#121c26", border: "1px solid #31404d", borderRadius: 8 }}
                            labelStyle={{ color: "#dce6ee" }}
                            formatter={(value, name) => [formatNumber(value, 3), name.toUpperCase()]}
                          />
                          <Line type="monotone" dataKey="ax" name="AX" stroke="#67d9e8" dot={false} strokeWidth={2} isAnimationActive={false} />
                          <Line type="monotone" dataKey="ay" name="AY" stroke="#9b91ff" dot={false} strokeWidth={2} isAnimationActive={false} />
                          <Line type="monotone" dataKey="az" name="AZ" stroke="#f2b866" dot={false} strokeWidth={2} isAnimationActive={false} />
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  ) : (
                    <EmptyState
                      icon={Activity}
                      title={loading ? "Loading sensor data…" : "Waiting for sensor samples"}
                      message="Send more than one timestamped sensor payload to display the motion chart. The chart uses received readings only."
                    />
                  )}
                  <div className="chart-legend">
                    <span><i className="legend-dot cyan" /> AX</span>
                    <span><i className="legend-dot purple" /> AY</span>
                    <span><i className="legend-dot amber" /> AZ</span>
                  </div>
                </Panel>

                <Panel title="Detection status" subtitle="Model integration status">
                  <div className="model-status">
                    <div className="model-status-icon"><CircleHelp size={21} /></div>
                    <div><strong>Prediction not verified</strong><p>No trained, validated fall-detection model is connected to this dashboard.</p></div>
                  </div>
                  <div className="detail-row"><span>Latest reported probability</span><strong>{predictionAvailable ? `${(probability * 100).toFixed(1)}%` : "Unavailable"}</strong></div>
                  <div className="detail-row"><span>Configured threshold</span><strong>{typeof threshold === "number" ? `${(threshold * 100).toFixed(0)}%` : "—"}</strong></div>
                  <div className="detail-row"><span>Prediction source</span><strong>{latest?.prediction_source || "Unknown"}</strong></div>
                  <div className="detail-row"><span>Model version</span><strong>{latest?.model_version || "Unknown"}</strong></div>
                  <div className="info-note"><AlertTriangle size={15} /><span>A probability received from a device is displayed as reported data, not proof of a detected fall.</span></div>
                </Panel>
              </div>
<IPCameraPanel />
              <div className="content-grid lower-grid">
                <Panel
                  title="Recent events"
                  subtitle="Latest events returned by the backend"
                  action={<button className="text-button" onClick={() => setPage("events")}>View all <ChevronRight size={14} /></button>}
                >
                  {events.length ? (
                    <div className="event-list compact">
                      {events.slice(0, 5).map((event, index) => (
                        <div className="event-row" key={event.event_id ?? `${event.timestamp}-${index}`}>
                          <div className={`event-icon ${eventTone(event.event_type)}`}>
                            {eventTone(event.event_type) === "danger" ? <BellRing size={16} /> : <Activity size={16} />}
                          </div>
                          <div className="event-main">
                            <strong>{event.event_type?.replaceAll("_", " ") || "System event"}</strong>
                            <p>{eventDescription(event)}</p>
                            <small>{formatDate(event.timestamp)}</small>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <EmptyState icon={Clock3} title="No events recorded" message="Backend events will appear here when they are created." />
                  )}
                </Panel>

                <Panel title="Device freshness" subtitle="Based on the backend's latest update time">
                  <div className="freshness-number">
                    {typeof sensorStatus?.seconds_since_update === "number"
                      ? `${sensorStatus.seconds_since_update.toFixed(1)}`
                      : "—"}
                    <span>seconds</span>
                  </div>
                  <div className="freshness-track">
                    <div
                      className={`freshness-fill ${sensorConnected ? "fresh" : "stale"}`}
                      style={{
                        width: `${Math.min(100, ((sensorStatus?.seconds_since_update || 0) / 5) * 100)}%`,
                      }}
                    />
                  </div>
                  <div className="detail-row"><span>Freshness limit</span><strong>5 seconds (default)</strong></div>
                  <div className="detail-row"><span>Last sensor timestamp</span><strong>{latest ? timeLabel(latest.timestamp) : "—"}</strong></div>
                  <div className="detail-row"><span>Device ID</span><strong>{latest?.device_id || "Not reported"}</strong></div>
                  <p className="panel-footnote">A fresh payload means the backend recently received data. It does not confirm that the physical sensor is correctly installed or calibrated.</p>
                </Panel>
              </div>

              <section className={`sos-banner ${sosActive ? "sos-active" : ""}`}>
                <div className="sos-symbol"><Siren size={23} /></div>
                <div className="sos-copy">
                  <strong>{sosActive ? "Software SOS is active" : "Software emergency control"}</strong>
                  <p>{sosActive ? "The backend has an active software SOS flag." : "Use this control to set or clear the software SOS flag for testing."} This does not contact emergency services.</p>
                </div>
                <button className={`sos-button ${sosActive ? "clear" : ""}`} onClick={toggleSos} disabled={sosBusy || !backendOnline}>
                  {sosBusy ? "Updating…" : sosActive ? "Clear SOS" : "Activate SOS"}
                </button>
              </section>
            </>
          )}

          {page === "sensors" && (
            <>
              <div className="metrics-grid sensor-metrics">
                {AXES.map((axis) => (
                  <MetricCard
                    key={axis.key}
                    label={axis.label}
                    value={formatNumber(latest?.[axis.key], 3)}
                    suffix={axis.unit}
                    icon={axis.key.startsWith("a") ? Activity : Waves}
                    tone={axis.color === "#9b91ff" ? "purple" : axis.color === "#f2b866" ? "amber" : "cyan"}
                    detail={latest ? `Device ${latest.device_id || "unknown"}` : "No data received"}
                  />
                ))}
              </div>

              <Panel title="Latest sensor payload" subtitle="Exact measurement record received by the backend">
                {latest ? (
                  <>
                    <div className="data-table-wrap">
                      <table className="data-table">
                        <thead><tr><th>Field</th><th>Value</th><th>Unit / description</th></tr></thead>
                        <tbody>
                          {AXES.map((axis) => (
                            <tr key={axis.key}><td><code>{axis.key}</code></td><td>{formatNumber(latest[axis.key], 5)}</td><td>{axis.unit}</td></tr>
                          ))}
                          <tr><td><code>device_id</code></td><td>{latest.device_id || "—"}</td><td>Sender identifier</td></tr>
                          <tr><td><code>timestamp</code></td><td>{formatDate(latest.timestamp)}</td><td>Backend receipt time</td></tr>
                          <tr><td><code>prediction_source</code></td><td>{latest.prediction_source || "unknown"}</td><td>Reported source</td></tr>
                          <tr><td><code>model_version</code></td><td>{latest.model_version || "unknown"}</td><td>Reported version</td></tr>
                        </tbody>
                      </table>
                    </div>
                    <div className="info-note"><CircleHelp size={15} /><span>The timestamp shown is assigned by the backend on receipt; it is not necessarily the sensor's original capture time.</span></div>
                  </>
                ) : (
                  <EmptyState icon={Radio} title="No sensor payload yet" message="Start the device or send a test payload to the POST /sensor endpoint." />
                )}
              </Panel>

              <Panel title="Recent acceleration samples" subtitle="Values recorded while this page is open">
                {history.length > 1 ? (
                  <div className="chart-wrap tall-chart">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={history} margin={{ top: 8, right: 16, left: -12, bottom: 0 }}>
                        <CartesianGrid stroke="#26333f" strokeDasharray="3 4" />
                        <XAxis dataKey="chartTime" tick={{ fill: "#8393a2", fontSize: 10 }} minTickGap={25} />
                        <YAxis tick={{ fill: "#8393a2", fontSize: 10 }} />
                        <Tooltip contentStyle={{ background: "#121c26", border: "1px solid #31404d" }} />
                        <Line type="monotone" dataKey="ax" stroke="#67d9e8" name="AX" dot={false} isAnimationActive={false} />
                        <Line type="monotone" dataKey="ay" stroke="#9b91ff" name="AY" dot={false} isAnimationActive={false} />
                        <Line type="monotone" dataKey="az" stroke="#f2b866" name="AZ" dot={false} isAnimationActive={false} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <EmptyState icon={Waves} title="Collecting samples" message="The chart appears after distinct sensor records arrive." />
                )}
              </Panel>
            </>
          )}

          {page === "events" && (
            <Panel title="Event history" subtitle={`${events.length} event(s) returned by the backend`} action={<button className="outline-button" onClick={() => refresh(true)}><RefreshCw size={14} /> Refresh</button>}>
              {events.length ? (
                <div className="event-list full-event-list">
                  {events.map((event, index) => (
                    <div className="event-row" key={event.event_id ?? `${event.timestamp}-${index}`}>
                      <div className={`event-icon ${eventTone(event.event_type)}`}>
                        {eventTone(event.event_type) === "danger" ? <BellRing size={16} /> : <Activity size={16} />}
                      </div>
                      <div className="event-main">
                        <div className="event-title-line">
                          <strong>{event.event_type?.replaceAll("_", " ") || "System event"}</strong>
                          <span className={`event-tag ${eventTone(event.event_type)}`}>{eventTone(event.event_type)}</span>
                        </div>
                        <p>{eventDescription(event)}</p>
                        <small>{formatDate(event.timestamp)} · Event ID {event.event_id ?? "—"}</small>
                        {event.details && Object.keys(event.details).length > 0 && (
                          <pre className="event-details">{JSON.stringify(event.details, null, 2)}</pre>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState icon={Clock3} title="No event history yet" message="When the backend records an event, it will be listed here. SOS activation and clearing create events." />
              )}
            </Panel>
          )}

          {page === "settings" && (
            <div className="settings-layout">
              <Panel title="Backend connection" subtitle="Configure where this dashboard sends API requests">
                <form className="settings-form" onSubmit={applyApiUrl}>
                  <label htmlFor="api-url">Flask API base URL</label>
                  <input
                    id="api-url"
                    type="url"
                    value={apiDraft}
                    onChange={(event) => setApiDraft(event.target.value)}
                    placeholder="http://localhost:5000"
                    required
                  />
                  <p className="field-help">Use http://localhost:5000 when the browser and backend run on the same computer. For a phone or another computer, use the backend computer's LAN IP address and ensure the firewall permits the connection.</p>
                  <button className="primary-button" type="submit">Save and test connection</button>
                </form>
                <div className="detail-row"><span>Current API address</span><strong className="url-value">{apiBase}</strong></div>
                <div className="detail-row"><span>Connection</span><StatusPill good={backendOnline}>{backendOnline ? "Reachable" : "Unavailable"}</StatusPill></div>
                <div className="detail-row"><span>Backend version</span><strong>{backendVersion}</strong></div>
                <div className="detail-row"><span>Backend timestamp</span><strong>{formatDate(serverTime)}</strong></div>
              </Panel>

              <Panel title="Monitoring configuration" subtitle="Values currently reported by the backend">
                <div className="settings-value-card">
                  <div className="settings-value-icon"><Gauge size={19} /></div>
                  <div><span>Fall probability threshold</span><strong>{typeof threshold === "number" ? `${(threshold * 100).toFixed(0)}%` : "Not available"}</strong></div>
                </div>
                <div className="settings-value-card">
                  <div className="settings-value-icon"><Clock3 size={19} /></div>
                  <div><span>Sensor freshness limit</span><strong>5 seconds by default</strong></div>
                </div>
                <div className="info-note"><AlertTriangle size={15} /><span>The threshold is displayed for reference. The current backend does not run a fall classifier or change its behavior based on this dashboard setting.</span></div>
              </Panel>

              <Panel title="Prototype and safety notice" subtitle="Read before any real-world use">
                <div className="safety-copy">
                  <div><ShieldCheck size={19} /><p>This application is a development prototype. It is not a certified industrial safety device.</p></div>
                  <div><AlertTriangle size={19} /><p>Do not rely on this dashboard as the sole means of detecting accidents or protecting workers. Maintain supervision, PPE, and established emergency procedures.</p></div>
                  <div><Wifi size={19} /><p>A backend connection or fresh payload does not guarantee the physical sensor, Wi-Fi link, or camera is functioning correctly.</p></div>
                  <div><XCircle size={19} /><p>The software SOS only changes the backend state; no phone call, siren, or external emergency notification is implemented here.</p></div>
                </div>
              </Panel>
            </div>
          )}

          <footer className="page-footer">
            <span>Worker monitoring prototype</span>
            <span>For development and demonstration only</span>
          </footer>
        </div>
      </main>
    </div>
  );
}
