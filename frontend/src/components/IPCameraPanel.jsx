
import { useState } from "react";
import "./IPCameraPanel.css";

const SHARED_CAMERA_URL = "http://127.0.0.1:5001/video_feed";

export default function IPCameraPanel() {
  const [streamUrl, setStreamUrl] = useState("");
  const [status, setStatus] = useState("disconnected");
  const [error, setError] = useState("");

  function connectCamera(event) {
    event.preventDefault();

    setError("");
    setStatus("connecting");

    // Use the local SENTROVA server, not the phone's URL.
    setStreamUrl(
      `${SHARED_CAMERA_URL}?t=${Date.now()}`
    );
  }

  function disconnectCamera() {
    setStreamUrl("");
    setError("");
    setStatus("disconnected");
  }

  return (
    <section className="camera-panel">
      <div className="camera-panel__header">
        <div>
          <h2>Live Worker Camera</h2>
          <p>SENTROVA shared YOLO pose stream</p>
        </div>

        <span
          className={
            status === "connected"
              ? "camera-status camera-status--connected"
              : status === "error"
              ? "camera-status camera-status--error"
              : status === "connecting"
              ? "camera-status camera-status--connecting"
              : "camera-status"
          }
        >
          {status === "connected"
            ? "CONNECTED"
            : status === "connecting"
            ? "CONNECTING"
            : status === "error"
            ? "CONNECTION ERROR"
            : "NOT CONNECTED"}
        </span>
      </div>

      <form
        className="camera-controls"
        onSubmit={connectCamera}
      >
        <input
          type="text"
          value={SHARED_CAMERA_URL}
          readOnly
          aria-label="SENTROVA shared camera stream URL"
        />

        <button type="submit" disabled={status === "connecting"}>
          {status === "connecting" ? "Connecting..." : "Connect"}
        </button>

        <button
          type="button"
          className="camera-disconnect"
          onClick={disconnectCamera}
        >
          Disconnect
        </button>
      </form>

      {error && (
        <p className="camera-error" role="alert">
          {error}
        </p>
      )}

      <div className="camera-view">
        {streamUrl ? (
          <img
            key={streamUrl}
            src={streamUrl}
            alt="Live SENTROVA camera with pose annotations"
            onLoad={() => {
              setStatus("connected");
              setError("");
            }}
            onError={() => {
              setStatus("error");
              setError(
                "Cannot load the shared camera feed. Check that camera_fall_server.py is running and /video_feed is accessible."
              );
            }}
          />
        ) : (
          <div className="camera-placeholder">
            <span className="camera-placeholder__icon">◉</span>
            <p>Camera feed is disconnected</p>
            <small>
              Start the SENTROVA shared camera server, then connect.
            </small>
          </div>
        )}
      </div>

      <p className="camera-note">
        The dashboard receives the annotated stream from the local
        SENTROVA server. Keep the server running while viewing the feed.
        A connected stream does not mean that fall detection is validated.
      </p>
    </section>
  );
}
