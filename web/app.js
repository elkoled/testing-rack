"use strict"
const $ = (id) => document.getElementById(id),
  TOKEN_KEY = "testing-rack-token"
const storedToken = () => {
  try {
    return localStorage.getItem(TOKEN_KEY)
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
  selected: new Set(),
  token: fragmentToken || savedToken,
  busy: false,
}
if (fragmentToken) rememberToken(fragmentToken)
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
function buttonLabel() {
  $("reserve").disabled = ui.selected.size === 0
}
function readyNames() {
  return ui.state.devices
    .filter((device) => device.state === "ready" && device.health === "ready")
    .map((device) => device.name)
}
function selectCount(count, rerender = true) {
  const ready = readyNames()
  ui.selected = new Set([...ui.selected].filter((name) => ready.includes(name)))
  while (ui.selected.size > count) ui.selected.delete([...ui.selected].at(-1))
  for (const name of ready) {
    if (ui.selected.size >= count) break
    ui.selected.add(name)
  }
  $("count").value = String(ui.selected.size || count)
  buttonLabel()
  if (rerender) render()
}
function card(device) {
  const el = document.createElement("button")
  el.type = "button"
  const state = device.health === "ready" ? device.state : device.health
  const selected = state === "ready" && ui.selected.has(device.name)
  el.className = `device ${selected ? "selected" : state}`
  el.disabled = state !== "ready" || ui.reservation !== null
  const name = document.createElement("b"),
    status = document.createElement("span")
  name.textContent = device.name
  status.textContent =
    selected ? "selected" : state === "reserved" ? device.owner : state
  el.append(name, status)
  el.onclick = () => {
    if (ui.selected.has(device.name)) {
      ui.selected.delete(device.name)
    } else if (ui.selected.size < ui.state.max_devices) {
      ui.selected.add(device.name)
    }
    $("count").value = String(ui.selected.size)
    buttonLabel()
    render()
  }
  return el
}
function render() {
  if (!ui.reservation) {
    const available = readyNames().length
    const limit = Math.min(available, ui.state.max_devices)
    const desired = $("count").options.length
      ? Number($("count").value)
      : Math.min(1, limit)
    if ($("count").options.length !== limit + 1)
      $("count").replaceChildren(
        ...Array.from(
          { length: limit + 1 },
          (_, index) => new Option(index, index),
        ),
      )
    $("count").value = String(Math.min(desired, limit))
    selectCount(Number($("count").value), false)
  }
  const ready = ui.state.devices.filter((d) => d.state === "ready").length
  const offline = ui.state.devices.filter((d) => d.health === "offline").length
  const reserved = ui.state.devices.filter(
    (d) => d.state === "reserved" && d.health !== "offline",
  ).length
  const reservedCount = document.createElement("b")
  const freeCount = document.createElement("b")
  reservedCount.className = "reserved-count"
  freeCount.className = "free-count"
  reservedCount.textContent = reserved
  freeCount.textContent = ready
  const status = [reservedCount, " RESERVED · ", freeCount, " FREE"]
  if (offline) status.push(` · ${offline} OFFLINE`)
  $("availability").replaceChildren(...status)
  $("matrix").replaceChildren(...ui.state.devices.map(card))
}
async function load() {
  try {
    ui.state = await api("/api/state")
    setText("rack-name", ui.state.display_name)
    document.title = ui.state.display_name
    $("offline").hidden = true
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
  history.replaceState(
    null,
    "",
    `${location.pathname}#token=${result.token}`,
  )
  $("reservation").hidden = false
  $("reserve-form").hidden = true
  setText(
    "reservation-title",
    `${result.name} · ${result.devices.length} device${result.devices.length === 1 ? "" : "s"}`,
  )
  const actions = [...new Set(Object.values(result.actions || {}).flat())]
  // The selector is a remote command, so SSH needs -t for an interactive UI login.
  setText(
    "command",
    result.access_commands
      .map((command) => command.replace(/^ssh /, "ssh -t "))
      .join("\n"),
  )
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
        devices: [...ui.selected],
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
    ui.selected.clear()
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
$("count").onchange = () => selectCount(Number($("count").value))
load()
setInterval(load, 5000)
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
