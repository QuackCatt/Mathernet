(() => {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";

  function svgElement(name, attributes = {}) {
    const element = document.createElementNS(SVG_NS, name);
    for (const [key, value] of Object.entries(attributes)) {
      element.setAttribute(key, String(value));
    }
    return element;
  }

  function hash(value) {
    let output = 2166136261;
    for (let index = 0; index < value.length; index += 1) {
      output ^= value.charCodeAt(index);
      output = Math.imul(output, 16777619);
    }
    return output >>> 0;
  }

  function labelLines(value) {
    const words = String(value || "").trim().split(/\s+/);
    const lines = [""];
    for (const word of words) {
      const current = lines[lines.length - 1];
      const candidate = current ? `${current} ${word}` : word;
      if (candidate.length <= 25 || !current) {
        lines[lines.length - 1] = candidate;
      } else if (lines.length === 1) {
        lines.push(word);
      } else {
        lines[1] = `${lines[1]} ${word}`;
      }
    }
    if (lines.length > 2) {
      lines.length = 2;
      lines[1] = `${lines[1].slice(0, 23).trim()}…`;
    } else if (lines[1]?.length > 25) {
      lines[1] = `${lines[1].slice(0, 24).trim()}…`;
    }
    return lines;
  }

  const NODE_RADII = [8, 10, 12, 15, 18, 21, 24, 26, 28, 30];

  function nodeRadiusForDegree(degree) {
    return NODE_RADII[Math.min(NODE_RADII.length - 1, Math.max(0, degree))];
  }

  class FormulaGraph {
    constructor() {
      this.stage = document.querySelector("#graph-stage");
      this.svg = document.querySelector("#graph-canvas");
      this.viewport = document.querySelector("#graph-viewport");
      this.edgeLayer = document.querySelector("#edge-layer");
      this.nodeLayer = document.querySelector("#node-layer");
      this.empty = document.querySelector("#graph-empty");
      this.description = document.querySelector("#graph-description");
      this.nodes = [];
      this.links = [];
      this.positions = new Map();
      this.selectedId = null;
      this.hoveredId = null;
      this.onSelect = null;
      this.onClearSelection = null;
      this.width = 900;
      this.height = 540;
      this.transform = { x: 0, y: 0, scale: 1 };
      this.animationFrame = 0;
      this.simulationFrame = 0;
      this.draggedNode = null;
      this.dragMoved = false;
      this.mergeCandidateId = null;
      this.cutMode = false;
      this.cutPointer = null;
      this.cutEdgeId = null;
      this.cutDragMoved = false;
      this.inspectMode = false;
      this.inspectPointer = null;
      this.inspectEdgeId = null;
      this.inspectDragMoved = false;
      this.onCreateRelationship = null;
      this.onCutRelationship = null;
      this.onInspectRelationship = null;
      this.panStart = null;
      this.reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      this.resizeObserver = new ResizeObserver(() => this.resize());
      this.resizeObserver.observe(this.stage);
      this.bindEvents();
      this.resize();
    }

    render(
      graph,
      {
        onSelect,
        selectedId,
        onCreateRelationship,
        onCutRelationship,
        onInspectRelationship,
        onClearSelection,
      } = {},
    ) {
      this.cancelAnimation();
      this.onSelect = onSelect || null;
      this.onCreateRelationship = onCreateRelationship || null;
      this.onCutRelationship = onCutRelationship || null;
      this.onInspectRelationship = onInspectRelationship || null;
      this.onClearSelection = onClearSelection || null;
      this.selectedId = selectedId || null;
      if (!graph || !graph.nodes.length) {
        this.clear();
        return;
      }

      const previousPositions = this.positions;
      const nodeById = new Map(graph.nodes.map((node) => [node.id, { ...node }]));
      this.nodes = [...nodeById.values()];
      this.links = graph.edges
        .map((edge) => ({
          ...edge,
          source: nodeById.get(edge.source_id),
          target: nodeById.get(edge.target_id),
        }))
        .filter((link) => link.source && link.target);
      const degrees = new Map(this.nodes.map((node) => [node.id, 0]));
      for (const link of this.links) {
        degrees.set(link.source_id, (degrees.get(link.source_id) || 0) + 1);
        degrees.set(link.target_id, (degrees.get(link.target_id) || 0) + 1);
      }
      for (const node of this.nodes) {
        node.degree = degrees.get(node.id) || 0;
        node.radius = nodeRadiusForDegree(node.degree);
      }
      this.positions = new Map();
      this.initializePositions(previousPositions);
      this.buildLayers();
      this.empty.hidden = true;
      this.updateDescription();
      this.updateHighlight();
      this.updatePositions();
      this.fit();
      this.simulate(() => this.fit());
    }

    clear() {
      this.cancelAnimation();
      this.nodes = [];
      this.links = [];
      this.positions = new Map();
      this.edgeLayer.replaceChildren();
      this.nodeLayer.replaceChildren();
      this.mergeCandidateId = null;
      this.cutEdgeId = null;
      this.inspectEdgeId = null;
      this.empty.hidden = false;
      this.description.textContent = "This mind map has no formula cards yet.";
    }

    initializePositions(previousPositions) {
      const centerX = this.width / 2;
      const centerY = this.height / 2;
      const radius = Math.min(this.width, this.height) * 0.28;
      const ordered = [...this.nodes].sort((a, b) => {
        if (a.id === this.selectedId) return -1;
        if (b.id === this.selectedId) return 1;
        return a.name.localeCompare(b.name);
      });

      ordered.forEach((node, index) => {
        const preserved = previousPositions.get(node.id);
        if (preserved) {
          this.positions.set(node.id, { ...preserved, vx: 0, vy: 0 });
          return;
        }
        const angle =
          ordered.length === 1
            ? -Math.PI / 2
            : -Math.PI / 2 + (Math.PI * 2 * index) / ordered.length;
        const variation = ((hash(node.id) % 100) / 100 - 0.5) * 44;
        this.positions.set(node.id, {
          x: centerX + Math.cos(angle) * (radius + variation),
          y: centerY + Math.sin(angle) * (radius * 0.72 + variation),
          vx: 0,
          vy: 0,
        });
      });
    }

    buildLayers() {
      this.edgeLayer.replaceChildren();
      this.nodeLayer.replaceChildren();

      for (const link of this.links) {
        const hitArea = svgElement("path", {
          class: "graph-edge-hit",
          "data-edge-id": link.id,
          "data-source-id": link.source_id,
          "data-target-id": link.target_id,
        });
        hitArea.addEventListener("click", () => {
          if (this.cutMode) this.onCutRelationship?.({ edge: link });
          else if (this.inspectMode) this.onInspectRelationship?.({ edge: link });
        });
        const isUnconfirmedManualRelationship =
          link.created_by === "manual" && link.evidence_status !== "supported";
        const path = svgElement("path", {
          class: `graph-edge ${isUnconfirmedManualRelationship ? "is-unverified" : "is-supported"}`,
          "data-edge-id": link.id,
          "data-source-id": link.source_id,
          "data-target-id": link.target_id,
          tabindex: "0",
          role: "button",
          "aria-label": `Cut relationship from ${link.source.name} to ${link.target.name}`,
        });
        path.addEventListener("click", () => {
          if (this.cutMode) this.onCutRelationship?.({ edge: link });
          else if (this.inspectMode) this.onInspectRelationship?.({ edge: link });
        });
        path.addEventListener("keydown", (event) => {
          if (!["Enter", " "].includes(event.key)) return;
          event.preventDefault();
          if (this.cutMode) this.onCutRelationship?.({ edge: link });
          else this.onInspectRelationship?.({ edge: link });
        });
        link.element = path;
        link.hitElement = hitArea;
        this.edgeLayer.append(path, hitArea);
      }

      for (const node of this.nodes) {
        node.element = this.createNodeElement(node);
        this.nodeLayer.append(node.element);
      }
    }

    createNodeElement(node) {
      const group = svgElement("g", {
        class: `graph-node status-${node.status}`,
        "data-node-id": node.id,
        role: "button",
        tabindex: "0",
        "aria-label": `Inspect ${node.name}`,
      });
      const radius = node.radius || nodeRadiusForDegree(0);
      const hitArea = svgElement("circle", { class: "node-hit", r: radius + 20 });
      const halo = svgElement("circle", { class: "node-halo", r: radius + 7 });
      const surface = svgElement("circle", {
        class: "node-surface",
        r: radius,
      });
      const label = svgElement("text", {
        class: "node-name",
        x: 0,
        y: radius + 21,
        "text-anchor": "middle",
      });
      labelLines(node.name).forEach((line, index) => {
        const row = svgElement("tspan", {
          x: 0,
          y: index === 0 ? radius + 21 : radius + 39,
        });
        row.textContent = line;
        label.append(row);
      });
      group.append(hitArea, halo, surface, label);

      group.addEventListener("pointerenter", () => {
        this.hoveredId = node.id;
        this.updateHighlight();
      });
      group.addEventListener("pointerleave", () => {
        if (this.hoveredId === node.id) this.hoveredId = null;
        this.updateHighlight();
      });
      group.addEventListener("focus", () => {
        this.hoveredId = node.id;
        this.updateHighlight();
      });
      group.addEventListener("blur", () => {
        if (this.hoveredId === node.id) this.hoveredId = null;
        this.updateHighlight();
      });
      group.addEventListener("pointerdown", (event) => {
        if (event.button !== 0) return;
        event.stopPropagation();
        const point = this.clientToGraph(event.clientX, event.clientY);
        const position = this.positions.get(node.id);
        this.draggedNode = node;
        this.dragMoved = false;
        this.dragOffset = { x: point.x - position.x, y: point.y - position.y };
        group.setPointerCapture(event.pointerId);
        this.updateRelationshipCandidate(point);
      });
      group.addEventListener("click", () => {
        if (this.dragMoved) {
          this.dragMoved = false;
          return;
        }
        this.select(node.id);
      });
      group.addEventListener("keydown", (event) => {
        if (!["Enter", " "].includes(event.key)) return;
        event.preventDefault();
        this.select(node.id);
      });
      return group;
    }

    bindEvents() {
      this.svg.addEventListener("pointerdown", (event) => {
        if (event.button !== 0 || event.target.closest("[data-node-id]")) return;
        this.panStart = {
          pointerId: event.pointerId,
          clientX: event.clientX,
          clientY: event.clientY,
          startX: event.clientX,
          startY: event.clientY,
          x: this.transform.x,
          y: this.transform.y,
          moved: false,
          isBlank:
            !this.cutMode
            && !this.inspectMode
            && !event.target.closest(".graph-edge-hit"),
        };
        this.svg.setPointerCapture(event.pointerId);
      });
      this.svg.addEventListener("pointermove", (event) => {
        if (this.draggedNode) {
          const point = this.clientToGraph(event.clientX, event.clientY);
          const position = this.positions.get(this.draggedNode.id);
          const nextX = point.x - this.dragOffset.x;
          const nextY = point.y - this.dragOffset.y;
          if (Math.hypot(nextX - position.x, nextY - position.y) > 1) this.dragMoved = true;
          position.x = nextX;
          position.y = nextY;
          position.vx = 0;
          position.vy = 0;
          this.updateRelationshipCandidate(point);
          this.updatePositions();
          return;
        }
        if (!this.panStart || this.panStart.pointerId !== event.pointerId) return;
        const bounds = this.svg.getBoundingClientRect();
        const scaleX = this.width / bounds.width;
        const scaleY = this.height / bounds.height;
        this.transform.x = this.panStart.x + (event.clientX - this.panStart.clientX) * scaleX;
        this.transform.y = this.panStart.y + (event.clientY - this.panStart.clientY) * scaleY;
        const panDistance = Math.hypot(
          event.clientX - this.panStart.startX,
          event.clientY - this.panStart.startY,
        );
        this.panStart.moved = this.panStart.moved || panDistance > 4;
        this.applyTransform();
      });
      const endPointer = (event) => {
        if (this.draggedNode) {
          const dragged = this.draggedNode;
          const candidate = this.mergeCandidateId
            ? this.nodes.find((node) => node.id === this.mergeCandidateId)
            : null;
          this.draggedNode = null;
          this.mergeCandidateId = null;
          this.updateHighlight();
          this.simulate();
          if (this.dragMoved && candidate) {
            this.onCreateRelationship?.({ sourceId: dragged.id, targetId: candidate.id });
          }
        }
        if (this.cutPointer?.pointerId === event.pointerId) {
          const edge = this.links.find((link) => link.id === this.cutEdgeId);
          const start = this.cutPointer;
          const dragDistance = Math.hypot(
            event.clientX - start.startX,
            event.clientY - start.startY,
          );
          const dragMoved = this.cutDragMoved || dragDistance > 4 || event.type === "pointercancel";
          this.cutPointer = null;
          this.cutEdgeId = null;
          this.cutDragMoved = false;
          this.hideToolGhost();
          this.updateHighlight();
          if (edge) this.onCutRelationship?.({ edge });
          if (edge || dragMoved) this.setCutMode(false);
        }
        if (this.inspectPointer?.pointerId === event.pointerId) {
          const edge = this.links.find((link) => link.id === this.inspectEdgeId);
          const start = this.inspectPointer;
          const dragDistance = Math.hypot(
            event.clientX - start.startX,
            event.clientY - start.startY,
          );
          const dragMoved =
            this.inspectDragMoved || dragDistance > 4 || event.type === "pointercancel";
          this.inspectPointer = null;
          this.inspectEdgeId = null;
          this.inspectDragMoved = false;
          this.hideToolGhost();
          this.updateHighlight();
          if (edge) this.onInspectRelationship?.({ edge });
          if (edge || dragMoved) this.setInspectMode(false);
        }
        if (this.panStart?.pointerId === event.pointerId) {
          const pan = this.panStart;
          this.panStart = null;
          if (pan.isBlank && !pan.moved && this.selectedId) this.onClearSelection?.();
        }
      };
      window.addEventListener("pointerup", endPointer);
      window.addEventListener("pointercancel", endPointer);
      this.svg.addEventListener("pointermove", (event) => {
        if (this.cutPointer?.pointerId === event.pointerId) {
          const start = this.cutPointer;
          const dragDistance = Math.hypot(
            event.clientX - start.startX,
            event.clientY - start.startY,
          );
          this.cutPointer = { ...start, clientX: event.clientX, clientY: event.clientY };
          this.cutDragMoved = this.cutDragMoved || dragDistance > 4;
          this.moveToolGhost(event.clientX, event.clientY);
          this.cutEdgeId = this.nearestEdgeAt(event.clientX, event.clientY)?.id || null;
        } else if (this.inspectPointer?.pointerId === event.pointerId) {
          const start = this.inspectPointer;
          const dragDistance = Math.hypot(
            event.clientX - start.startX,
            event.clientY - start.startY,
          );
          this.inspectPointer = { ...start, clientX: event.clientX, clientY: event.clientY };
          this.inspectDragMoved = this.inspectDragMoved || dragDistance > 4;
          this.moveToolGhost(event.clientX, event.clientY);
          this.inspectEdgeId = this.nearestEdgeAt(event.clientX, event.clientY)?.id || null;
        } else {
          return;
        }
        this.updateHighlight();
      });
      this.svg.addEventListener(
        "wheel",
        (event) => {
          event.preventDefault();
          const point = this.clientToScreen(event.clientX, event.clientY);
          const factor = event.deltaY < 0 ? 1.12 : 0.89;
          this.zoomAt(point.x, point.y, factor);
        },
        { passive: false },
      );
      this.svg.addEventListener("dblclick", (event) => {
        if (event.target.closest("[data-node-id]")) return;
        this.fit();
      });
      document.querySelector("#graph-zoom-in")?.addEventListener("click", () => {
        this.zoomAt(this.width / 2, this.height / 2, 1.22);
      });
      document.querySelector("#graph-zoom-out")?.addEventListener("click", () => {
        this.zoomAt(this.width / 2, this.height / 2, 0.82);
      });
      document.querySelector("#graph-reset")?.addEventListener("click", () => this.fit());
      const cutButton = document.querySelector("#graph-cut");
      cutButton?.addEventListener("pointerdown", (event) => {
        if (event.button !== 0) return;
        this.setInspectMode(false);
        this.setCutMode(true);
        this.beginCutDrag(event);
      });
      cutButton?.addEventListener("click", (event) => {
        if (event.detail !== 0) return;
        this.setCutMode(!this.cutMode);
        cutButton.setAttribute("aria-pressed", String(this.cutMode));
      });
      const inspectButton = document.querySelector("#graph-inspect");
      inspectButton?.addEventListener("pointerdown", (event) => {
        if (event.button !== 0) return;
        this.setCutMode(false);
        this.setInspectMode(true);
        this.beginInspectDrag(event);
      });
      inspectButton?.addEventListener("click", (event) => {
        if (event.detail !== 0) return;
        this.setInspectMode(!this.inspectMode);
      });
      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && (this.cutMode || this.inspectMode)) {
          this.setCutMode(false);
          this.setInspectMode(false);
        }
      });
    }

    select(nodeId) {
      this.selectedId = nodeId;
      this.updateHighlight();
      this.onSelect?.(nodeId);
    }

    setCutMode(enabled) {
      this.cutMode = Boolean(enabled);
      if (!this.cutMode) {
        this.cutPointer = null;
        this.cutEdgeId = null;
        this.cutDragMoved = false;
        this.hideToolGhost();
      }
      this.svg.classList.toggle("is-cut-mode", this.cutMode);
      document.querySelector("#graph-cut")?.setAttribute("aria-pressed", String(this.cutMode));
      this.updateHighlight();
    }

    beginCutDrag(event) {
      if (!this.cutMode || event.button !== 0) return;
      event.preventDefault();
      this.cutDragMoved = false;
      this.cutPointer = {
        pointerId: event.pointerId,
        clientX: event.clientX,
        clientY: event.clientY,
        startX: event.clientX,
        startY: event.clientY,
      };
      this.showToolGhost("cut", event.clientX, event.clientY);
      this.cutEdgeId = this.nearestEdgeAt(event.clientX, event.clientY)?.id || null;
      this.svg.setPointerCapture(event.pointerId);
      this.updateHighlight();
    }

    setInspectMode(enabled) {
      this.inspectMode = Boolean(enabled);
      if (!this.inspectMode) {
        this.inspectPointer = null;
        this.inspectEdgeId = null;
        this.inspectDragMoved = false;
        this.hideToolGhost();
      }
      this.svg.classList.toggle("is-inspect-mode", this.inspectMode);
      document.querySelector("#graph-inspect")?.setAttribute(
        "aria-pressed",
        String(this.inspectMode),
      );
      this.updateHighlight();
    }

    beginInspectDrag(event) {
      if (!this.inspectMode || event.button !== 0) return;
      event.preventDefault();
      this.inspectDragMoved = false;
      this.inspectPointer = {
        pointerId: event.pointerId,
        clientX: event.clientX,
        clientY: event.clientY,
        startX: event.clientX,
        startY: event.clientY,
      };
      this.showToolGhost("inspect", event.clientX, event.clientY);
      this.inspectEdgeId = this.nearestEdgeAt(event.clientX, event.clientY)?.id || null;
      this.svg.setPointerCapture(event.pointerId);
      this.updateHighlight();
    }

    showToolGhost(mode, clientX, clientY) {
      const ghost = document.querySelector("#graph-tool-ghost");
      const icon = document.querySelector("#graph-tool-ghost-icon use");
      if (!ghost) return;
      ghost.hidden = false;
      ghost.dataset.mode = mode;
      icon?.setAttribute("href", mode === "cut" ? "#icon-scissors" : "#icon-search");
      this.moveToolGhost(clientX, clientY);
    }

    hideToolGhost() {
      const ghost = document.querySelector("#graph-tool-ghost");
      if (ghost) ghost.hidden = true;
    }

    moveToolGhost(clientX, clientY) {
      const ghost = document.querySelector("#graph-tool-ghost");
      const bounds = this.stage.getBoundingClientRect();
      if (!ghost) return;
      ghost.style.left = `${clientX - bounds.left}px`;
      ghost.style.top = `${clientY - bounds.top}px`;
    }

    nearestEdgeAt(clientX, clientY) {
      const point = this.clientToGraph(clientX, clientY);
      let nearest = null;
      let nearestDistance = 24 / this.transform.scale;
      for (const link of this.links) {
        const path = link.element;
        if (!path || typeof path.getTotalLength !== "function") continue;
        const length = path.getTotalLength();
        for (let index = 0; index <= 30; index += 1) {
          const sample = path.getPointAtLength((length * index) / 30);
          const distance = Math.hypot(sample.x - point.x, sample.y - point.y);
          if (distance < nearestDistance) {
            nearest = link;
            nearestDistance = distance;
          }
        }
      }
      return nearest;
    }

    updateRelationshipCandidate(point) {
      if (!this.draggedNode) return;
      const draggedPosition = this.positions.get(this.draggedNode.id);
      let candidate = null;
      let candidateDistance = Infinity;
      for (const node of this.nodes) {
        if (node.id === this.draggedNode.id) continue;
        const position = this.positions.get(node.id);
        const distance = Math.hypot(
          draggedPosition.x - position.x,
          draggedPosition.y - position.y,
        );
        if (distance < 52 && distance < candidateDistance) {
          candidate = node;
          candidateDistance = distance;
        }
      }
      const changed = this.mergeCandidateId !== candidate?.id;
      this.mergeCandidateId = candidate?.id || null;
      if (changed) this.updateHighlight();
    }

    resize() {
      const bounds = this.stage.getBoundingClientRect();
      this.width = Math.max(1, bounds.width);
      this.height = Math.max(1, bounds.height);
      this.svg.setAttribute("viewBox", `0 0 ${this.width} ${this.height}`);
    }

    simulate(onSettled) {
      this.cancelAnimation();
      if (!this.nodes.length) return;
      if (this.reducedMotion) {
        for (let index = 0; index < 120; index += 1) this.tickPhysics(0.22);
        this.updatePositions();
        onSettled?.();
        return;
      }

      let alpha = 1;
      const step = () => {
        for (let iteration = 0; iteration < 2; iteration += 1) this.tickPhysics(alpha);
        alpha *= 0.972;
        this.updatePositions();
        this.simulationFrame += 1;
        if (alpha > 0.025 && this.simulationFrame < 150) {
          this.animationFrame = requestAnimationFrame(step);
        } else {
          this.animationFrame = 0;
          this.simulationFrame = 0;
          onSettled?.();
        }
      };
      this.animationFrame = requestAnimationFrame(step);
    }

    tickPhysics(alpha) {
      const centerX = this.width / 2;
      const centerY = this.height / 2;

      for (const link of this.links) {
        const source = this.positions.get(link.source_id);
        const target = this.positions.get(link.target_id);
        const dx = target.x - source.x;
        const dy = target.y - source.y;
        const distance = Math.max(1, Math.hypot(dx, dy));
        const force = (distance - 190) * 0.009 * alpha;
        source.vx += (dx / distance) * force;
        source.vy += (dy / distance) * force;
        target.vx -= (dx / distance) * force;
        target.vy -= (dy / distance) * force;
      }

      for (let first = 0; first < this.nodes.length; first += 1) {
        const a = this.positions.get(this.nodes[first].id);
        for (let second = first + 1; second < this.nodes.length; second += 1) {
          const b = this.positions.get(this.nodes[second].id);
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const distance = Math.max(18, Math.hypot(dx, dy));
          const repulsion = Math.min(2.2, 4200 / (distance * distance)) * alpha;
          a.vx -= (dx / distance) * repulsion;
          a.vy -= (dy / distance) * repulsion;
          b.vx += (dx / distance) * repulsion;
          b.vy += (dy / distance) * repulsion;
          const collision = 148 - distance;
          if (collision > 0) {
            const push = collision * 0.025 * alpha;
            a.vx -= (dx / distance) * push;
            a.vy -= (dy / distance) * push;
            b.vx += (dx / distance) * push;
            b.vy += (dy / distance) * push;
          }
        }
      }

      for (const node of this.nodes) {
        const position = this.positions.get(node.id);
        position.vx += (centerX - position.x) * 0.0018 * alpha;
        position.vy += (centerY - position.y) * 0.0018 * alpha;
        position.vx *= 0.84;
        position.vy *= 0.84;
        position.x += position.vx;
        position.y += position.vy;
      }
    }

    updatePositions() {
      for (const node of this.nodes) {
        const position = this.positions.get(node.id);
        node.element?.setAttribute("transform", `translate(${position.x} ${position.y})`);
      }
      for (const link of this.links) {
        const source = this.positions.get(link.source_id);
        const target = this.positions.get(link.target_id);
        const dx = target.x - source.x;
        const dy = target.y - source.y;
        const distance = Math.max(1, Math.hypot(dx, dy));
        const normalX = -dy / distance;
        const normalY = dx / distance;
        const direction = hash(link.id) % 2 === 0 ? 1 : -1;
        const curve = (20 + (hash(link.id) % 18)) * direction;
        const startPadding = (link.source.radius || 8) + 3;
        const endPadding = (link.target.radius || 8) + 3;
        const startX = source.x + (dx / distance) * startPadding;
        const startY = source.y + (dy / distance) * startPadding;
        const endX = target.x - (dx / distance) * endPadding;
        const endY = target.y - (dy / distance) * endPadding;
        const controlX = (startX + endX) / 2 + normalX * curve;
        const controlY = (startY + endY) / 2 + normalY * curve;
        link.element?.setAttribute(
          "d",
          `M ${startX} ${startY} Q ${controlX} ${controlY} ${endX} ${endY}`,
        );
        link.hitElement?.setAttribute("d", `M ${startX} ${startY} Q ${controlX} ${controlY} ${endX} ${endY}`);
      }
    }

    updateHighlight() {
      const activeId = this.hoveredId || this.selectedId;
      const neighbours = new Set(activeId ? [activeId] : []);
      for (const link of this.links) {
        if (link.source_id === activeId) neighbours.add(link.target_id);
        if (link.target_id === activeId) neighbours.add(link.source_id);
      }

      for (const node of this.nodes) {
        const element = node.element;
        element?.classList.toggle("is-selected", node.id === this.selectedId);
        element?.classList.toggle("is-neighbor", node.id !== activeId && neighbours.has(node.id));
        element?.classList.toggle("is-dimmed", Boolean(activeId) && !neighbours.has(node.id));
        element?.classList.toggle("is-merge-candidate", node.id === this.mergeCandidateId);
        element?.classList.toggle("is-merge-source", node.id === this.draggedNode?.id && Boolean(this.mergeCandidateId));
        const surface = element?.querySelector(".node-surface");
        const radius = node.radius || nodeRadiusForDegree(0);
        surface?.setAttribute("r", String(radius));
        element?.querySelector(".node-halo")?.setAttribute(
          "r",
          String(radius + (node.id === this.selectedId ? 11 : 7)),
        );
      }
      for (const link of this.links) {
        const active = link.id === this.cutEdgeId
          || link.id === this.inspectEdgeId
          || link.source_id === activeId
          || link.target_id === activeId;
        link.element?.classList.toggle("is-cut-target", link.id === this.cutEdgeId);
        link.hitElement?.classList.toggle("is-cut-target", link.id === this.cutEdgeId);
        link.element?.classList.toggle("is-inspect-target", link.id === this.inspectEdgeId);
        link.hitElement?.classList.toggle("is-inspect-target", link.id === this.inspectEdgeId);
        link.element?.classList.toggle("is-active", active);
        link.element?.classList.toggle("is-dimmed", Boolean(activeId) && !active);
      }
    }

    updateDescription() {
      const formulaLabel = this.nodes.length === 1 ? "formula" : "formulas";
      const relationLabel = this.links.length === 1 ? "relationship" : "relationships";
      const root = this.nodes.find((node) => node.id === this.selectedId);
      this.description.textContent =
        `${this.nodes.length} ${formulaLabel} and ${this.links.length} ${relationLabel} shown ` +
        `in this mind map${root ? ` with ${root.name} selected` : ""}. ` +
        "Drag nodes, scroll to zoom, or drag the canvas to pan.";
    }

    fit() {
      if (!this.nodes.length) return;
      const values = [...this.positions.values()];
      const minX = Math.min(...values.map((position) => position.x - 138));
      const maxX = Math.max(...values.map((position) => position.x + 138));
      const minY = Math.min(...values.map((position) => position.y - 38));
      const maxY = Math.max(...values.map((position) => position.y + 72));
      const contentWidth = Math.max(276, maxX - minX);
      const contentHeight = Math.max(150, maxY - minY);
      const scale = Math.min(1.35, Math.max(0.55, Math.min(
        (this.width - 56) / contentWidth,
        (this.height - 56) / contentHeight,
      )));
      const centerX = (minX + maxX) / 2;
      const centerY = (minY + maxY) / 2;
      this.transform.scale = scale;
      this.transform.x = this.width / 2 - centerX * scale;
      this.transform.y = this.height / 2 - centerY * scale;
      this.applyTransform();
    }

    zoomAt(screenX, screenY, factor) {
      const oldScale = this.transform.scale;
      const scale = Math.min(2.2, Math.max(0.45, oldScale * factor));
      const graphX = (screenX - this.transform.x) / oldScale;
      const graphY = (screenY - this.transform.y) / oldScale;
      this.transform.scale = scale;
      this.transform.x = screenX - graphX * scale;
      this.transform.y = screenY - graphY * scale;
      this.applyTransform();
    }

    applyTransform() {
      const { x, y, scale } = this.transform;
      this.viewport.setAttribute("transform", `translate(${x} ${y}) scale(${scale})`);
    }

    clientToScreen(clientX, clientY) {
      const bounds = this.svg.getBoundingClientRect();
      return {
        x: ((clientX - bounds.left) / bounds.width) * this.width,
        y: ((clientY - bounds.top) / bounds.height) * this.height,
      };
    }

    clientToGraph(clientX, clientY) {
      const screen = this.clientToScreen(clientX, clientY);
      return {
        x: (screen.x - this.transform.x) / this.transform.scale,
        y: (screen.y - this.transform.y) / this.transform.scale,
      };
    }

    cancelAnimation() {
      if (this.animationFrame) cancelAnimationFrame(this.animationFrame);
      this.animationFrame = 0;
      this.simulationFrame = 0;
    }
  }

  window.MathernetGraph = new FormulaGraph();
})();
