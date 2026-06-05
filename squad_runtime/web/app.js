const state = {
  runId: null,
  nodes: [],
  gates: [],
  events: [],
};

const runSelect = document.querySelector("#runSelect");
const refreshButton = document.querySelector("#refreshButton");
const tokenInput = document.querySelector("#tokenInput");
const directiveInput = document.querySelector("#directiveInput");
const sendDirectiveButton = document.querySelector("#sendDirectiveButton");
const dag = document.querySelector("#dag");
const gates = document.querySelector("#gates");
const events = document.querySelector("#events");
const nodeDetail = document.querySelector("#nodeDetail");
const runStatus = document.querySelector("#runStatus");

async function fetchJson(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

async function loadRuns() {
  const data = await fetchJson("/api/runs");
  runSelect.innerHTML = "";
  data.runs.forEach((run) => {
    const option = document.createElement("option");
    option.value = run.id;
    option.textContent = `${run.id} - ${run.goal}`;
    runSelect.append(option);
  });
  if (!state.runId && data.runs.length > 0) {
    state.runId = data.runs[data.runs.length - 1].id;
  }
  runSelect.value = state.runId || "";
  runStatus.textContent = data.runs.find((run) => run.id === state.runId)?.status || "No run";
}

async function loadRunDetail() {
  if (!state.runId) {
    renderEmpty();
    return;
  }
  const [nodeData, gateData, eventData] = await Promise.all([
    fetchJson(`/api/runs/${state.runId}/nodes`),
    fetchJson(`/api/runs/${state.runId}/gates`),
    fetchJson(`/api/runs/${state.runId}/events?limit=80`),
  ]);
  state.nodes = nodeData.nodes;
  state.gates = gateData.gates;
  state.events = eventData.events;
  render();
}

function renderEmpty() {
  dag.textContent = "No run created yet.";
  gates.textContent = "No gates evaluated yet.";
  events.innerHTML = "";
}

function render() {
  dag.innerHTML = "";
  state.nodes.forEach((node) => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = `node status-${node.status}`;
    item.innerHTML = `
      <strong>${escapeHtml(node.title)}</strong>
      <small>${escapeHtml(node.ownerAgentId)} / ${escapeHtml(node.type)}</small>
      <small>Status: ${escapeHtml(node.status)}</small>
    `;
    item.addEventListener("click", () => {
      nodeDetail.textContent = JSON.stringify(node, null, 2);
    });
    dag.append(item);
  });

  gates.innerHTML = "";
  if (state.gates.length === 0) {
    gates.textContent = "No gates evaluated yet.";
  } else {
    state.gates.forEach((gate) => {
      const item = document.createElement("div");
      item.className = `gate status-${gate.status}`;
      item.innerHTML = `
        <strong>${escapeHtml(gate.gateName)}</strong>
        <small>Status: ${escapeHtml(gate.status)}</small>
        <small>${escapeHtml(gate.reason || "")}</small>
      `;
      gates.append(item);
    });
  }

  events.innerHTML = "";
  state.events.slice().reverse().forEach((event) => {
    const item = document.createElement("li");
    item.textContent = `#${event.sequenceNumber} ${event.type}`;
    events.append(item);
  });
}

async function refresh() {
  await loadRuns();
  await loadRunDetail();
}

async function sendDirective() {
  if (!state.runId || !directiveInput.value.trim()) {
    return;
  }
  await fetchJson(`/api/runs/${state.runId}/directives`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Squad-Token": tokenInput.value,
    },
    body: JSON.stringify({ message: directiveInput.value }),
  });
  directiveInput.value = "";
  await refresh();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

runSelect.addEventListener("change", () => {
  state.runId = runSelect.value;
  loadRunDetail().catch((error) => {
    nodeDetail.textContent = error.message;
  });
});
refreshButton.addEventListener("click", () => refresh().catch((error) => {
  nodeDetail.textContent = error.message;
}));
sendDirectiveButton.addEventListener("click", () => sendDirective().catch((error) => {
  nodeDetail.textContent = error.message;
}));

refresh().catch((error) => {
  nodeDetail.textContent = error.message;
});
