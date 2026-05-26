/**
 * Interactive swimlane diagram editor with RACI overlay.
 */
(function () {
  const dataEl = document.getElementById("diagram-data");
  if (!dataEl) return;

  const payload = JSON.parse(dataEl.textContent);
  let diagram = payload.diagram;
  const processId = payload.process_id;
  let dimensionSlug = payload.dimension || "ssc_ops";
  let showRaci = true;
  let editMode = false;

  const board = document.getElementById("diagram-board");
  const statusEl = document.getElementById("editor-status");
  const dimSelect = document.getElementById("raci-dimension");
  const raciToggle = document.getElementById("toggle-raci");
  const editToggle = document.getElementById("toggle-edit");

  if (dimSelect) {
    dimSelect.value = dimensionSlug;
    dimSelect.addEventListener("change", () => {
      dimensionSlug = dimSelect.value;
      reloadDiagram();
    });
  }
  if (raciToggle) {
    raciToggle.checked = showRaci;
    raciToggle.addEventListener("change", () => {
      showRaci = raciToggle.checked;
      render();
    });
  }
  if (editToggle) {
    editToggle.addEventListener("change", () => {
      editMode = editToggle.checked;
      board.classList.toggle("diagram-editing", editMode);
      render();
    });
  }

  document.getElementById("btn-add-lane")?.addEventListener("click", addLane);
  document.getElementById("btn-add-step")?.addEventListener("click", addStep);
  document.getElementById("btn-save")?.addEventListener("click", saveDiagram);
  document.getElementById("btn-reset")?.addEventListener("click", resetDiagram);

  async function reloadDiagram() {
    const res = await fetch(
      `/api/processes/${processId}/diagram?dimension=${encodeURIComponent(dimensionSlug)}`
    );
    if (!res.ok) return;
    const data = await res.json();
    diagram = data.diagram;
    render();
  }

  function addLane() {
    const name = prompt("Lane name (role / swimlane):", "New role");
    if (!name) return;
    const id =
      "lane_" +
      name
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "_")
        .replace(/^_|_$/g, "") +
      "_" +
      Date.now();
    diagram.lanes.push({ id, label: name });
    render();
    setStatus("Lane added — save to persist.");
  }

  function addStep() {
    const label = prompt("Activity / step name:", "New step");
    if (!label) return;
    const laneId = diagram.lanes[0]?.id || "lane_default";
    const id = "n_" + Date.now();
    const nodes = diagram.nodes || [];
    const prev = nodes.length ? nodes[nodes.length - 1] : null;
    diagram.nodes = nodes;
    diagram.nodes.push({
      id,
      lane_id: laneId,
      label,
      type: "task",
      activity_id: null,
      raci_overlay: [],
    });
    if (prev) {
      diagram.edges = diagram.edges || [];
      diagram.edges.push({ from: prev.id, to: id, label: "" });
    }
    render();
    setStatus("Step added — save to persist.");
  }

  function renderRaciBadges(overlay) {
    if (!showRaci || !overlay?.length) return "";
    return overlay
      .map((o) => {
        const letters = (o.letters || "").toUpperCase();
        let cls = "raci-badge";
        if (letters.includes("A")) cls += " raci-a";
        else if (letters.includes("R")) cls += " raci-r";
        else if (letters.includes("C")) cls += " raci-c";
        else if (letters.includes("I")) cls += " raci-i";
        return `<span class="${cls}" title="${escapeHtml(o.role_name)}">${escapeHtml(
          letters
        )}<small>${escapeHtml(o.role_name.split(" ")[0])}</small></span>`;
      })
      .join("");
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/"/g, "&quot;");
  }

  function render() {
    board.innerHTML = "";
    (diagram.lanes || []).forEach((lane) => {
      const row = document.createElement("div");
      row.className = "swimlane-row";
      row.dataset.laneId = lane.id;

      const header = document.createElement("div");
      header.className = "swimlane-header";
      if (editMode) {
        header.innerHTML = `<input type="text" class="lane-edit" value="${escapeHtml(
          lane.label
        )}" data-lane-id="${lane.id}">`;
        header.querySelector("input").addEventListener("change", (e) => {
          lane.label = e.target.value;
        });
      } else {
        header.textContent = lane.label;
      }

      const track = document.createElement("div");
      track.className = "swimlane-track";

      (diagram.nodes || [])
        .filter((n) => n.lane_id === lane.id)
        .forEach((node) => {
          const el = document.createElement("div");
          el.className = `swimlane-node swimlane-node--${node.type || "task"}`;
          el.dataset.nodeId = node.id;

          const labelHtml = editMode
            ? `<input type="text" class="node-edit" value="${escapeHtml(node.label)}" data-node-id="${node.id}">`
            : `<span class="node-label">${escapeHtml(node.label)}</span>`;

          const raciHtml = `<div class="raci-overlay">${renderRaciBadges(node.raci_overlay)}</div>`;

          el.innerHTML = labelHtml + raciHtml;

          if (editMode) {
            el.querySelector(".node-edit")?.addEventListener("change", (e) => {
              node.label = e.target.value;
            });
            const tools = document.createElement("div");
            tools.className = "node-tools";
            tools.innerHTML = `
              <select class="node-lane-move" data-node-id="${node.id}" title="Move to lane">
                ${(diagram.lanes || [])
                  .map(
                    (l) =>
                      `<option value="${l.id}" ${l.id === node.lane_id ? "selected" : ""}>${escapeHtml(
                        l.label
                      )}</option>`
                  )
                  .join("")}
              </select>
              <button type="button" class="btn-mini" data-raci-edit="${node.id}">RACI</button>
              <button type="button" class="btn-mini btn-danger" data-del="${node.id}">×</button>
            `;
            tools.querySelector(".node-lane-move").addEventListener("change", (e) => {
              node.lane_id = e.target.value;
              render();
            });
            tools.querySelector(`[data-raci-edit]`).addEventListener("click", () =>
              editNodeRaci(node)
            );
            tools.querySelector(`[data-del]`).addEventListener("click", () => deleteNode(node.id));
            el.appendChild(tools);
          } else if (showRaci && node.raci_overlay?.length) {
            el.title = node.raci_overlay
              .map((o) => `${o.role_name}: ${o.letters}`)
              .join("\n");
          }

          track.appendChild(el);
        });

      row.appendChild(header);
      row.appendChild(track);
      board.appendChild(row);
    });
  }

  function editNodeRaci(node) {
    const roles = payload.roles || [];
    const lines = [`Editing RACI for: ${node.label}`, "Format: ROLE:LETTERS (e.g. Analyst:RAC)"];
    (node.raci_overlay || []).forEach((o) => lines.push(`${o.role_name}:${o.letters}`));
    const input = prompt(lines.join("\n"), "");
    if (input === null) return;
    if (!input.trim()) {
      node.raci_overlay = [];
      render();
      return;
    }
    const overlay = [];
    input.split("\n").forEach((line) => {
      const [rolePart, letters] = line.split(":");
      if (!rolePart) return;
      const roleName = rolePart.trim();
      const role = roles.find((r) => r.name.toLowerCase() === roleName.toLowerCase());
      if (role) {
        overlay.push({
          role_id: role.id,
          role_name: role.name,
          letters: (letters || "R").trim().toUpperCase(),
        });
      }
    });
    node.raci_overlay = overlay;
    render();
    setStatus("RACI updated — save to persist.");
  }

  function deleteNode(nodeId) {
    if (!confirm("Remove this step from the diagram?")) return;
    diagram.nodes = (diagram.nodes || []).filter((n) => n.id !== nodeId);
    diagram.edges = (diagram.edges || []).filter((e) => e.from !== nodeId && e.to !== nodeId);
    render();
  }

  async function saveDiagram() {
    setStatus("Saving…");
    const res = await fetch(`/api/processes/${processId}/diagram`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ diagram, dimension: dimensionSlug }),
    });
    if (res.ok) {
      const data = await res.json();
      diagram = data.diagram;
      setStatus("Saved. Activities and RACI updated.");
      render();
    } else {
      setStatus("Save failed.", true);
    }
  }

  async function resetDiagram() {
    if (!confirm("Rebuild diagram from current activities? Unsaved layout changes will be lost."))
      return;
    const res = await fetch(`/processes/${processId}/diagram/reset`, {
      method: "POST",
      redirect: "follow",
    });
    if (res.redirected) window.location.href = res.url;
    else reloadDiagram();
  }

  function setStatus(msg, isError) {
    if (statusEl) {
      statusEl.textContent = msg;
      statusEl.style.color = isError ? "#b42318" : "#0a2540";
    }
  }

  render();
})();
