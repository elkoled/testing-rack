"use strict"
const preview = document.querySelector("#terminal-preview")
if (preview) {
  const box = preview.closest(".terminal,details")
  const target = box || preview
  target.remove()
}
const $ = (id) => document.getElementById(id),
  TOKEN_KEY = "testing-rack-token",
  LEGACY_KEY = ["testing-rack", "capability"].join("-")
const storedToken = () => {
  try {
    const token = localStorage.getItem(TOKEN_KEY) || localStorage.getItem(LEGACY_KEY)
    if (token) localStorage.setItem(TOKEN_KEY, token)
    localStorage.removeItem(LEGACY_KEY)
    return token
  } catch {
    return null
  }
}
const rememberToken = (value) => {
  try {
    value
      ? localStorage.setItem(TOKEN_KEY, value)
      : localStorage.removeItem(TOKEN_KEY)
  } catch {}
}
const fragmentToken = new URLSearchParams(location.hash.slice(1)).get("token")
const savedToken = storedToken()
const ui = {
  state: null,
  reservation: null,
  token: savedToken || fragmentToken,
  busy: false,
  fallback:
    savedToken && fragmentToken && savedToken !== fragmentToken
      ? fragmentToken
      : null,
}
if (!savedToken && fragmentToken) rememberToken(fragmentToken)
function requestKey() {
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
  if (ui.token) headers.Authorization = `Bearer ${ui.token}`
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
  for (const hours of ui.state.hours)
    $("duration").add(
      new Option(
        hours === 1 ? "1 hour" : `${hours} hours`,
        hours,
        hours === ui.state.default_hours,
        hours === ui.state.default_hours,
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
  const state = device.health === "ready" ? device.state : device.health
  el.className = `device ${state}`
  const name = document.createElement("b"),
    status = document.createElement("span")
  name.textContent = device.name
  status.textContent =
    state === "reserved"
      ? `${device.owner} · ${left(device.expires_at)}`
      : state
  el.append(name, status)
  return el
}
function render() {
  const ready = ui.state.devices.filter((d) => d.state === "ready").length
  const offline = ui.state.devices.filter((d) => d.health === "offline").length
  const reserved = ui.state.devices.filter(
    (d) => d.state === "reserved" && d.health !== "offline",
  ).length
  const parts = [`${reserved} reserved`, `${ready} free`]
  if (offline) parts.push(`${offline} offline`)
  setText(
    "availability",
    parts.join(" · "),
  )
  $("matrix").replaceChildren(...ui.state.devices.map(card))
}
async function load() {
  try {
    ui.state = await api("/api/state")
    setText("rack-name", ui.state.display_name)
    setText(
      "agent-help",
      "Clanker API: /api/agent",
    )
    document.title = ui.state.display_name
    $("offline").hidden = true
    setup()
    render()
    if (!ui.token) ui.token = storedToken()
    if (ui.token) await refresh()
    else {
      $("reservation").hidden = true
      $("reserve-form").hidden = false
      history.replaceState(null, "", location.pathname)
    }
    document.documentElement.classList.remove("loading")
  } catch (error) {
    $("offline").hidden = false
    setText("offline", `${error.message} Retrying…`)
    document.documentElement.classList.remove("loading")
  }
}
function show(result) {
  ui.reservation = result
  if (ui.state) render()
  rememberToken(result.token)
  ui.fallback = null
  history.replaceState(
    null,
    "",
    `${location.pathname}#token=${result.token}`,
  )
  $("reservation").hidden = false
  $("reserve-form").hidden = true
  setText(
    "reservation-title",
    `${result.name} · ${result.devices.length} device${result.devices.length === 1 ? "" : "s"} · ${left(result.expires_at)} remaining`,
  )
  const actions = [...new Set(Object.values(result.actions || {}).flat())]
  setText("command", result.access_commands.join("\n"))
  $("controls").hidden = actions.length === 0
  setText(
    "controls",
    actions.length ? `Append for actions: ${actions.join(" · ")}` : "",
  )
  setText("copy-ssh", "Copy SSH")
}
async function refresh() {
  try {
    show(await api("/api/reservation"))
  } catch {
    if (ui.fallback) {
      ui.token = ui.fallback
      ui.fallback = null
      rememberToken(ui.token)
      return refresh()
    }
    ui.token = null
    ui.reservation = null
    rememberToken(null)
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
  const name = $("name").value.trim()
  try {
    localStorage.setItem("testing-rack-name", name)
  } catch {}
  try {
    const result = await api("/api/reservations", {
      method: "POST",
      body: JSON.stringify({
        name,
        count: Number($("count").value),
        hours: Number($("duration").value),
      }),
      headers: { "Idempotency-Key": requestKey() },
    })
    ui.token = result.token
    rememberToken(result.token)
    location.hash = `token=${result.token}`
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
async function copyText(buttonId, text, sourceId) {
  const original = $(buttonId).textContent
  try {
    if (!navigator.clipboard?.writeText) throw Error("Clipboard API unavailable")
    await navigator.clipboard.writeText(text)
    setText(buttonId, "Copied")
    setTimeout(() => setText(buttonId, original), 1000)
  } catch {
    const field = document.createElement("textarea")
    field.value = text
    field.setAttribute("readonly", "")
    field.style.position = "fixed"
    field.style.opacity = "0"
    document.body.append(field)
    field.select()
    const copied = document.execCommand("copy")
    field.remove()
    if (copied) {
      setText(buttonId, "Copied")
      setText("message", "")
      setTimeout(() => setText(buttonId, original), 1000)
    } else {
      const selection = getSelection()
      const range = document.createRange()
      range.selectNodeContents($(sourceId))
      selection.removeAllRanges()
      selection.addRange(range)
      setText("message", "Text selected. Press Ctrl+C or Command+C.")
    }
  }
}
$("copy-ssh").onclick = () =>
  copyText("copy-ssh", $("command").textContent, "command")
$("release").onclick = async () => {
  if (!confirm("Release all devices in this reservation?")) return
  try {
    await api("/api/reservation", { method: "DELETE" })
    ui.token = null
    ui.reservation = null
    rememberToken(null)
    history.replaceState(null, "", location.pathname)
    $("reservation").hidden = true
    $("reserve-form").hidden = false
    await load()
  } catch (error) {
    setText("message", error.message)
  }
}
try {
  $("name").value = localStorage.getItem("testing-rack-name") || ""
} catch {}
load()
setInterval(load, 5000)
setInterval(() => {
  if (ui.state) render()
}, 1000)
addEventListener("storage", (event) => {
  if (event.key === TOKEN_KEY) {
    ui.token = event.newValue
    if (!event.newValue) {
      $("reservation").hidden = true
      $("reserve-form").hidden = false
      history.replaceState(null, "", location.pathname)
    }
    load()
  }
})
addEventListener("beforeunload", () =>
  document.documentElement.classList.add("loading"),
)
