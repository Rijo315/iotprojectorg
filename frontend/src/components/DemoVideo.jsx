import { useEffect, useMemo, useRef, useState } from "react";

import { AlertTriangle, CheckCircle2, Film, LoaderCircle, Upload, Video, XCircle } from "lucide-react";

import "./DemoVideo.css";



const DEMO_API = (import.meta.env.VITE_DEMO_API_URL || "http://127.0.0.1:5002").replace(/\/+$/, "");

const MAX_FILE_BYTES = 200 * 1024 * 1024;

const ALLOWED_EXTENSIONS = [".mp4", ".avi", ".mov", ".mkv", ".mpeg", ".mpg", ".m4v"];



function formatSeconds(value) {

  if (!Number.isFinite(value)) return "00:00";

  const total = Math.max(0, Math.floor(value));

  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;

}



function formatDate(value) {

  if (!value) return "—";

  const date = new Date(value);

  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();

}



export default function DemoVideo() {

  const [file, setFile] = useState(null);

  const [job, setJob] = useState(null);

  const [uploading, setUploading] = useState(false);

  const [error, setError] = useState("");

  const [serviceHealth, setServiceHealth] = useState(null);

  const [currentTime, setCurrentTime] = useState(0);

  const [playbackError, setPlaybackError] = useState("");

  const videoRef = useRef(null);



  useEffect(() => {

    let cancelled = false;

    fetch(`${DEMO_API}/health`)

      .then((response) => {

        if (!response.ok) throw new Error(`Demo service returned HTTP ${response.status}`);

        return response.json();

      })

      .then((data) => { if (!cancelled) setServiceHealth(data); })

      .catch((err) => { if (!cancelled) setError(`Demo video service is unavailable: ${err.message}`); });

    return () => { cancelled = true; };

  }, []);



  useEffect(() => {

    if (!job?.job_id || !["queued", "processing"].includes(job.state)) return undefined;

    let cancelled = false;

    const poll = async () => {

      try {

        const response = await fetch(`${DEMO_API}/api/demo/status/${job.job_id}`);

        const data = await response.json();

        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);

        if (!cancelled) {

          setJob(data);

          if (data.state === "error") setError(data.error || "Video processing failed.");

        }

      } catch (err) {

        if (!cancelled) setError(`Could not read processing status: ${err.message}`);

      }

    };

    poll();

    const timer = window.setInterval(poll, 1000);

    return () => {

      cancelled = true;

      window.clearInterval(timer);

    };

  }, [job?.job_id, job?.state]);



  const events = job?.events || [];

  const currentWarning = useMemo(() => {

    const preceding = [...events]

      .filter((event) => Number(event.clip_time_seconds) <= currentTime)

      .sort((a, b) => a.clip_time_seconds - b.clip_time_seconds);

    const latest = preceding.at(-1);

    return latest?.event_type === "DEMO_POTENTIAL_FALL";

  }, [events, currentTime]);



  const activeEvent = useMemo(() => {

    return events.find((event) =>

      Math.abs(Number(event.clip_time_seconds) - currentTime) <= 1.25

    ) || null;

  }, [events, currentTime]);



  function chooseFile(nextFile) {

    setError("");

    setJob(null);

    setCurrentTime(0);

    setPlaybackError("");

    if (!nextFile) {

      setFile(null);

      return;

    }

    const ext = `.${nextFile.name.split(".").pop()}`.toLowerCase();

    if (!ALLOWED_EXTENSIONS.includes(ext)) {

      setFile(null);

      setError(`Unsupported file type. Use ${ALLOWED_EXTENSIONS.join(", ")}.`);

      return;

    }

    if (nextFile.size > MAX_FILE_BYTES) {

      setFile(null);

      setError("The file is larger than 200 MB. Choose a smaller demo clip.");

      return;

    }

    setFile(nextFile);

  }



  async function uploadVideo(event) {

    event.preventDefault();

    if (!file || uploading) return;

    setUploading(true);

    setError("");

    setJob(null);

    setCurrentTime(0);

    setPlaybackError("");

    try {

      const form = new FormData();

      form.append("video", file);

      const response = await fetch(`${DEMO_API}/api/demo/upload`, { method: "POST", body: form });

      const data = await response.json();

      if (!response.ok) throw new Error(data.error || `Upload failed (HTTP ${response.status})`);

      setJob({ job_id: data.job_id, filename: data.filename, state: data.state, progress: 0, events: [] });

    } catch (err) {

      setError(err.message || "Could not upload the demo video.");

    } finally {

      setUploading(false);

    }

  }



  function resetDemo() {

    setFile(null);

    setJob(null);

    setError("");

    setCurrentTime(0);

    setPlaybackError("");

    if (videoRef.current) videoRef.current.pause();

  }



  const videoUrl = job?.state === "completed"

    ? `${DEMO_API}/api/demo/video/${job.job_id}`

    : "";



  return (

    <section className="demo-video-page">

      <div className="demo-video-heading">

        <div>

          <div className="demo-eyebrow">SENTROVA / DEMONSTRATION MODE</div>

          <h2>Upload Demo Video</h2>

          <p>Process a prerecorded clip with the installed YOLO pose model and review annotated playback.</p>

        </div>

        <div className={`demo-service-pill ${serviceHealth?.model_loaded ? "is-good" : "is-muted"}`}>

          <span className="demo-dot" />

          {serviceHealth?.model_loaded ? "YOLO model ready" : "Demo service / model checking"}

        </div>

      </div>



      <div className="demo-safety-note">

        <AlertTriangle size={18} />

        <div>

          <strong>Prototype warning heuristic</strong>

          <p>Skeletons come from YOLO pose estimation. Warning events use torso orientation only; they are not validated fall classifications and may be wrong.</p>

        </div>

      </div>



      {error && (

        <div className="demo-error" role="alert">

          <XCircle size={18} />

          <span>{error}</span>

          <button type="button" onClick={() => setError("")} aria-label="Dismiss error">×</button>

        </div>

      )}



      <div className="demo-video-grid">

        <section className="demo-card">

          <div className="demo-card-title">

            <div className="demo-card-icon"><Upload size={18} /></div>

            <div><h3>Select a video</h3><p>MP4, AVI, MOV, MKV, MPEG, MPG or M4V · max 200 MB</p></div>

          </div>

          <form onSubmit={uploadVideo} className="demo-upload-form">

            <label className="demo-file-picker">

              <Film size={25} />

              <strong>{file ? file.name : "Choose demo video"}</strong>

              <span>{file ? `${(file.size / (1024 * 1024)).toFixed(1)} MB selected` : "Select a file from this computer"}</span>

              <input

                type="file"

                accept="video/mp4,video/avi,video/quicktime,video/x-matroska,video/mpeg,.mp4,.avi,.mov,.mkv,.mpeg,.mpg,.m4v"

                onChange={(event) => chooseFile(event.target.files?.[0] || null)}

              />

            </label>

            <button className="demo-primary-button" type="submit" disabled={!file || uploading || ["queued", "processing"].includes(job?.state)}>

              {uploading ? <LoaderCircle className="demo-spin" size={17} /> : <Video size={17} />}

              {uploading ? "Uploading…" : "Upload and process"}

            </button>

            {job && <button className="demo-secondary-button" type="button" onClick={resetDemo}>Clear demo</button>}

          </form>

          <div className="demo-service-info">

            <span>Demo service</span><strong>{serviceHealth?.status === "ok" ? "Reachable" : "Not confirmed"}</strong>

          </div>

          <div className="demo-service-info">

            <span>Model</span><strong>{serviceHealth?.model_loaded ? "Loaded" : serviceHealth?.model_error || "Checking…"}</strong>

          </div>

          <p className="demo-footnote">Demo videos and events are handled by a separate service. They do not enter the live camera or hardware event history.</p>

        </section>



        <section className="demo-card demo-results-card">

          <div className="demo-card-title">

            <div className="demo-card-icon"><Video size={18} /></div>

            <div><h3>Annotated playback</h3><p>{job?.filename || "Your processed video will appear here."}</p></div>

          </div>



          {job && ["queued", "processing"].includes(job.state) && (

            <div className="demo-progress">

              <div className="demo-progress-label"><span>{job.state === "queued" ? "Waiting to process" : "Running YOLO pose inference"}</span><strong>{job.progress || 0}%</strong></div>

              <div className="demo-progress-track"><div style={{ width: `${job.progress || 0}%` }} /></div>

              <p>{job.frames_processed || 0}{job.frame_count ? ` / ${job.frame_count}` : ""} frames processed. Keep this page open while processing.</p>

            </div>

          )}



          {job?.state === "error" && <div className="demo-empty"><XCircle size={28} /><strong>Processing failed</strong><p>{job.error || error}</p></div>}



          {job?.state === "completed" && (

            <>

              <div className="demo-video-wrap">

                <video
                  ref={videoRef}
                  key={videoUrl}
                  controls
                  playsInline
                  preload="metadata"
                  src={videoUrl}
                  onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)}
                  onLoadedMetadata={(event) => {
                    setCurrentTime(event.currentTarget.currentTime);
                    setPlaybackError("");
                  }}
                  onCanPlay={() => setPlaybackError("")}
                  onError={() => setPlaybackError(
                    "The annotated video could not be played. Check that the demo service is running and that the output MP4 uses a browser-supported codec."
                  )}
                />
                {playbackError && (
                  <div className="demo-error" role="alert">
                    <XCircle size={18} />
                    <span>{playbackError}</span>
                    <button
                      type="button"
                      onClick={() => {
                        setPlaybackError("");
                        if (videoRef.current) {
                          videoRef.current.load();
                          videoRef.current.play().catch(() => {});
                        }
                      }}
                    >
                      Retry playback
                    </button>
                  </div>
                )}

              </div>

              <div className={`demo-warning-state ${currentWarning ? "warning-on" : "warning-off"}`}>

                {currentWarning ? <AlertTriangle size={18} /> : <CheckCircle2 size={18} />}

                <div><strong>{currentWarning ? "POTENTIAL FALL — DEMO HEURISTIC" : "NO ACTIVE DEMO WARNING"}</strong><span>Clip time {formatSeconds(currentTime)} / {formatSeconds(job.duration_seconds || 0)}</span></div>

              </div>

              {activeEvent && (

                <div className="demo-current-event">

                  <strong>{activeEvent.event_type.replaceAll("_", " ")}</strong>

                  <span>{formatSeconds(activeEvent.clip_time_seconds)} · {activeEvent.message}</span>

                </div>

              )}

            </>

          )}



          {!job && <div className="demo-empty"><Film size={30} /><strong>No demo video loaded</strong><p>Choose a clip, then upload it to generate skeleton/keypoint annotations.</p></div>}

        </section>

      </div>



      <section className="demo-card demo-events-card">

        <div className="demo-card-title">

          <div className="demo-card-icon"><AlertTriangle size={18} /></div>

          <div><h3>Demo warning events</h3><p>Separate from live camera and ESP32 event history</p></div>

          <span className="demo-event-count">{events.length}</span>

        </div>

        {!events.length ? (

          <div className="demo-empty compact"><p>Events detected in the processed clip will appear here with their position in the video.</p></div>

        ) : (

          <div className="demo-event-list">

            {events.map((event) => {

              const isWarning = event.event_type === "DEMO_POTENTIAL_FALL";

              return (

                <div className={`demo-event-row ${isWarning ? "event-warning" : ""}`} key={event.event_id}>

                  <span className="demo-event-time">{formatSeconds(event.clip_time_seconds)}</span>

                  <div className="demo-event-copy">

                    <strong>{event.event_type.replaceAll("_", " ")}</strong>

                    <p>{event.message}</p>

                    <small>Frame {event.frame_index} · Recorded {formatDate(event.timestamp)}</small>

                  </div>

                  <span className={`demo-event-tag ${isWarning ? "tag-warning" : "tag-cleared"}`}>{isWarning ? "WARNING" : "CLEARED"}</span>

                </div>

              );

            })}

          </div>

        )}

      </section>

    </section>

  );

}
