"use strict"
const commonStyle = document.createElement("link")
commonStyle.rel = "stylesheet"
commonStyle.href = "/common.css"
document.head.append(commonStyle)
const preview = document.querySelector("#terminal-preview")
if (preview) {
  const box = preview.closest(".terminal,details")
  const target = box || preview
  target.remove()
}
const $ = (id) => document.getElementById(id),
  CAPABILITY_KEY = "testing-rack-capability"
const storedCapability = () => {
  try {
    return localStorage.getItem(CAPABILITY_KEY)
  } catch {
    return null
  }
}
const rememberCapability = (value) => {
  try {
    value
      ? localStorage.setItem(CAPABILITY_KEY, value)
      : localStorage.removeItem(CAPABILITY_KEY)
  } catch {}
}
const fragmentCapability = new URLSearchParams(location.hash.slice(1)).get(
  "reservation",
)
const savedCapability = storedCapability()
const ui = {
  state: null,
  capability: savedCapability || fragmentCapability,
  busy: false,
  fallback:
    savedCapability &&
    fragmentCapability &&
    savedCapability !== fragmentCapability
      ? fragmentCapability
      : null,
}
if (!savedCapability && fragmentCapability)
  rememberCapability(fragmentCapability)
function idempotencyKey() {
  if (globalThis.crypto?.getRandomValues) {
    const bytes = new Uint8Array(16)
    crypto.getRandomValues(bytes)
    return [...bytes].map((x) => x.toString(16).padStart(2, "0")).join("")
  }
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}${Math.random().toString(36).slice(2)}`
    .padEnd(16, "0")
    .slice(0, 128)
}
const setText = (id, value) => {
  $(id).textContent = value ?? ""
}
const left = (deadline, now = Date.now() / 1000) => {
  const minutes = Math.max(0, Math.ceil((deadline - now) / 60))
  return minutes < 60
    ? `${minutes} min`
    : minutes % 60
      ? `${Math.floor(minutes / 60)}h ${minutes % 60}m`
      : `${minutes / 60}h`
}
async function api(path, options = {}) {
  const headers = { Accept: "application/json", ...(options.headers || {}) }
  if (ui.capability) headers["X-Testing-Rack-Capability"] = ui.capability
  if (options.body) headers["Content-Type"] = "application/json"
  const response = await fetch(path, { ...options, headers })
  let data
  try {
    data = await response.json()
  } catch {
    throw Error("The rack returned an unreadable response.")
  }
  if (!response.ok) throw Error(data.message || "Request failed.")
  return data
}
function setup() {
  if ($("duration").options.length) return
  for (const n of Array.from(
    { length: ui.state.max_devices },
    (_, index) => index + 1,
  ))
    $("count").add(new Option(n, n))
  for (const minutes of ui.state.durations)
    $("duration").add(
      new Option(
        minutes === 60 ? "1 hour" : `${minutes / 60} hours`,
        minutes,
        minutes === ui.state.default_duration,
        minutes === ui.state.default_duration,
      ),
    )
  $("count").onchange = buttonLabel
  buttonLabel()
}
function buttonLabel() {
  const n = Number($("count").value || 1)
  setText("reserve", `Reserve ${n} device${n === 1 ? "" : "s"}`)
}
function card(device) {
  const el = document.createElement("article")
  el.className = `device ${device.state}`
  const name = document.createElement("b"),
    status = document.createElement("span")
  name.textContent = device.name
  status.textContent =
    device.state === "reserved"
      ? `${device.nickname} · ${left(device.expires_at)}`
      : device.state
  el.append(name, status)
  return el
}
function render() {
  const ready = ui.state.devices.filter((d) => d.state === "ready").length
  setText("availability", `${ready} of ${ui.state.devices.length} ready`)
  $("matrix").replaceChildren(...ui.state.devices.map(card))
}
async function load() {
  try {
    ui.state = await api("/api/state")
    $("offline").hidden = true
    setup()
    render()
    if (!ui.capability) ui.capability = storedCapability()
    if (ui.capability) await refresh()
    else {
      $("reservation").hidden = true
      $("reserve-form").hidden = false
      history.replaceState(null, "", location.pathname)
    }
  } catch (error) {
    $("offline").hidden = false
    setText("offline", `${error.message} Retrying…`)
  }
}
function show(result) {
  rememberCapability(result.capability)
  ui.fallback = null
  history.replaceState(
    null,
    "",
    `${location.pathname}#reservation=${result.capability}`,
  )
  $("reservation").hidden = false
  $("reserve-form").hidden = true
  setText(
    "reservation-title",
    `${result.devices.length} device${result.devices.length === 1 ? "" : "s"} · ${left(result.expires_at)} remaining`,
  )
  setText("reservation-devices", result.devices.join("  ·  "))
  setText("command", result.access_commands.join("\n"))
  setText(
    "copy",
    result.devices.length === 1 ? "Copy command" : "Copy all commands",
  )
}
async function refresh() {
  try {
    show(await api("/api/reservations/current"))
  } catch {
    if (ui.fallback) {
      ui.capability = ui.fallback
      ui.fallback = null
      rememberCapability(ui.capability)
      return refresh()
    }
    ui.capability = null
    rememberCapability(null)
    $("reservation").hidden = true
    $("reserve-form").hidden = false
    history.replaceState(null, "", location.pathname)
  }
}
$("reserve-form").onsubmit = async (event) => {
  event.preventDefault()
  if (ui.busy) return
  ui.busy = true
  $("reserve").disabled = true
  setText("message", "Reserving…")
  const nickname = $("nickname").value.trim()
  try {
    localStorage.setItem("testing-rack-name", nickname)
  } catch {}
  try {
    const result = await api("/api/reservations", {
      method: "POST",
      body: JSON.stringify({
        nickname,
        count: Number($("count").value),
        duration_minutes: Number($("duration").value),
        idempotency_key: idempotencyKey(),
      }),
    })
    ui.capability = result.capability
    rememberCapability(result.capability)
    location.hash = `reservation=${result.capability}`
    show(result)
    setText("message", "")
    await load()
  } catch (error) {
    setText("message", error.message)
  } finally {
    ui.busy = false
    $("reserve").disabled = false
    buttonLabel()
  }
}
$("copy").onclick = async () => {
  const original = $("copy").textContent
  try {
    await navigator.clipboard.writeText($("command").textContent)
    setText("copy", "Copied")
    setTimeout(() => setText("copy", original), 1000)
  } catch {
    setText("message", "Copy failed. Select and copy the command manually.")
  }
}
$("release").onclick = async () => {
  if (!confirm("Release all devices in this reservation?")) return
  try {
    await api("/api/reservations/current", { method: "DELETE" })
    ui.capability = null
    rememberCapability(null)
    history.replaceState(null, "", location.pathname)
    $("reservation").hidden = true
    $("reserve-form").hidden = false
    await load()
  } catch (error) {
    setText("message", error.message)
  }
}
try {
  $("nickname").value = localStorage.getItem("testing-rack-name") || ""
} catch {}
load()
setInterval(load, 5000)
setInterval(() => {
  if (ui.state) render()
}, 1000)
addEventListener("storage", (event) => {
  if (event.key === CAPABILITY_KEY) {
    ui.capability = event.newValue
    if (!event.newValue) {
      $("reservation").hidden = true
      $("reserve-form").hidden = false
      history.replaceState(null, "", location.pathname)
    }
    load()
  }
})
