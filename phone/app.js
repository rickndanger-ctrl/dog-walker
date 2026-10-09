"use strict";
const $ = id => document.getElementById(id);
let current = null, csrf = "", busy = false, paired = false, timer;
function message(text, error = false) { $("message").textContent = text; $("message").classList.toggle("error", error); }
function list(id, rows) { const parent = $(id); parent.replaceChildren(); for (const row of rows) { const li = document.createElement("li"); li.textContent = row.text; if (row.className) li.className = row.className; parent.appendChild(li); } }
function buttons() {
  const s = current?.state, connected = current?.connected && !current.external;
  const review = connected && current.review;
  const failed = (s?.evaluation?.checks || []).some(c => !c.pass);
  for (const id of ["approve", "retry", "pause", "resume"]) $(id).disabled = busy || !connected;
  $("approve").hidden = $("retry").hidden = !review;
  $("approve").disabled ||= failed;
  $("pause").hidden = !connected || !current.active;
  $("resume").hidden = !connected || current.active || !s || ["completed", "aborted"].includes(s.status);
}
function render(data) {
  current = data.current; csrf = data.csrf; paired = true;
  $("pair").hidden = true; $("dashboard").hidden = false;
  const s = current.state, job = current.job || s?.job;
  $("connection").textContent = current.connected ? "Connected privately" : "Desktop closed";
  $("headline").textContent = current.review ? "A hand on the leash." : s?.status === "completed" ? "Walk complete." : "Your walk, in view.";
  $("job-name").textContent = s?.name || "No walk selected";
  $("turns").textContent = s ? `${s.turns} model turns` : "";
  const steps = job?.steps || [], history = s?.history || [];
  $("progress").max = Math.max(steps.length, 1); $("progress").value = history.length;
  $("checkpoint-count").textContent = `${history.length} of ${steps.length} checkpoints finished`;
  list("steps", steps.map(step => { const done = history.find(h => h.step === step.id); return {text: `${done ? "✓" : s?.step === step.id ? "●" : "○"}  ${step.title}  ·  ${done ? done.outcome.replaceAll("_", " ") : s?.step === step.id ? "current" : "up next"}`}; }));
  $("status").textContent = current.review ? "Needs your review" : s?.status === "completed" ? "Your results are ready" : s?.status === "paused" ? "Walk paused" : current.active ? "Your model is working" : "Ready for a walk";
  $("reason").textContent = current.reason || s?.reason || (s?.completion ? `Completion: ${s.completion.replaceAll("_", " ")}` : "The desktop owns this walk. Your phone observes and sends checkpoint decisions.");
  $("summary").textContent = s?.result?.summary || (s?.status === "completed" ? s?.previous_result?.summary : "") || "";
  list("checks", (s?.evaluation?.checks || (s?.status === "completed" ? s?.last_evaluation?.checks : []) || []).map(c => ({text: `${c.pass ? "✓" : "✕"}  ${c.id}: ${c.detail}`, className: c.pass ? "pass" : "fail"})));
  $("scope").textContent = s?.allowed_changes ? `Allowed file changes: ${s.allowed_changes.join(", ") || "none (read only)"}` : "This walk has no file allowlist. Its authored checks and protected files still apply.";
  $("evidence").classList.toggle("review", current.review);
  list("runs", data.runs.map(run => ({text: `${run.name} · ${run.status.replaceAll("_", " ")}`})));
  buttons();
}
async function refresh() {
  clearTimeout(timer);
  try {
    const response = await fetch("/api/state", {cache: "no-store", signal: AbortSignal.timeout(10000)});
    if (response.status === 401) { paired = false; current = null; csrf = ""; $("pair").hidden = false; $("dashboard").hidden = true; $("connection").textContent = "Pair your phone"; message("Your computer stays in control. Pair once to monitor and approve."); return; }
    const data = await response.json(); if (!response.ok) throw new Error(data.message || "Connection rejected");
    render(data);
    if (!busy) message(current.connected ? "Live from your computer · checked just now" : current.reason, !current.connected);
  } catch (error) {
    current = null; buttons(); $("connection").textContent = "Disconnected";
    message("Connection lost. Approvals are disabled and never queued offline. Reconnect Tailscale to refresh.", true);
  } finally { timer = setTimeout(refresh, 2500); }
}
$("pair-form").addEventListener("submit", async event => {
  event.preventDefault(); busy = true;
  try {
    const response = await fetch("/api/pair", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({code: $("code").value}), signal: AbortSignal.timeout(10000)});
    const data = await response.json(); if (!response.ok) throw new Error(data.message);
    $("code").value = ""; await refresh();
  } catch (error) { message(error.message, true); }
  finally { busy = false; buttons(); }
});
async function control(action) {
  if (busy || !paired || !current?.connected || !current.state) return;
  const request = {action, run_id: current.state.id, review_id: current.review_id || ""};
  busy = true; buttons(); message("Sending this checkpoint decision…");
  try {
    const response = await fetch("/api/control", {method: "POST", headers: {"Content-Type": "application/json", "X-Dogwalker-CSRF": csrf}, body: JSON.stringify(request), signal: AbortSignal.timeout(14000)});
    const data = await response.json(); if (!response.ok) throw new Error(data.message);
    message(data.message);
  } catch (error) { message(error.message || "Request not confirmed. Refresh before trying again.", true); }
  finally { busy = false; await refresh(); }
}
for (const action of ["approve", "retry", "pause", "resume"]) $(action).addEventListener("click", () => control(action));
document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
refresh();
