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
      this.width = 900;
      this.height = 540;
      this.transform = { x: 0, y: 0, scale: 1 };
      this.animationFrame = 0;
      this.simulationFrame = 0;
      this.draggedNode = null;
      this.dragMoved = false;
      this.panStart = null;
      this.reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      this.resizeObserver = new ResizeObserver(() => this.resize());
      this.resizeObserver.observe(this.stage);
      this.bindEvents();
      this.resize();
    }

    render(graph, { onSelect, selectedId } = {}) {
      this.cancelAnimation();
      this.onSelect = onSelect || null;
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
        const path = svgElement("path", {
          class: `graph-edge ${link.requires_user_confirmation ? "pending" : "accepted"}`,
          "data-edge-id": link.id,
          "data-source-id": link.source_id,
          "data-target-id": link.target_id,
        });
        link.element = path;
        this.edgeLayer.append(path);
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
      const hitArea = svgElement("circle", { class: "node-hit", r: 34 });
      const halo = svgElement("circle", { class: "node-halo", r: 19 });
      const surface = svgElement("circle", {
        class: "node-surface",
        r: node.id === this.selectedId ? 12 : 9,
      });
      const label = svgElement("text", {
        class: "node-name",
        x: 0,
        y: 34,
        "text-anchor": "middle",
      });
      labelLines(node.name).forEach((line, index) => {
        const row = svgElement("tspan", {
          x: 0,
          y: index === 0 ? 34 : 52,
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
          x: this.transform.x,
          y: this.transform.y,
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
          this.updatePositions();
          return;
        }
        if (!this.panStart || this.panStart.pointerId !== event.pointerId) return;
        const bounds = this.svg.getBoundingClientRect();
        const scaleX = this.width / bounds.width;
        const scaleY = this.height / bounds.height;
        this.transform.x = this.panStart.x + (event.clientX - this.panStart.clientX) * scaleX;
        this.transform.y = this.panStart.y + (event.clientY - this.panStart.clientY) * scaleY;
        this.applyTransform();
      });
      const endPointer = (event) => {
        if (this.draggedNode) {
          this.draggedNode = null;
          this.simulate();
        }
        if (this.panStart?.pointerId === event.pointerId) this.panStart = null;
      };
      this.svg.addEventListener("pointerup", endPointer);
      this.svg.addEventListener("pointercancel", endPointer);
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
    }

    select(nodeId) {
      this.selectedId = nodeId;
      this.updateHighlight();
      this.onSelect?.(nodeId);
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
        const startX = source.x + (dx / distance) * 15;
        const startY = source.y + (dy / distance) * 15;
        const endX = target.x - (dx / distance) * 15;
        const endY = target.y - (dy / distance) * 15;
        const controlX = (startX + endX) / 2 + normalX * curve;
        const controlY = (startY + endY) / 2 + normalY * curve;
        link.element?.setAttribute(
          "d",
          `M ${startX} ${startY} Q ${controlX} ${controlY} ${endX} ${endY}`,
        );
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
        const surface = element?.querySelector(".node-surface");
        surface?.setAttribute("r", node.id === this.selectedId ? "12" : "9");
      }
      for (const link of this.links) {
        const active = link.source_id === activeId || link.target_id === activeId;
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
