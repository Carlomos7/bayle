// Phase 0 development page: every engine call goes through the gateway's `engine_call` command (ADR 0015).
const { invoke, Channel } = window.__TAURI__.core;
const log = (label, value) => {
  const out = document.getElementById("log");
  out.textContent = `${new Date().toLocaleTimeString()} ${label}: ${JSON.stringify(value)}\n` + out.textContent;
};
const call = async (operation, params) => {
  try {
    const result = await invoke("engine_call", { operation, params });
    log(`${operation} ok`, result);
    return result;
  } catch (error) {
    log(`${operation} error`, error);
  }
};

let lastJob = null;
let epoch = 0;
const showStatus = (s) => {
  epoch = s.epoch;
  const down = ["failed", "incompatible", "unavailable"].includes(s.state) || (s.state === "restarting" && s.epoch > 2);
  document.getElementById("recovery").hidden = !down;
  const why = s.problem ? s.problem.message : "";
  document.getElementById("recovery-why").textContent = why || s.state;
  document.getElementById("status").textContent =
    `engine: ${s.state}, epoch ${s.epoch}${s.engineVersion ? `, version ${s.engineVersion}` : ""}` + (why ? ` (${why})` : "");
};

const events = new Channel();
events.onmessage = (m) => {
  if (m.kind === "status") {
    const wasEpoch = epoch;
    showStatus(m.status);
    if (m.status.state === "ready" && lastJob && lastJob.epoch < m.status.epoch && wasEpoch !== m.status.epoch) {
      log("job", `${lastJob.id} was running in epoch ${lastJob.epoch}: interrupted by the restart, outcome unknown`);
    }
  } else if (m.kind === "event") {
    const e = m.event;
    if (e.epoch !== epoch) return; // an older engine's events are gone with it
    log(`event #${e.seq} ${e.type}${e.job_id ? ` (${e.job_id})` : ""}`, e.data);
  }
};
invoke("engine_subscribe", { channel: events }); // the first message is the current status

document.getElementById("health").onclick = () => call("health");
document.getElementById("activity").onclick = () => call("activity");
document.getElementById("job").onclick = async () => {
  const started = await call("saves_back_up", { everything: true });
  if (started) lastJob = { id: started.job_id, epoch };
};
document.getElementById("cancel").onclick = () =>
  lastJob ? call("cancel_job", { job_id: lastJob.id }) : log("cancel", "no job started yet");
document.getElementById("kill").onclick = () => invoke("dev_kill_engine").then(() => log("kill", "asked"));
document.getElementById("refused").onclick = () => call("mods_delete_profile", {});
document.getElementById("escape").onclick = () => call("get_job", { job_id: "../health" });

// Recovery screen (ADR 0016): served by the shell, so it works with the engine down.
window.__TAURI__.app.getVersion().then((v) => (document.getElementById("version").textContent = `app: ${v}`));
const checkUpdates = async () => {
  try {
    const found = await invoke("app_update_check");
    log("update check", found ?? "up to date");
    for (const id of ["install", "install2"]) document.getElementById(id).hidden = !found;
  } catch (error) {
    log("update check error", error);
  }
};
document.getElementById("retry").onclick = () => invoke("engine_restart").then(() => log("retry", "asked"));
document.getElementById("check").onclick = checkUpdates;
document.getElementById("check2").onclick = checkUpdates;
const install = () => invoke("app_update_install").catch((error) => log("update install error", error));
document.getElementById("install").onclick = install;
document.getElementById("install2").onclick = install;
document.getElementById("logs").onclick = () => invoke("app_open_logs").catch((error) => log("open logs error", error));
document.getElementById("report").onclick = () => invoke("app_report_issue").catch((error) => log("report error", error));
