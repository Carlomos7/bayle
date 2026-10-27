// Phase 0 development page: every engine call goes through the gateway's `engine_call` command (ADR 0015).
const { invoke, Channel } = window.__TAURI__.core;
const log = (label, value) => {
  const out = document.getElementById("log");
  out.textContent = `${new Date().toLocaleTimeString()} ${label}: ${JSON.stringify(value)}\n` + out.textContent;
};
const call = async (operation, args = {}) => {
  try {
    const result = await invoke("engine_call", { operation, ...args });
    log(`${operation} ok`, result);
    return result;
  } catch (error) {
    log(`${operation} error`, error);
  }
};

let lastJob = null;
let generation = 0;
const showStatus = (s) => {
  generation = s.generation;
  document.getElementById("status").textContent =
    `engine: ${s.state}, generation ${s.generation}${s.engine_version ? `, version ${s.engine_version}` : ""}` +
    (s.message ? ` (${s.message})` : "");
};

const events = new Channel();
events.onmessage = (e) => {
  if (e.kind === "engine") {
    showStatus(e);
    if (e.state === "ready" && lastJob && lastJob.generation < e.generation) {
      log("job", `${lastJob.id} was running in generation ${lastJob.generation}: interrupted by the restart, outcome unknown`);
    }
  } else if (e.kind === "event") {
    if (e.generation !== generation) return; // an older engine's events are gone with it
    log(`event #${e.seq} ${e.type}${e.job_id ? ` (${e.job_id})` : ""}`, e.data);
  } else {
    log("lagged", `${e.missed} events missed: reload what is shown`);
  }
};
invoke("engine_events", { channel: events });
invoke("engine_status").then(showStatus);

document.getElementById("health").onclick = () => call("health");
document.getElementById("activity").onclick = () => call("activity");
document.getElementById("job").onclick = async () => {
  const started = await call("saves_back_up", { body: { everything: true } });
  if (started) lastJob = { id: started.job_id, generation };
};
document.getElementById("cancel").onclick = () =>
  lastJob ? call("cancel_job", { path: { job_id: lastJob.id } }) : log("cancel", "no job started yet");
document.getElementById("kill").onclick = () => invoke("dev_kill_engine").then(() => log("kill", "asked"));
document.getElementById("refused").onclick = () => call("mods_delete_profile", { body: {} });
document.getElementById("escape").onclick = () => call("get_job", { path: { job_id: "../health" } });
