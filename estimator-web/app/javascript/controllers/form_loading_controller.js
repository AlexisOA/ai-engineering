import { Controller } from "@hotwired/stimulus"

// Connects to data-controller="form-loading"
// Submits the form via fetch to the FastAPI streaming endpoint, parses the
// Server-Sent Events stream manually (status, token, complete, error) and
// renders tokens live into the output area. Falls back to a clean error
// message if the network fails. The traditional POST to /estimation remains
// available when JS is disabled or if `streamUrlValue` is empty.
export default class extends Controller {
  static targets = [
    "submit", "label", "spinner",
    "statusPanel", "phaseText", "timer",
    "outputContainer", "output", "badge",
    "errorPanel", "errorText",
    "formBody"
  ]
  static values = { streamUrl: String }

  PHASES = {
    preparing:   "Preparando prompt y contexto…",
    calling_llm: "Esperando primeros tokens del LLM…",
    receiving:   "Recibiendo tokens en vivo…",
    finalizing:  "Estimación completada"
  }

  connect() {
    this.abortController = null
  }

  disconnect() {
    this.stopTimer()
    if (this.abortController) this.abortController.abort()
  }

  // ------------------------------------------------------------------
  // submit handler
  // ------------------------------------------------------------------

  async start(event) {
    if (!this.streamUrlValue) return  // no JS streaming → let the form POST normally
    event.preventDefault()

    if (!this.validate()) return

    this.markBusy()
    this.startTimer()
    this.openOutput()
    this.clearError()

    try {
      await this.streamEstimation()
    } catch (err) {
      if (err.name !== "AbortError") this.showError(err.message || String(err))
    } finally {
      this.markIdle()
      this.stopTimer()
    }
  }

  reset() {
    if (this.hasFormBodyTarget) this.formBodyTarget.classList.remove("hidden")
    if (this.hasOutputContainerTarget) this.outputContainerTarget.classList.add("hidden")
    if (this.hasOutputTarget) this.outputTarget.textContent = ""
    this.clearError()
    this.markIdle()
  }

  // ------------------------------------------------------------------
  // streaming
  // ------------------------------------------------------------------

  async streamEstimation() {
    const payload = this.collectPayload()
    this.abortController = new AbortController()

    const response = await fetch(this.streamUrlValue, {
      method: "POST",
      mode: "cors",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        "Accept": "text/event-stream"
      },
      body: JSON.stringify(payload),
      signal: this.abortController.signal
    })

    if (!response.ok) {
      let detail = `HTTP ${response.status}`
      try { detail = (await response.json()).detail || detail } catch (_) {}
      throw new Error(`AI service unavailable: ${detail}`)
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ""

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let sep
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, sep)
        buffer = buffer.slice(sep + 2)
        this.handleFrame(frame)
      }
    }
  }

  handleFrame(frame) {
    if (!frame.trim()) return
    let eventType = "message"
    let dataRaw = ""
    for (const line of frame.split("\n")) {
      if (line.startsWith("event: ")) eventType = line.slice(7).trim()
      else if (line.startsWith("data: ")) dataRaw += line.slice(6)
    }
    let data = {}
    try { data = JSON.parse(dataRaw || "{}") } catch (_) {}

    switch (eventType) {
      case "status":
        this.setPhase(data.phase)
        if (data.prompt_version && this.hasBadgeTarget) {
          this.badgeTarget.textContent = `prompt ${data.prompt_version}`
        }
        break
      case "token":
        if (data.chunk) {
          this.outputTarget.textContent += data.chunk
          this.setPhase("receiving")
          this.outputTarget.scrollIntoView({ block: "end", behavior: "smooth" })
        }
        break
      case "complete":
        this.setPhase("finalizing")
        if (data.prompt_version && this.hasBadgeTarget) {
          this.badgeTarget.textContent = `prompt ${data.prompt_version}`
        }
        if (this.hasStatusPanelTarget) this.statusPanelTarget.classList.add("hidden")
        break
      case "error":
        throw new Error(data.message || "Stream failed")
    }
  }

  // ------------------------------------------------------------------
  // helpers
  // ------------------------------------------------------------------

  collectPayload() {
    const fd = new FormData(this.element)
    return {
      description:   fd.get("estimation_request[description]") || "",
      project_type:  fd.get("estimation_request[project_type]") || "",
      detail_level:  fd.get("estimation_request[detail_level]") || "",
      output_format: fd.get("estimation_request[output_format]") || ""
    }
  }

  validate() {
    const payload = this.collectPayload()
    if (payload.description.length < 20 || payload.description.length > 80000) {
      this.showError("Description must be between 20 and 80,000 characters.")
      return false
    }
    if (!payload.project_type) {
      this.showError("Please pick a project type.")
      return false
    }
    return true
  }

  markBusy() {
    this.submitTarget.disabled = true
    this.submitTarget.classList.add("cursor-not-allowed", "opacity-70")
    if (this.hasLabelTarget) this.labelTarget.textContent = "Generating…"
    if (this.hasSpinnerTarget) this.spinnerTarget.classList.remove("hidden")
    if (this.hasStatusPanelTarget) this.statusPanelTarget.classList.remove("hidden")
  }

  markIdle() {
    this.submitTarget.disabled = false
    this.submitTarget.classList.remove("cursor-not-allowed", "opacity-70")
    if (this.hasLabelTarget) this.labelTarget.textContent = "Generate estimation"
    if (this.hasSpinnerTarget) this.spinnerTarget.classList.add("hidden")
    if (this.hasStatusPanelTarget) this.statusPanelTarget.classList.add("hidden")
  }

  openOutput() {
    if (this.hasFormBodyTarget) this.formBodyTarget.classList.add("hidden")
    if (this.hasOutputContainerTarget) this.outputContainerTarget.classList.remove("hidden")
    if (this.hasOutputTarget) this.outputTarget.textContent = ""
  }

  setPhase(phaseKey) {
    if (!this.hasPhaseTextTarget) return
    const text = this.PHASES[phaseKey] || phaseKey
    if (text && this.phaseTextTarget.textContent !== text) {
      this.phaseTextTarget.textContent = text
    }
  }

  showError(message) {
    if (this.hasErrorPanelTarget) {
      this.errorPanelTarget.classList.remove("hidden")
      if (this.hasErrorTextTarget) this.errorTextTarget.textContent = message
    }
    if (this.hasFormBodyTarget) this.formBodyTarget.classList.remove("hidden")
    if (this.hasOutputContainerTarget) this.outputContainerTarget.classList.add("hidden")
  }

  clearError() {
    if (this.hasErrorPanelTarget) this.errorPanelTarget.classList.add("hidden")
  }

  startTimer() {
    this.startedAt = Date.now()
    this.tick()
    this.interval = setInterval(() => this.tick(), 500)
  }

  stopTimer() {
    if (this.interval) {
      clearInterval(this.interval)
      this.interval = null
    }
  }

  tick() {
    if (!this.hasTimerTarget) return
    const elapsed = Math.floor((Date.now() - this.startedAt) / 1000)
    const mm = String(Math.floor(elapsed / 60)).padStart(2, "0")
    const ss = String(elapsed % 60).padStart(2, "0")
    this.timerTarget.textContent = `${mm}:${ss}`
  }
}
