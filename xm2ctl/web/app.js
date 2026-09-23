"use strict";

const TOKEN = document.querySelector('meta[name="xm2-token"]').content;
const REFRESH_MS = 60_000;

const BUTTONS = {
  left: { label: "Left button" },
  right: { label: "Right button" },
  middle: { label: "Wheel click" },
  back: { label: "Back", note: "Rear side button" },
  forward: { label: "Forward", note: "Front side button" },
  cpi: { label: "CPI button", note: "On the underside" },
  wheel_up: { label: "Wheel up" },
  wheel_down: { label: "Wheel down" },
};

const ACTION_TYPES = {
  mouse: "Mouse button",
  key: "Keyboard key",
  media: "Media key",
  scroll: "Scroll",
  "cpi-loop": "Cycle CPI levels",
  disable: "Do nothing",
};

const MOUSE_VALUES = ["left", "right", "middle", "back", "forward"];

let state = null;      // last state from the mouse
let draft = null;      // settings being edited
let selected = "forward";
let busy = false;

const $ = (id) => document.getElementById(id);
const clone = (value) => JSON.parse(JSON.stringify(value));
const isDirty = () => Boolean(draft) && JSON.stringify(draft) !== JSON.stringify(state.settings);

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

function describeAction(action) {
  const [type, value] = action.split(":");
  if (type === "mouse") return `${value[0].toUpperCase()}${value.slice(1)} click`;
  if (type === "key") return `Key ${value.toUpperCase()}`;
  if (type === "media") return value.replace(/-/g, " ");
  if (type === "scroll") return `Scroll ${value}`;
  if (type === "cpi-loop") return "Cycle CPI levels";
  if (type === "disable") return "Does nothing";
  return action;
}

// --- server ---------------------------------------------------------------

async function load() {
  try {
    const response = await fetch("/api/state");
    state = await response.json();
  } catch (error) {
    state = { connected: false, error: "The xm2ctl service is not running." };
  }
  if (state.connected) draft = clone(state.settings);
  render();
}

async function save() {
  busy = true;
  setMessage("Saving to the mouse…");
  updateSaveBar();
  try {
    const response = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-XM2-Token": TOKEN },
      body: JSON.stringify(draft),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `Request failed (${response.status})`);
    state = result;
    draft = clone(state.settings);
    render();
    setMessage("Saved to the mouse.", "ok");
  } catch (error) {
    setMessage(`Not saved: ${error.message}`, "error");
  } finally {
    busy = false;
    updateSaveBar();
  }
}

// --- rendering ------------------------------------------------------------

function render() {
  const online = state && state.connected;
  $("offline").hidden = online;
  $("main").hidden = !online;
  $("savebar").hidden = !online;
  renderHeader();
  if (!online) {
    $("offline-reason").textContent = state ? state.error : "";
    return;
  }
  renderSensor();
  renderTracking();
  renderPower();
  renderButtons();
  updateSaveBar();
}

function renderHeader() {
  const device = $("device");
  const battery = $("battery");
  if (!state || !state.connected) {
    device.innerHTML = "<span>Not connected</span>";
    battery.hidden = true;
    return;
  }
  const wired = state.connection === "wired";
  const parts = [wired ? "Connected by cable" : "Connected by wireless receiver",
    `Mouse firmware ${state.firmware.mouse}`];
  if (state.firmware.dongle) parts.push(`Receiver firmware ${state.firmware.dongle}`);
  device.innerHTML = parts.map((part) => `<span>${escapeHtml(part)}</span>`).join("");

  battery.hidden = false;
  battery.classList.toggle("low", state.battery <= 20 && !wired);
  $("battery-charge").style.width = `${Math.max(0, Math.min(100, state.battery))}%`;
  $("battery-text").textContent = wired ? `${state.battery} %, charging` : `${state.battery} %`;
}

function segmented(name, options, current, disabled = false) {
  return `<div class="segmented" role="radiogroup">${options.map(([value, label]) => {
    const id = `${name}-${value}`;
    return `<input type="radio" id="${id}" name="${name}" value="${value}"
      ${value === current ? "checked" : ""} ${disabled ? "disabled" : ""}>
      <label for="${id}">${label}</label>`;
  }).join("")}</div>`;
}

function renderSensor() {
  const s = draft;
  const limits = state.limits;
  const wired = state.connection === "wired";
  const levels = s.cpi.map((level, i) => `
    <li class="${i < s.cpi_level_count ? "" : "inactive"}">
      <span class="dot dot-${i + 1}" aria-hidden="true"></span>
      <span class="name">Level ${i + 1}</span>
      <label>${s.xy_split ? "X" : "CPI"}
        <input type="number" data-cpi="${i}" data-axis="x" value="${level.x}"
          min="${limits.cpi_min}" max="${limits.cpi_max}" step="${limits.cpi_step}"></label>
      ${s.xy_split ? `<label>Y
        <input type="number" data-cpi="${i}" data-axis="y" value="${level.y}"
          min="${limits.cpi_min}" max="${limits.cpi_max}" step="${limits.cpi_step}"></label>` : ""}
    </li>`).join("");

  $("sensor").innerHTML = `
    <div class="row"><span>Levels the CPI button cycles through</span>
      ${segmented("levels", [1, 2, 3, 4].map((n) => [n, n]), s.cpi_level_count)}</div>
    <ol class="levels">${levels}</ol>
    <div class="row"><span>Separate X and Y values
      <p class="hint">Not yet verified on this mouse.</p></span>
      <input type="checkbox" class="switch" id="xy-split" ${s.xy_split ? "checked" : ""}></div>
    <div class="row"><span>Lift-off distance</span>
      ${segmented("lod", [[1, "1 mm"], [2, "2 mm"]], s.lod)}</div>
    <div class="row"><span>Polling rate
      ${wired ? '<p class="hint">Fixed at 1000 Hz over the cable. Connect the receiver to change it.</p>' : ""}</span>
      ${segmented("polling", [[1000, "1000 Hz"], [2000, "2000 Hz"], [4000, "4000 Hz"]], s.polling, wired)}</div>`;

  $("sensor").querySelectorAll('input[name="levels"]').forEach((input) =>
    input.addEventListener("change", () => { s.cpi_level_count = Number(input.value); renderSensor(); updateSaveBar(); }));
  $("sensor").querySelectorAll('input[name="lod"]').forEach((input) =>
    input.addEventListener("change", () => { s.lod = Number(input.value); updateSaveBar(); }));
  $("sensor").querySelectorAll('input[name="polling"]').forEach((input) =>
    input.addEventListener("change", () => { s.polling = Number(input.value); updateSaveBar(); }));
  $("xy-split").addEventListener("change", (event) => {
    s.xy_split = event.target.checked;
    if (!s.xy_split) s.cpi.forEach((level) => { level.y = level.x; });
    renderSensor();
    updateSaveBar();
  });
  $("sensor").querySelectorAll("input[data-cpi]").forEach((input) =>
    input.addEventListener("input", () => {
      const level = s.cpi[Number(input.dataset.cpi)];
      const value = Number(input.value);
      level[input.dataset.axis] = value;
      if (!s.xy_split) level.y = value;
      updateSaveBar();
    }));
}

function renderTracking() {
  const toggles = [
    ["angle_snapping", "Angle snapping", "Straightens slightly wobbly lines."],
    ["ripple_control", "Ripple control", "Smooths sensor noise at high CPI."],
    ["motion_sync", "Motion sync", "Aligns sensor data with USB polling."],
    ["slamclick_filter", "Slamclick filter", "Ignores clicks caused by lifting or slamming the mouse."],
    ["jitter_filter", "Motion jitter filter", "Suppresses tiny movements while clicking."],
    ["lift_off_led", "LED on lift-off", "Lights the LED when the mouse is lifted."],
  ];
  $("tracking").innerHTML = toggles.map(([key, label, hint]) => `
    <div class="row"><span>${label}<p class="hint">${hint}</p></span>
      <input type="checkbox" class="switch" data-toggle="${key}" aria-label="${label}"
        ${draft[key] ? "checked" : ""}></div>`).join("");
  $("tracking").querySelectorAll("[data-toggle]").forEach((input) =>
    input.addEventListener("change", () => { draft[input.dataset.toggle] = input.checked; updateSaveBar(); }));
}

function renderPower() {
  const limits = state.limits;
  const timers = [["power_saving", "Power saving"], ["deep_sleep", "Deep sleep"]];
  $("power").innerHTML = timers.map(([key, label]) => `
    <div class="row timer"><span>${label}</span>
      <label class="minutes">after
        <input type="number" data-timer="${key}" value="${draft[key].minutes}"
          min="${limits.timer_min}" max="${limits.timer_max}" aria-label="${label} minutes"
          ${draft[key].enabled ? "" : "disabled"}> min</label>
      <input type="checkbox" class="switch" data-timer-switch="${key}" aria-label="${label}"
        ${draft[key].enabled ? "checked" : ""}></div>`).join("");
  $("power").querySelectorAll("[data-timer]").forEach((input) =>
    input.addEventListener("input", () => { draft[input.dataset.timer].minutes = Number(input.value); updateSaveBar(); }));
  $("power").querySelectorAll("[data-timer-switch]").forEach((input) =>
    input.addEventListener("change", () => {
      draft[input.dataset.timerSwitch].enabled = input.checked;
      renderPower();
      updateSaveBar();
    }));
}

function renderButtons() {
  document.querySelectorAll(".schematic [data-button]").forEach((element) => {
    element.classList.toggle("selected", element.dataset.button === selected);
    element.onclick = () => selectButton(element.dataset.button);
  });

  $("legend").innerHTML = Object.entries(BUTTONS).map(([key, info]) => `
    <li><button type="button" data-select="${key}" aria-pressed="${key === selected}">
      <span>${info.label}</span>
      <span class="action">${escapeHtml(describeAction(draft.buttons[key].action))}</span>
    </button></li>`).join("");
  $("legend").querySelectorAll("[data-select]").forEach((button) =>
    button.addEventListener("click", () => selectButton(button.dataset.select)));

  renderEditor();
}

function selectButton(key) {
  selected = key;
  renderButtons();
}

function renderEditor() {
  const key = selected;
  const info = BUTTONS[key];
  const entry = draft.buttons[key];
  const limits = state.limits;
  const [type, value = ""] = entry.action.split(":");
  const lockedByHandedness = key === "left" || (key === "right" && draft.left_handed);
  let html = `<h3>${info.label}</h3>${info.note ? `<p class="hint">${info.note}</p>` : ""}`;

  if (key === "left" || key === "right") {
    html += `<div class="row"><span>Left-handed mode<p class="hint">Swaps the left and right button.</p></span>
      <input type="checkbox" class="switch" id="left-handed" ${draft.left_handed ? "checked" : ""}></div>`;
  }

  if (lockedByHandedness) {
    html += `<p class="hint">This button always clicks. Only left-handed mode changes it.</p>`;
  } else {
    html += `<label class="row"><span>Action</span><select id="action-type">${Object.entries(ACTION_TYPES)
      .map(([k, label]) => `<option value="${k}" ${k === type ? "selected" : ""}>${label}</option>`).join("")}</select></label>`;
    if (type === "mouse") {
      html += `<label class="row"><span>Button</span><select id="action-value">${MOUSE_VALUES
        .map((v) => `<option value="${v}" ${v === value ? "selected" : ""}>${v}</option>`).join("")}</select></label>`;
    } else if (type === "media") {
      html += `<label class="row"><span>Media key</span><select id="action-value">${limits.media
        .map((v) => `<option value="${v}" ${v === value ? "selected" : ""}>${v.replace(/-/g, " ")}</option>`).join("")}</select></label>`;
    } else if (type === "scroll") {
      html += `<label class="row"><span>Direction</span><select id="action-value">${["up", "down"]
        .map((v) => `<option value="${v}" ${v === value ? "selected" : ""}>${v}</option>`).join("")}</select></label>`;
    } else if (type === "key") {
      html += `<label class="row"><span>Key<p class="hint">For example f5, a, ctrl+c or ctrl+shift+esc</p></span>
        <input type="text" id="action-value" value="${escapeHtml(value)}" spellcheck="false" autocomplete="off"></label>
        ${state.keyboard_fix === true
          ? '<p class="hint">The keyboard fix (HID-BPF) is active, keyboard keys work.</p>'
          : `<p class="hint warning">Linux ignores keyboard keys sent by this mouse because of a bug in its
        firmware (1.10). Install the HID-BPF fix from the repository, or bind keys in your game or with
        a remapping tool instead. Media keys and mouse buttons always work.</p>`}`;
    }
  }

  if (entry.click !== null) {
    const spdt = limits.spdt_buttons.includes(key);
    const mode = typeof entry.click === "string" ? entry.click : "debounce";
    if (spdt) {
      html += `<label class="row"><span>Click detection<p class="hint">GX modes use the switch's second contact.</p></span>
        <select id="click-mode">
          <option value="debounce" ${mode === "debounce" ? "selected" : ""}>Debounce time</option>
          <option value="safe" ${mode === "safe" ? "selected" : ""}>GX safe</option>
          <option value="speed" ${mode === "speed" ? "selected" : ""}>GX speed</option>
        </select></label>`;
    }
    if (mode === "debounce") {
      html += `<label class="row"><span>Debounce time<p class="hint">Higher values prevent double clicks.</p></span>
        <span><input type="number" id="debounce" value="${entry.click}" min="0" max="${limits.debounce_max}"> ms</span></label>`;
    }
  }

  $("editor").innerHTML = html;

  const leftHanded = $("left-handed");
  if (leftHanded) leftHanded.addEventListener("change", () => {
    draft.left_handed = leftHanded.checked;
    draft.buttons.left.action = leftHanded.checked ? "mouse:right" : "mouse:left";
    draft.buttons.right.action = leftHanded.checked ? "mouse:left" : "mouse:right";
    renderButtons();
    updateSaveBar();
  });

  const typeSelect = $("action-type");
  if (typeSelect) typeSelect.addEventListener("change", () => {
    const defaults = { mouse: "mouse:left", key: "key:f5", media: `media:${limits.media[0]}`,
      scroll: "scroll:up", "cpi-loop": "cpi-loop", disable: "disable" };
    entry.action = defaults[typeSelect.value];
    renderButtons();
    updateSaveBar();
  });

  const valueInput = $("action-value");
  if (valueInput) valueInput.addEventListener(valueInput.tagName === "SELECT" ? "change" : "input", () => {
    entry.action = `${type}:${valueInput.value.trim().toLowerCase()}`;
    const legendAction = document.querySelector(`[data-select="${key}"] .action`);
    if (legendAction) legendAction.textContent = describeAction(entry.action);
    updateSaveBar();
  });

  const clickMode = $("click-mode");
  if (clickMode) clickMode.addEventListener("change", () => {
    entry.click = clickMode.value === "debounce" ? 8 : clickMode.value;
    renderEditor();
    updateSaveBar();
  });

  const debounce = $("debounce");
  if (debounce) debounce.addEventListener("input", () => { entry.click = Number(debounce.value); updateSaveBar(); });
}

// --- save bar -------------------------------------------------------------

function setMessage(text, kind = "") {
  const message = $("message");
  message.textContent = text;
  message.className = kind;
}

function updateSaveBar() {
  const dirty = isDirty();
  $("save").disabled = busy || !dirty;
  $("discard").disabled = busy || !dirty;
  if (!busy && dirty) setMessage("Unsaved changes");
  if (!busy && !dirty && $("message").className === "") setMessage("All settings are on the mouse.");
}

$("save").addEventListener("click", save);
$("discard").addEventListener("click", () => {
  draft = clone(state.settings);
  render();
  setMessage("Changes discarded.");
});
$("retry").addEventListener("click", load);

setInterval(() => { if (!busy && !isDirty()) load(); }, REFRESH_MS);
load();
