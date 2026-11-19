function showToast(message, ok = true) {
  const toast = document.getElementById("toast");
  if (!toast) return;
  toast.textContent = message;
  toast.style.borderColor = ok ? "rgba(16,185,129,.6)" : "rgba(244,63,94,.6)";
  toast.classList.remove("hidden");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.add("hidden"), 3200);
}

function setMode(mode) {
  const badge = document.getElementById("control-mode");
  if (!badge) return;
  badge.textContent = mode;
  badge.className = "badge mode-" + mode;
}

async function postJson(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw new Error("HTTP " + response.status);
  return response.json().catch(() => ({}));
}

async function control(action) {
  try {
    const data = await postJson("/api/control/" + action);
    setMode(data.mode);
    showToast("modo: " + data.mode);
  } catch (error) {
    showToast("error: " + error.message, false);
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function initCharts(data) {
  if (!window.Chart || !data) return;
  const grid = { color: "rgba(148,163,184,0.12)" };
  const ticks = { color: "#94a3b8" };
  const base = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { labels: { color: "#cbd5e1" } } },
    scales: {
      x: { ticks, grid },
      y: { ticks, grid, beginAtZero: true },
    },
  };
  const palette = ["#10b981", "#38bdf8", "#a78bfa", "#fbbf24", "#fb7185", "#34d399", "#60a5fa", "#f472b6", "#facc15", "#2dd4bf"];

  const make = (id, config) => {
    const canvas = document.getElementById(id);
    if (!canvas) return;
    new window.Chart(canvas, config);
  };

  if (data.categories && data.categories.labels.length) {
    make("chart-categories", {
      type: "bar",
      data: {
        labels: data.categories.labels,
        datasets: [{ label: "empresas", data: data.categories.values, backgroundColor: "#10b981", borderRadius: 5 }],
      },
      options: { ...base, indexAxis: "y" },
    });
  }

  if (data.cities && data.cities.labels.length) {
    make("chart-cities", {
      type: "bar",
      data: {
        labels: data.cities.labels,
        datasets: [{ label: "sedes", data: data.cities.values, backgroundColor: "#38bdf8", borderRadius: 5 }],
      },
      options: { ...base, indexAxis: "y" },
    });
  }

  if (data.activity) {
    make("chart-activity", {
      type: "line",
      data: {
        labels: data.activity.labels,
        datasets: [{
          label: "cambios",
          data: data.activity.values,
          borderColor: "#a78bfa",
          backgroundColor: "rgba(167,139,250,.18)",
          fill: true,
          tension: 0.3,
          pointRadius: 3,
        }],
      },
      options: base,
    });
  }

  if (data.coverage) {
    make("chart-coverage", {
      type: "doughnut",
      data: {
        labels: data.coverage.labels,
        datasets: [{
          data: data.coverage.values,
          backgroundColor: ["#10b981", "#38bdf8", "#a78bfa"],
          borderColor: "#0f172a",
          borderWidth: 2,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { position: "bottom", labels: { color: "#cbd5e1" } } },
      },
    });
  }
}

function initLogs() {
  const consoleEl = document.getElementById("log-console");
  if (!consoleEl) return;

  let currentLevel = "ALL";
  const maxLines = 600;

  const append = (event) => {
    const level = (event.level || "INFO").toUpperCase();
    if (currentLevel !== "ALL" && level !== currentLevel) return;
    const line = document.createElement("div");
    line.className = "log-line";
    line.dataset.level = level;
    const time = (event.ts || "").replace("T", " ").slice(0, 19);
    line.innerHTML =
      '<span class="log-time">' + escapeHtml(time) + "</span>" +
      '<span class="log-level log-' + escapeHtml(level) + '">' + escapeHtml(level) + "</span>" +
      '<span class="log-msg">' + escapeHtml(event.message || "") + "</span>" +
      '<span class="log-meta">' + escapeHtml(event.url || event.worker || "") + "</span>";
    consoleEl.appendChild(line);
    while (consoleEl.childElementCount > maxLines) consoleEl.removeChild(consoleEl.firstChild);
    consoleEl.scrollTop = consoleEl.scrollHeight;
  };

  fetch("/api/logs/recent?limit=200")
    .then((response) => response.json())
    .then((items) => items.reverse().forEach(append))
    .catch(() => {});

  const source = new EventSource("/api/logs/stream");
  source.onmessage = (message) => {
    try {
      append(JSON.parse(message.data));
    } catch (error) {
      return;
    }
  };

  document.querySelectorAll("[data-level]").forEach((button) => {
    button.addEventListener("click", () => {
      currentLevel = button.dataset.level;
      consoleEl.querySelectorAll(".log-line").forEach((line) => {
        line.classList.toggle("hidden", currentLevel !== "ALL" && line.dataset.level !== currentLevel);
      });
    });
  });

  const clear = document.getElementById("clear-logs");
  if (clear) clear.addEventListener("click", () => (consoleEl.innerHTML = ""));
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-control]").forEach((button) => {
    button.addEventListener("click", () => control(button.dataset.control));
  });

  document.querySelectorAll("[data-post]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        const data = await postJson(button.dataset.post);
        showToast("ok: " + JSON.stringify(data));
        window.setTimeout(() => window.location.reload(), 600);
      } catch (error) {
        showToast("error: " + error.message, false);
      }
    });
  });

  if (window.__CHARTS__) initCharts(window.__CHARTS__);
  initLogs();

  const mode = document.getElementById("control-mode");
  if (mode && mode.textContent) setMode(mode.textContent.trim());
});
