/**
 * SOLVI - Visualizador Interactivo de Esquemas Eléctricos SVG (Circuit Visualizer)
 * 
 * 100% Autónomo y Offline: No requiere librerías externas ni conexión a internet.
 * Proporciona renderizado vectorial, zoom/pan interactivo con soporte multitáctil (pinch-to-zoom),
 * inspección técnica de componentes y sincronización bidireccional con el Grafo de Conocimiento.
 */

(function(window) {
    "use strict";

    // ─── BASE DE DATOS DE SUBSISTEMAS EMBEBIDA (100% OFFLINE) ───
    const EMBEDDED_SUBSYSTEMS = null;
    let _subsystems = EMBEDDED_SUBSYSTEMS;
    let _currentSubsystemId = "safety_loop";
    let _activeSubsystem = null;

    // Estado del viewport SVG (coordenadas en user-space del SVG 1200x680)
    let _scale = 1.0;
    let _panX = 0;
    let _panY = 0;
    let _isDragging = false;
    let _lastClientX = 0;
    let _lastClientY = 0;
    let _lastPinchDistance = 0;
    let _highlightedNodeIds = new Set();
    let _selectedNode = null;
    let _filterQuery = "";

    // Elementos DOM
    let _container = null;
    let _svgElement = null;
    let _viewportGroup = null;

    const _GENERIC_WORDS = new Set([
        "interlock", "intlk", "item", "cable", "pcb", "rele", "relay", "punto",
        "prueba", "test", "point", "linea", "line", "para", "falla", "error",
        "alarma", "desde", "hacia", "circuito", "bucle", "switch", "sensor",
        "fuente", "supply", "board"
    ]);

    function escapeRegex(s) {
        return String(s || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    }

    // ─── TRANSFORMACIÓN DE COORDENADAS PANTALLA ➔ SVG ─────────────
    function clientToSvgPoint(clientX, clientY) {
        if (!_svgElement) {
            return { x: 600, y: 340 };
        }
        const pt = _svgElement.createSVGPoint();
        pt.x = clientX;
        pt.y = clientY;
        try {
            const ctm = _svgElement.getScreenCTM();
            if (ctm) {
                const p = pt.matrixTransform(ctm.inverse());
                return { x: p.x, y: p.y };
            }
        } catch (_err) {}
        return { x: 600, y: 340 };
    }

    function zoomAroundSvgPoint(svgX, svgY, newScale) {
        if (!isFinite(svgX) || isNaN(svgX) || !isFinite(svgY) || isNaN(svgY)) return;
        const clampedScale = Math.min(Math.max(newScale, 0.4), 4.5);
        if (_scale === clampedScale) return;
        const currentScale = (_scale > 0 && isFinite(_scale)) ? _scale : 1.0;
        _panX = svgX - (svgX - _panX) * (clampedScale / currentScale);
        _panY = svgY - (svgY - _panY) * (clampedScale / currentScale);
        _scale = clampedScale;
        aplicarTransformacion();
    }

    // ─── CARGA DE DATOS ──────────────────────────────────────────
    let _subsystemsLoadedFromServer = false;
    async function cargarDatosSubistemas() {
        if (_subsystemsLoadedFromServer) return _subsystems;

        // 1. Intentar sincronizar con circuit_schematics.json más reciente
        try {
            const resp = await fetch("/static/circuit_schematics.json");
            if (resp.ok) {
                _subsystems = await resp.json();
                _subsystemsLoadedFromServer = true;
                return _subsystems;
            }
        } catch (e) {
            try {
                const apiResp = await fetch("/circuits/subsystems");
                if (apiResp.ok) {
                    const apiData = await apiResp.json();
                    if (apiData && apiData.ok && apiData.subsystems) {
                        const indexed = {};
                        if (Array.isArray(apiData.subsystems)) {
                            apiData.subsystems.forEach(s => { indexed[s.id] = s; });
                        } else {
                            Object.assign(indexed, apiData.subsystems);
                        }
                        if (Object.keys(indexed).length >= 5) {
                            _subsystems = indexed;
                            _subsystemsLoadedFromServer = true;
                            return _subsystems;
                        }
                    }
                }
            } catch (_apiErr) {
                // Operación offline garantizada con los datos embebidos
            }
        }

        return _subsystems || {};
    }

    // ─── MOTOR DE RENDERIZADO SVG ───────────────────────────────
    function renderizarEsquema(subsystemId) {
        if (!_subsystems || !_subsystems[subsystemId]) return;
        _currentSubsystemId = subsystemId;
        _activeSubsystem = _subsystems[subsystemId];

        const container = document.getElementById("circuitCanvasContainer");
        if (!container) return;
        _container = container;

        // Construir el elemento SVG
        const sub = _activeSubsystem;
        const [vx, vy, vw, vh] = (sub.viewBox || "0 0 1200 680").split(" ").map(Number);

        let svgHtml = `
        <svg id="cvSvgRoot" xmlns="http://www.w3.org/2000/svg" viewBox="${sub.viewBox}" preserveAspectRatio="xMidYMid meet"
             style="width:100%;height:100%;display:block;user-select:none;touch-action:none;">
            <defs>
                <!-- Patrón de cuadrícula de plano eléctrico -->
                <pattern id="cvGridPattern" width="30" height="30" patternUnits="userSpaceOnUse">
                    <path d="M 30 0 L 0 0 0 30" fill="none" stroke="rgba(0, 212, 255, 0.04)" stroke-width="1"/>
                    <circle cx="0" cy="0" r="1" fill="rgba(0, 212, 255, 0.15)"/>
                </pattern>
                
                <!-- Filtros de resplandor para rutas activas -->
                <filter id="cvGlow" x="-20%" y="-20%" width="140%" height="140%">
                    <feGaussianBlur stdDeviation="4" result="blur" />
                    <feMerge>
                        <feMergeNode in="blur"/>
                        <feMergeNode in="SourceGraphic"/>
                    </feMerge>
                </filter>
                <filter id="cvPulseGlow" x="-30%" y="-30%" width="160%" height="160%">
                    <feGaussianBlur stdDeviation="6" result="blur" />
                    <feMerge>
                        <feMergeNode in="blur"/>
                        <feMergeNode in="SourceGraphic"/>
                    </feMerge>
                </filter>

                <!-- Marcadores de flechas para dirección de señal -->
                <marker id="cvArrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                    <path d="M 0 1 L 10 5 L 0 9 z" fill="#00d4ff" />
                </marker>
                <marker id="cvArrowActive" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                    <path d="M 0 1 L 10 5 L 0 9 z" fill="#4ade80" />
                </marker>
            </defs>

            <!-- Fondo con cuadrícula -->
            <rect x="0" y="0" width="100%" height="100%" fill="#0a0f1d"/>
            <rect x="-10000" y="-10000" width="20000" height="20000" fill="url(#cvGridPattern)" pointer-events="none"/>

            <!-- Grupo interactivo de vista (con Pan & Zoom) -->
            <g id="cvViewportGroup" transform="translate(${_panX}, ${_panY}) scale(${_scale})" style="will-change:transform;">
                <!-- Capa 1: Cables y Conexiones -->
                <g id="cvWiresLayer">
                    ${renderizarCables(sub.wires || [])}
                </g>

                <!-- Capa 2: Nodos de Componentes y PCBs -->
                <g id="cvNodesLayer">
                    ${renderizarNodos(sub.nodes || [])}
                </g>
            </g>
        </svg>`;

        container.innerHTML = svgHtml;
        _svgElement = document.getElementById("cvSvgRoot");
        _viewportGroup = document.getElementById("cvViewportGroup");

        adjuntarEventosInteractivos();
        actualizarBadgesSubistema();
        aplicarResaltadosDOM();
    }

    // ─── RENDERIZADO DE NODOS ────────────────────────────────────
    function renderizarNodos(nodes) {
        return nodes.map(n => {
            const isHighlighted = _highlightedNodeIds.has(n.id);
            const hlClass = isHighlighted ? "cv-node highlighted" : "cv-node";
            
            // Iconos y colores según el tipo de nodo
            let typeColor = "#60a5fa";
            let typeIcon = "📦";
            let typeBadge = "COMP";

            if (n.type === "pcb") {
                typeColor = "#a78bfa";
                typeIcon = "🔲";
                typeBadge = "PCB";
            } else if (n.type === "test_point") {
                typeColor = "#fde047";
                typeIcon = "⚡";
                typeBadge = "TP";
            } else if (n.type === "relay") {
                typeColor = "#f59e0b";
                typeIcon = "🔌";
                typeBadge = "RELÉ";
            } else if (n.type === "interlock") {
                typeColor = "#ef4444";
                typeIcon = "🔒";
                typeBadge = "INTLK";
            } else if (n.type === "switch") {
                typeColor = "#38bdf8";
                typeIcon = "🔘";
                typeBadge = "SW";
            } else if (n.type === "source") {
                typeColor = "#4ade80";
                typeIcon = "🔋";
                typeBadge = "ALIM";
            } else if (n.type === "sensor") {
                typeColor = "#00d4ff";
                typeIcon = "📡";
                typeBadge = "SENS";
            } else if (n.type === "cable") {
                typeColor = "#93c5fd";
                typeIcon = "〰️";
                typeBadge = "CABLE";
            } else if (n.type === "load") {
                typeColor = "#c084fc";
                typeIcon = "⚙️";
                typeBadge = "CARGA";
            }

            // Render especial para Puntos de Prueba (TP): Formato compacto diamante/círculo
            if (n.type === "test_point") {
                const cx = n.x + n.width / 2;
                const cy = n.y + n.height / 2;
                return `
                <g class="${hlClass}" data-id="${n.id}"
                   style="cursor:pointer;" tabindex="0" role="button" aria-label="${escSvg(n.name)}">
                    <circle cx="${cx}" cy="${cy}" r="22" fill="#111827" stroke="${typeColor}" stroke-width="${isHighlighted ? '3' : '2'}"
                            stroke-dasharray="${isHighlighted ? '4 2' : 'none'}" />
                    <circle cx="${cx}" cy="${cy}" r="7" fill="${typeColor}" />
                    <text x="${cx}" y="${cy - 26}" text-anchor="middle" font-family="'Share Tech Mono', monospace" font-size="11" font-weight="bold" fill="${typeColor}">${escSvg(n.code)}</text>
                    <text x="${cx}" y="${cy + 34}" text-anchor="middle" font-family="'Barlow', sans-serif" font-size="9" fill="#94a3b8">${escSvg(n.name)}</text>
                </g>`;
            }

            // Render estándar para tarjetas PCB, Relés, Interlocks y fuentes
            return `
            <g class="${hlClass}" data-id="${n.id}"
               style="cursor:pointer;" tabindex="0" role="button" aria-label="${escSvg(n.name)}">
                <!-- Caja base -->
                <rect x="${n.x}" y="${n.y}" width="${n.width}" height="${n.height}" rx="8"
                      fill="#111827" stroke="${isHighlighted ? '#00d4ff' : 'rgba(30, 41, 59, 0.9)'}" stroke-width="${isHighlighted ? '2.5' : '1.5'}"
                      style="filter: drop-shadow(0 4px 12px rgba(0,0,0,0.5));" />
                
                <!-- Barra superior de acento -->
                <path d="M ${n.x} ${n.y + 6} A 6 6 0 0 1 ${n.x + 6} ${n.y} L ${n.x + n.width - 6} ${n.y} A 6 6 0 0 1 ${n.x + n.width} ${n.y + 6} L ${n.x + n.width} ${n.y + 22} L ${n.x} ${n.y + 22} Z"
                      fill="rgba(255,255,255,0.03)" />
                <line x1="${n.x}" y1="${n.y + 22}" x2="${n.x + n.width}" y2="${n.y + 22}" stroke="rgba(255,255,255,0.08)" stroke-width="1" />
                
                <!-- Indicador de tipo y código -->
                <rect x="${n.x + 8}" y="${n.y + 4}" width="42" height="14" rx="3" fill="${typeColor}22" stroke="${typeColor}66" stroke-width="0.8"/>
                <text x="${n.x + 29}" y="${n.y + 14}" text-anchor="middle" font-family="'Share Tech Mono', monospace" font-size="8.5" font-weight="bold" fill="${typeColor}">
                    ${typeBadge}
                </text>
                
                <text x="${n.x + 56}" y="${n.y + 15}" font-family="'Share Tech Mono', monospace" font-size="10.5" font-weight="bold" fill="#f8fafc">
                    ${escSvg(n.code)}
                </text>

                <!-- Título o nombre -->
                <text x="${n.x + 10}" y="${n.y + 42}" font-family="'Barlow', sans-serif" font-weight="600" font-size="12" fill="#e2e8f0">
                    ${escSvg(truncate(n.name, 22))}
                </text>

                <!-- Especificación / Rango de operación -->
                <text x="${n.x + 10}" y="${n.y + 58}" font-family="'Share Tech Mono', monospace" font-size="9" fill="#94a3b8">
                    ${escSvg(truncate(n.spec, 28))}
                </text>

                <!-- Puertos de conexión visuales -->
                <circle cx="${n.x}" cy="${n.y + n.height / 2}" r="3.5" fill="${typeColor}" />
                <circle cx="${n.x + n.width}" cy="${n.y + n.height / 2}" r="3.5" fill="${typeColor}" />
            </g>`;
        }).join("");
    }

    // ─── RENDERIZADO DE CABLES ───────────────────────────────────
    function renderizarCables(wires) {
        return wires.map(w => {
            const isHighlighted = (_highlightedNodeIds.has(w.from) && _highlightedNodeIds.has(w.to)) ||
                                  _highlightedNodeIds.has(w.id);

            const pointsStr = (w.points || []).map(pt => `${pt[0]},${pt[1]}`).join(" ");
            let dPath = "";
            if (w.points && w.points.length >= 2) {
                dPath = `M ${w.points[0][0]} ${w.points[0][1]} ` +
                        w.points.slice(1).map(p => `L ${p[0]} ${p[1]}`).join(" ");
            }

            let strokeColor = "#334155";
            let strokeWidth = 1.8;
            if (w.type === "power") strokeColor = "#38bdf8";
            else if (w.type === "safety") strokeColor = "#f59e0b";
            else if (w.type === "high_voltage") strokeColor = "#ef4444";
            else if (w.type === "rf") strokeColor = "#c084fc";
            else if (w.type === "feedback") strokeColor = "#4ade80";

            if (isHighlighted) {
                strokeColor = "#00d4ff";
                strokeWidth = 3.5;
            }

            // Etiqueta de cable en el punto medio
            let labelSvg = "";
            if (w.label && w.points && w.points.length >= 2) {
                const midIdx = Math.floor(w.points.length / 2);
                const p1 = w.points[midIdx - 1] || w.points[0];
                const p2 = w.points[midIdx];
                const mx = (p1[0] + p2[0]) / 2;
                const my = (p1[1] + p2[1]) / 2;
                labelSvg = `
                <g class="cv-wire-label" transform="translate(${mx}, ${my})">
                    <rect x="-24" y="-9" width="48" height="15" rx="3" fill="#0b0f1a" stroke="${strokeColor}" stroke-width="0.8"/>
                    <text x="0" y="2" text-anchor="middle" font-family="'Share Tech Mono', monospace" font-size="8" fill="${isHighlighted ? '#00d4ff' : '#94a3b8'}">${escSvg(w.label)}</text>
                </g>`;
            }

            return `
            <g class="cv-wire-group ${isHighlighted ? 'wire-highlighted' : ''}" data-id="${w.id}">
                <!-- Trazo de fondo para facilitar clic -->
                <path d="${dPath}" fill="none" stroke="transparent" stroke-width="14" style="cursor:pointer;"/>
                <!-- Trazo visible -->
                <path class="cv-wire ${isHighlighted ? 'wire-highlighted' : ''}"
                      d="${dPath}" fill="none" stroke="${strokeColor}" stroke-width="${strokeWidth}"
                      stroke-linecap="round" stroke-linejoin="round"
                      ${isHighlighted ? 'stroke-dasharray="8 4" marker-end="url(#cvArrowActive)"' : 'marker-end="url(#cvArrow)"'} />
                ${labelSvg}
            </g>`;
        }).join("");
    }

    // ─── CONTROL DE EVENTOS: PAN & ZOOM INTERACTIVOS ────────────
    function adjuntarEventosInteractivos() {
        if (!_container || !_svgElement) return;

        desadjuntarEventosInteractivos();

        _container.addEventListener("wheel", onWheel, { passive: false });
        _container.addEventListener("mousedown", onMouseDown);
        _container.addEventListener("click", onContainerClick);
        _container.addEventListener("keydown", onContainerKeyDown);
        window.addEventListener("mousemove", onMouseMove);
        window.addEventListener("mouseup", onMouseUp);

        _container.addEventListener("touchstart", onTouchStart, { passive: false });
        _container.addEventListener("touchmove", onTouchMove, { passive: false });
        _container.addEventListener("touchend", onTouchEnd, { passive: false });
        _container.addEventListener("touchcancel", onTouchCancel, { passive: false });

        window.addEventListener("blur", onWindowBlur);
        window.addEventListener("resize", onWindowResize);
    }

    function desadjuntarEventosInteractivos() {
        if (_container) {
            _container.removeEventListener("wheel", onWheel);
            _container.removeEventListener("mousedown", onMouseDown);
            _container.removeEventListener("click", onContainerClick);
            _container.removeEventListener("keydown", onContainerKeyDown);
            _container.removeEventListener("touchstart", onTouchStart);
            _container.removeEventListener("touchmove", onTouchMove);
            _container.removeEventListener("touchend", onTouchEnd);
            _container.removeEventListener("touchcancel", onTouchCancel);
        }
        window.removeEventListener("mousemove", onMouseMove);
        window.removeEventListener("mouseup", onMouseUp);
        window.removeEventListener("blur", onWindowBlur);
        window.removeEventListener("resize", onWindowResize);
    }

    function onContainerClick(e) {
        if (_isDragging) return;
        const nodeEl = e.target.closest("g[data-id]");
        if (nodeEl) {
            const id = nodeEl.dataset.id;
            if (nodeEl.classList.contains("cv-wire-group") || nodeEl.closest(".cv-wire-group")) {
                inspeccionarCable(id);
            } else {
                inspeccionarNodo(id);
            }
        }
    }

    function onContainerKeyDown(e) {
        if (e.key === "Enter" || e.key === " ") {
            const nodeEl = e.target.closest("g[data-id]");
            if (nodeEl) {
                e.preventDefault();
                const id = nodeEl.dataset.id;
                if (nodeEl.classList.contains("cv-wire-group") || nodeEl.closest(".cv-wire-group")) {
                    inspeccionarCable(id);
                } else {
                    inspeccionarNodo(id);
                }
            }
        }
    }

    function onWheel(e) {
        e.preventDefault();
        const svgPt = clientToSvgPoint(e.clientX, e.clientY);
        const zoomFactor = e.deltaY < 0 ? 1.15 : 0.87;
        zoomAroundSvgPoint(svgPt.x, svgPt.y, _scale * zoomFactor);
    }

    let _touchStartX = 0;
    let _touchStartY = 0;
    let _touchMoved = false;
    let _touchTarget = null;
    let _rafId = null;

    function solicitarTransformacion() {
        if (_rafId) return;
        _rafId = requestAnimationFrame(() => {
            _rafId = null;
            aplicarTransformacion();
        });
    }

    function onMouseDown(e) {
        if (e.button !== 0) return;
        if (e.target.closest(".cv-node") || e.target.closest(".cv-wire-label") || e.target.closest("button")) {
            return;
        }
        _isDragging = true;
        _lastClientX = e.clientX;
        _lastClientY = e.clientY;
        if (_container) _container.style.cursor = "grabbing";
    }

    function onMouseMove(e) {
        if (!_isDragging) return;
        const prevPt = clientToSvgPoint(_lastClientX, _lastClientY);
        const currPt = clientToSvgPoint(e.clientX, e.clientY);
        _panX += (currPt.x - prevPt.x);
        _panY += (currPt.y - prevPt.y);
        _lastClientX = e.clientX;
        _lastClientY = e.clientY;
        solicitarTransformacion();
    }

    function onMouseUp() {
        if (_isDragging) {
            _isDragging = false;
            if (_container) _container.style.cursor = "grab";
        }
    }

    // ─── GESTOS TÁCTILES MÓVILES (Android / iOS) ────────────────
    function onTouchStart(e) {
        if (e.touches.length === 1) {
            const t = e.touches[0];
            _isDragging = true;
            _lastClientX = t.clientX;
            _lastClientY = t.clientY;
            _touchStartX = t.clientX;
            _touchStartY = t.clientY;
            _touchMoved = false;
            _touchTarget = e.target;
        } else if (e.touches.length === 2) {
            _isDragging = false;
            _touchMoved = true;
            const t1 = e.touches[0];
            const t2 = e.touches[1];
            _lastPinchDistance = Math.hypot(t1.clientX - t2.clientX, t1.clientY - t2.clientY);
            _lastClientX = (t1.clientX + t2.clientX) / 2;
            _lastClientY = (t1.clientY + t2.clientY) / 2;
            e.preventDefault();
        }
    }

    function onTouchMove(e) {
        if (e.touches.length === 1 && _isDragging) {
            const t = e.touches[0];
            const dist = Math.hypot(t.clientX - _touchStartX, t.clientY - _touchStartY);
            if (dist > 5) {
                _touchMoved = true;
                const prevPt = clientToSvgPoint(_lastClientX, _lastClientY);
                const currPt = clientToSvgPoint(t.clientX, t.clientY);
                _panX += (currPt.x - prevPt.x);
                _panY += (currPt.y - prevPt.y);
                _lastClientX = t.clientX;
                _lastClientY = t.clientY;
                solicitarTransformacion();
                e.preventDefault();
            }
        } else if (e.touches.length === 2 && _lastPinchDistance > 0) {
            _touchMoved = true;
            const t1 = e.touches[0];
            const t2 = e.touches[1];
            const currentDist = Math.hypot(t1.clientX - t2.clientX, t1.clientY - t2.clientY);
            const midX = (t1.clientX + t2.clientX) / 2;
            const midY = (t1.clientY + t2.clientY) / 2;

            const prevMidPt = clientToSvgPoint(_lastClientX, _lastClientY);
            const currMidPt = clientToSvgPoint(midX, midY);
            _panX += (currMidPt.x - prevMidPt.x);
            _panY += (currMidPt.y - prevMidPt.y);
            _lastClientX = midX;
            _lastClientY = midY;

            if (_lastPinchDistance > 5) {
                const currentScale = (_scale > 0 && isFinite(_scale)) ? _scale : 1.0;
                const factor = currentDist / _lastPinchDistance;
                if (isFinite(factor) && factor > 0) {
                    const newScale = Math.min(Math.max(currentScale * factor, 0.4), 4.5);
                    _panX = currMidPt.x - (currMidPt.x - _panX) * (newScale / currentScale);
                    _panY = currMidPt.y - (currMidPt.y - _panY) * (newScale / currentScale);
                    _scale = newScale;
                }
            }
            if (!isFinite(_panX) || isNaN(_panX)) _panX = 0;
            if (!isFinite(_panY) || isNaN(_panY)) _panY = 0;
            _lastPinchDistance = currentDist;

            solicitarTransformacion();
            e.preventDefault();
        }
    }

    function onTouchEnd(e) {
        if (e.touches.length === 0) {
            if (!_touchMoved && _touchTarget) {
                const nodeEl = _touchTarget.closest ? _touchTarget.closest(".cv-node") : null;
                const wireEl = _touchTarget.closest ? _touchTarget.closest(".cv-wire-group") : null;
                if (nodeEl && nodeEl.dataset && nodeEl.dataset.id) {
                    inspeccionarNodo(nodeEl.dataset.id);
                } else if (wireEl && wireEl.dataset && wireEl.dataset.id) {
                    inspeccionarCable(wireEl.dataset.id);
                }
            }
            _isDragging = false;
            _lastPinchDistance = 0;
            _touchTarget = null;
        } else if (e.touches.length === 1) {
            _lastPinchDistance = 0;
            _isDragging = true;
            _lastClientX = e.touches[0].clientX;
            _lastClientY = e.touches[0].clientY;
            _touchStartX = e.touches[0].clientX;
            _touchStartY = e.touches[0].clientY;
        }
    }

    function onTouchCancel() {
        _isDragging = false;
        _lastPinchDistance = 0;
        _touchTarget = null;
    }

    function onWindowBlur() {
        _isDragging = false;
        _lastPinchDistance = 0;
        _touchTarget = null;
    }

    function onWindowResize() {
        _isDragging = false;
        _lastPinchDistance = 0;
    }

    function aplicarTransformacion() {
        if (!isFinite(_panX) || isNaN(_panX)) _panX = 0;
        if (!isFinite(_panY) || isNaN(_panY)) _panY = 0;
        if (!isFinite(_scale) || isNaN(_scale) || _scale <= 0) _scale = 1.0;
        if (_viewportGroup) {
            _viewportGroup.setAttribute("transform", `translate(${_panX}, ${_panY}) scale(${_scale})`);
        }
        const zoomText = document.getElementById("cvZoomPercent");
        if (zoomText) {
            zoomText.textContent = `${Math.round(_scale * 100)}%`;
        }
    }

    // ─── RESALTADO DE COMPONENTES Y RUTAS ───────────────────────
    function aplicarResaltadosDOM() {
        if (!_container) return;

        // Limpiar clases previas
        _container.querySelectorAll(".cv-node").forEach(el => {
            el.classList.toggle("highlighted", _highlightedNodeIds.has(el.dataset.id));
        });

        // Actualizar cables
        if (_activeSubsystem && _activeSubsystem.wires) {
            _container.querySelectorAll(".cv-wire-group").forEach(group => {
                const wId = group.dataset.id;
                const wireObj = _activeSubsystem.wires.find(w => w.id === wId);
                if (wireObj) {
                    const isHl = (_highlightedNodeIds.has(wireObj.from) && _highlightedNodeIds.has(wireObj.to)) ||
                                 _highlightedNodeIds.has(wId);
                    group.classList.toggle("wire-highlighted", isHl);
                    const pathEl = group.querySelector(".cv-wire");
                    if (pathEl) {
                        if (isHl) {
                            pathEl.setAttribute("stroke", "#00d4ff");
                            pathEl.setAttribute("stroke-width", "3.5");
                            pathEl.setAttribute("stroke-dasharray", "8 4");
                            pathEl.setAttribute("marker-end", "url(#cvArrowActive)");
                        } else {
                            let originalColor = "#334155";
                            if (wireObj.type === "power") originalColor = "#38bdf8";
                            else if (wireObj.type === "safety") originalColor = "#f59e0b";
                            else if (wireObj.type === "high_voltage") originalColor = "#ef4444";
                            else if (wireObj.type === "rf") originalColor = "#c084fc";
                            else if (wireObj.type === "feedback") originalColor = "#4ade80";
                            pathEl.setAttribute("stroke", originalColor);
                            pathEl.setAttribute("stroke-width", "1.8");
                            pathEl.removeAttribute("stroke-dasharray");
                            pathEl.setAttribute("marker-end", "url(#cvArrow)");
                        }
                    }
                }
            });
        }
    }

    function centrarEnNodos(nodeIds) {
        if (!nodeIds || !nodeIds.length || !_activeSubsystem) return;
        const nodes = _activeSubsystem.nodes.filter(n => nodeIds.includes(n.id));
        if (!nodes.length) return;

        // Calcular caja delimitadora en espacio SVG
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        nodes.forEach(n => {
            minX = Math.min(minX, n.x);
            minY = Math.min(minY, n.y);
            maxX = Math.max(maxX, n.x + n.width);
            maxY = Math.max(maxY, n.y + n.height);
        });

        const centerX = (minX + maxX) / 2;
        const centerY = (minY + maxY) / 2;

        const spanX = maxX - minX;
        const spanY = maxY - minY;
        let targetScale = 1.35;
        if (nodes.length > 1) {
            const padX = 140;
            const padY = 120;
            const scaleX = (1200 - padX * 2) / Math.max(spanX, 100);
            const scaleY = (680 - padY * 2) / Math.max(spanY, 100);
            targetScale = Math.min(scaleX, scaleY);
            targetScale = Math.max(0.65, Math.min(targetScale, 1.4));
        }

        _scale = targetScale;
        // El centro del viewBox 1200x680 es (600, 340)
        _panX = 600 - (centerX * _scale);
        _panY = 340 - (centerY * _scale);

        aplicarTransformacion();
    }

    function _extraerPatronesNodo(n) {
        const pats = new Set();
        const nid = (n.id || "").toUpperCase();
        const code = (n.code || "").toUpperCase();
        const spec = (n.spec || "").toUpperCase();
        const norm = s => String(s).toUpperCase().replace(/[\W_]+/g, "");

        pats.add(norm(nid));
        pats.add(norm(code));

        const mCable = code.match(/\bW\d+\b/) || nid.match(/\bW\d+\b/);
        if (mCable) {
            pats.add(mCable[0]);
            pats.add("CABLE" + mCable[0]);
        }
        const mTp = code.match(/\bTP_?\w+\b/) || nid.match(/\bTP_?\w+\b/);
        if (mTp) pats.add(norm(mTp[0]));

        const mItem = code.match(/\bITEM_?(\d+)\b/) || nid.match(/\bITEM_?(\d+)\b/) || spec.match(/\bITEM_?(\d+)\b/);
        if (mItem) {
            pats.add("ITEM" + mItem[1]);
            pats.add("INTERLOCK" + mItem[1]);
            pats.add("INTLK" + mItem[1]);
            pats.add(mItem[1]);
        }

        const mIntlk = code.match(/\b(?:INTERLOCK|INTLK)_?(\d+)\b/) || nid.match(/\b(?:INTERLOCK|INTLK)_?(\d+)\b/) || spec.match(/\b(?:INTERLOCK|INTLK)_?(\d+)\b/);
        if (mIntlk) {
            pats.add("INTERLOCK" + mIntlk[1]);
            pats.add("INTLK" + mIntlk[1]);
            pats.add("ITEM" + mIntlk[1]);
            pats.add(mIntlk[1]);
        }

        const mPcb = code.match(/\bPCB_?(\w+)\b/) || nid.match(/\bPCB_?(\w+)\b/);
        if (mPcb) {
            pats.add("PCB" + mPcb[1]);
            pats.add(mPcb[1]);
        }

        const mRelay = code.match(/\bK\d+\b/) || nid.match(/\bK\d+\b/);
        if (mRelay) {
            pats.add(mRelay[0]);
            pats.add("RELAY" + mRelay[0]);
        }

        return pats;
    }

    // ─── INTEGRACIÓN CON RELACIONAR / GRAFO (REQUIREMENT 2) ─────
    async function loadAndHighlightFromTrace(traceData) {
        if (!traceData) return;
        await cargarDatosSubistemas();

        resetZoom();
        _highlightedNodeIds.clear();

        // Determinar qué componentes deben resaltarse
        const components = [];
        if (Array.isArray(traceData.resolved_nodes)) components.push(...traceData.resolved_nodes);
        if (Array.isArray(traceData.pcbs)) components.push(...traceData.pcbs);
        if (Array.isArray(traceData.cables)) components.push(...traceData.cables);
        if (Array.isArray(traceData.test_points)) components.push(...traceData.test_points);
        if (traceData.hub_node) components.push(traceData.hub_node);

        // Encontrar el subsistema más afín
        let targetSubsystem = "safety_loop";
        if (traceData.circuit_schematic && traceData.circuit_schematic.subsystem_id) {
            targetSubsystem = traceData.circuit_schematic.subsystem_id;
        } else {
            const compStr = components.join(" ").toLowerCase();
            if (/\b(409|474|modulador|radiaci[oó]n|radiation|tiratron|magnetron|rf|pfn|pcb\s*22)\b/i.test(compStr)) {
                targetSubsystem = "radiation_beam";
            } else if (/\b(dosis|dose|camara|chamber|d_rate|327|332|66|pcb\s*17|pcb\s*18)\b/i.test(compStr)) {
                targetSubsystem = "dosimetry";
            } else if (/\b(gantry|colimador|collimator|motor|encoder|215|servo|pcb\s*25)\b/i.test(compStr)) {
                targetSubsystem = "gantry_collimator";
            } else if (/\b(vac[ií]o|vacuum|cañ[oó]n|canon|gun|112|118|vacion|pcb\s*14|pcb\s*12)\b/i.test(compStr)) {
                targetSubsystem = "vacuum_gun";
            }
        }

        // Cambiar al selector
        const selectEl = document.getElementById("cvSubsystemSelect");
        if (selectEl) selectEl.value = targetSubsystem;

        renderizarEsquema(targetSubsystem);

        // Usar nodos ya resueltos por el backend si coinciden con este subsistema
        if (traceData.circuit_schematic &&
            traceData.circuit_schematic.subsystem_id === targetSubsystem &&
            Array.isArray(traceData.circuit_schematic.matched_nodes) &&
            traceData.circuit_schematic.matched_nodes.length > 0) {
            traceData.circuit_schematic.matched_nodes.forEach(nid => _highlightedNodeIds.add(nid));
        }

        // Correlación de nodos precisa
        if (_activeSubsystem && _activeSubsystem.nodes) {
            _activeSubsystem.nodes.forEach(n => {
                const pats = _extraerPatronesNodo(n);
                const matched = components.some(c => {
                    const normC = String(c).toUpperCase().replace(/[\W_]+/g, "");
                    if (pats.has(normC)) return true;
                    for (const p of pats) {
                        if (p.length >= 3) {
                            if (p === normC) return true;
                            try {
                                if (new RegExp("\\b" + escapeRegex(p) + "\\b", "i").test(String(c))) return true;
                            } catch (_reErr) {
                                if (String(c).toUpperCase().includes(p)) return true;
                            }
                        }
                    }
                    const termWords = String(c).toLowerCase().split(/\W+/).filter(w => w.length >= 4 && !_GENERIC_WORDS.has(w));
                    const nameWords = (n.name || "").toLowerCase().split(/\W+/).filter(w => w.length >= 4 && !_GENERIC_WORDS.has(w));
                    return termWords.some(tw => nameWords.some(nw => nw === tw || (nw.length >= 5 && nw.includes(tw))));
                });
                if (matched) _highlightedNodeIds.add(n.id);
            });
        }

        aplicarResaltadosDOM();

        // Mostrar banner de traza activa
        const banner = document.getElementById("cvTraceBanner");
        if (banner) {
            banner.style.display = "flex";
            const txt = document.getElementById("cvTraceBannerText");
            if (txt) {
                const hubLabel = traceData.hub_node ? ` · Nodo clave: ${traceData.hub_node}` : "";
                txt.textContent = `⚡ Ruta activa resaltada${hubLabel} (${_highlightedNodeIds.size} elementos)`;
            }
        }

        if (_highlightedNodeIds.size > 0) {
            centrarEnNodos(Array.from(_highlightedNodeIds));
        }
    }

    // ─── INSPECTOR DE COMPONENTES (DRAWER) ──────────────────────
    function inspeccionarNodo(nodeId) {
        if (!_activeSubsystem) return;
        const node = _activeSubsystem.nodes.find(n => n.id === nodeId);
        if (!node) return;

        _selectedNode = node;
        const drawer = document.getElementById("cvInspectorDrawer");
        if (!drawer) return;

        drawer.innerHTML = `
        <div style="background:var(--surface);border:1px solid var(--border);border-top:3px solid var(--accent);border-radius:12px;padding:16px;box-shadow:0 10px 30px rgba(0,0,0,0.6);animation:fadeIn 0.2s ease;">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px;gap:8px;">
                <div>
                    <span style="display:inline-block;font-size:0.65rem;font-family:var(--mono);padding:2px 7px;border-radius:4px;background:rgba(0,212,255,0.12);color:var(--accent);font-weight:bold;margin-bottom:4px;">
                        ${node.type.toUpperCase()} · ${escSvg(node.code)}
                    </span>
                    <h3 style="font-size:1.05rem;color:var(--text);margin:0;font-weight:700;">${escSvg(node.name)}</h3>
                </div>
                <button type="button" data-cv-action="cerrar" style="background:none;border:none;color:var(--muted);font-size:1.3rem;cursor:pointer;padding:4px 8px;">✕</button>
            </div>

            <div style="background:rgba(0,0,0,0.25);border:1px solid var(--border);border-radius:8px;padding:10px;margin-bottom:12px;font-size:0.8rem;line-height:1.5;">
                <div style="color:#94a3b8;margin-bottom:4px;"><strong>Función en el sistema:</strong> ${escSvg(node.role || 'Componente de control')}</div>
                <div style="color:var(--green);font-family:var(--mono);"><strong>Especificación eléctrica:</strong> ${escSvg(node.spec)}</div>
            </div>

            <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;justify-content:space-between;">
                <div>
                    ${node.manual ? `
                    <button type="button" class="btn-pdf" data-action="ver-pdf" data-manual="${escSvg(node.manual)}" data-page="${node.page || 1}" data-kw="${escSvg(node.code)}">
                        📖 Ver en ${escSvg(node.manual)} (Pág. ${node.page || 1})
                    </button>` : ''}
                </div>
                <div style="display:flex;gap:6px;flex-wrap:wrap;">
                    <button type="button" class="btn btn-ghost btn-sm" data-cv-action="medir" data-id="${node.id}" style="color:#fde047;border-color:rgba(253,224,71,0.35);background:rgba(253,224,71,0.08);">
                        📟 Medir con Multímetro
                    </button>
                    <button type="button" class="btn btn-ghost btn-sm" data-cv-action="trazar" data-code="${escSvg(node.code)}">
                        🧭 Trazar en Relacionar
                    </button>
                    <button type="button" class="btn btn-primary btn-sm" data-cv-action="aislar" data-id="${node.id}">
                        🎯 Aislar en plano
                    </button>
                </div>
            </div>
        </div>`;

        if (!drawer.dataset.listenerAttached) {
            drawer.dataset.listenerAttached = "true";
            drawer.addEventListener("click", onDrawerClick);
        }

        drawer.style.display = "block";
    }

    function inspeccionarCable(wireId) {
        if (!_activeSubsystem) return;
        const wire = _activeSubsystem.wires.find(w => w.id === wireId);
        if (!wire) return;

        const drawer = document.getElementById("cvInspectorDrawer");
        if (!drawer) return;

        drawer.innerHTML = `
        <div style="background:var(--surface);border:1px solid var(--border);border-top:3px solid #60a5fa;border-radius:12px;padding:16px;box-shadow:0 10px 30px rgba(0,0,0,0.6);">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px;">
                <div>
                    <span style="display:inline-block;font-size:0.65rem;font-family:var(--mono);padding:2px 7px;border-radius:4px;background:rgba(96,165,250,0.12);color:#93c5fd;font-weight:bold;margin-bottom:4px;">
                        LÍNEA DE CONEXIÓN · ${escSvg(wire.label || wire.id)}
                    </span>
                    <h3 style="font-size:0.95rem;color:var(--text);margin:0;">Conexión: ${escSvg(wire.from)} ➔ ${escSvg(wire.to)}</h3>
                </div>
                <button type="button" data-cv-action="cerrar" style="background:none;border:none;color:var(--muted);font-size:1.3rem;cursor:pointer;">✕</button>
            </div>
            <p style="font-size:0.8rem;color:#94a3b8;margin:0 0 10px;">Tipo de señal: <strong>${escSvg(wire.type.toUpperCase())}</strong></p>
            <button type="button" class="btn btn-primary btn-sm" data-cv-action="resaltar-ruta" data-from="${escSvg(wire.from)}" data-to="${escSvg(wire.to)}">⚡ Resaltar este segmento</button>
        </div>`;

        if (!drawer.dataset.listenerAttached) {
            drawer.dataset.listenerAttached = "true";
            drawer.addEventListener("click", onDrawerClick);
        }

        drawer.style.display = "block";
    }

    function onDrawerClick(e) {
        const btn = e.target.closest("[data-cv-action]");
        if (!btn) return;
        e.preventDefault();
        const act = btn.dataset.cvAction;
        if (act === "cerrar") cerrarInspector();
        else if (act === "medir") medirEnMultimetro(btn.dataset.id);
        else if (act === "trazar") trazarEnDiagnostico(btn.dataset.code);
        else if (act === "aislar") resaltarUnicoNodo(btn.dataset.id);
        else if (act === "resaltar-ruta") resaltarRuta(btn.dataset.from, btn.dataset.to);
    }

    function cerrarInspector() {
        const drawer = document.getElementById("cvInspectorDrawer");
        if (drawer) drawer.style.display = "none";
    }

    function trazarEnDiagnostico(componentCode) {
        cerrarInspector();
        if (typeof window.irA === "function") {
            window.irA("Diagnose");
            const firstInput = document.querySelector(".symptom-input");
            if (firstInput) {
                firstInput.value = componentCode;
                if (typeof window.ejecutarTrazaGrafo === "function") {
                    window.ejecutarTrazaGrafo();
                }
            }
        }
    }

    function medirEnMultimetro(nodeId) {
        cerrarInspector();
        if (window.Multimeter) {
            if (typeof window.Multimeter.abrirInspectorModal === "function") {
                window.Multimeter.abrirInspectorModal(nodeId);
            } else if (typeof window.irA === "function") {
                window.irA("Multimeter");
                if (typeof window.Multimeter.seleccionarPuntoDePrueba === "function") {
                    window.Multimeter.seleccionarPuntoDePrueba(nodeId);
                }
            }
        } else if (typeof window.irA === "function") {
            window.irA("Multimeter");
        }
    }

    // ─── HERRAMIENTAS DE ZOOM Y EXPORTACIÓN ──────────────────────
    function zoomIn() {
        zoomAroundSvgPoint(600, 340, _scale * 1.25);
    }

    function zoomOut() {
        zoomAroundSvgPoint(600, 340, _scale / 1.25);
    }

    function resetZoom() {
        _scale = 1.0;
        _panX = 0;
        _panY = 0;
        aplicarTransformacion();
    }

    function fitToScreen() {
        resetZoom();
    }

    function exportSvg() {
        if (!_svgElement || !_activeSubsystem) return;
        const svgClone = _svgElement.cloneNode(true);
        if (!svgClone.getAttribute("xmlns")) {
            svgClone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
        }
        svgClone.setAttribute("version", "1.1");
        const svgBlob = new Blob([svgClone.outerHTML], { type: "image/svg+xml;charset=utf-8" });
        const url = URL.createObjectURL(svgBlob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `solvi_esquema_${_activeSubsystem.id}.svg`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(() => URL.revokeObjectURL(url), 60000);
        if (typeof window.toast === "function") {
            window.toast("Esquema SVG descargado con éxito", "ok");
        }
    }

    function buscarEnEsquema(texto) {
        _filterQuery = (texto || "").trim().toUpperCase();
        _highlightedNodeIds.clear();

        if (_filterQuery && _activeSubsystem) {
            const normQ = _filterQuery.replace(/[\W_]+/g, "");
            _activeSubsystem.nodes.forEach(n => {
                const pats = _extraerPatronesNodo(n);
                let matched = pats.has(normQ) || pats.has(_filterQuery);
                if (!matched) {
                    for (const p of pats) {
                        if (p.length >= 3 && (p === normQ || normQ.includes(p))) {
                            matched = true;
                            break;
                        }
                    }
                }
                if (!matched) {
                    const nameWords = (n.name || "").toLowerCase().split(/\W+/);
                    const qWords = (texto || "").toLowerCase().split(/\W+/);
                    matched = qWords.some(qw => qw.length >= 3 && nameWords.some(nw => nw === qw || (nw.length >= 5 && nw.includes(qw))));
                }
                if (matched) {
                    _highlightedNodeIds.add(n.id);
                }
            });
            if (_activeSubsystem.wires) {
                _activeSubsystem.wires.forEach(w => {
                    const typeMatches = w.type && w.type.toUpperCase().includes(_filterQuery);
                    const labelMatches = w.label && w.label.toUpperCase().includes(_filterQuery);
                    const isControl = _filterQuery.includes("CONTROL") && (w.type === "safety" || w.type === "feedback");
                    const isPower = _filterQuery.includes("POTENCIA") && (w.type === "power" || w.type === "high_voltage");
                    if (typeMatches || labelMatches || isControl || isPower) {
                        _highlightedNodeIds.add(w.id);
                        _highlightedNodeIds.add(w.from);
                        _highlightedNodeIds.add(w.to);
                    }
                });
            }
            if (_highlightedNodeIds.size > 0) {
                centrarEnNodos(Array.from(_highlightedNodeIds));
            }
        }
        aplicarResaltadosDOM();
    }

    function limpiarResaltados() {
        _highlightedNodeIds.clear();
        aplicarResaltadosDOM();
        const banner = document.getElementById("cvTraceBanner");
        if (banner) banner.style.display = "none";
        const input = document.getElementById("cvSearchInput");
        if (input) input.value = "";
    }

    function resaltarUnicoNodo(nodeId) {
        _highlightedNodeIds.clear();
        _highlightedNodeIds.add(nodeId);
        aplicarResaltadosDOM();
        centrarEnNodos([nodeId]);
    }

    function resaltarRuta(fromId, toId) {
        _highlightedNodeIds.clear();
        _highlightedNodeIds.add(fromId);
        _highlightedNodeIds.add(toId);
        aplicarResaltadosDOM();
        centrarEnNodos([fromId, toId]);
    }

    function actualizarBadgesSubistema() {
        const titleEl = document.getElementById("cvSubsystemTitle");
        const badgeEl = document.getElementById("cvSubsystemBadge");
        const descEl = document.getElementById("cvSubsystemDesc");

        if (_activeSubsystem) {
            if (titleEl) titleEl.textContent = _activeSubsystem.name;
            if (badgeEl) badgeEl.textContent = _activeSubsystem.badge || "Circuito Linac";
            if (descEl) descEl.textContent = _activeSubsystem.description || "";
        }
    }

    // ─── CICLO DE VIDA (DESACOPLAMIENTO Y LIMPIEZA DE MEMORIA) ───
    async function onActivate() {
        await cargarDatosSubistemas();
        if (!_activeSubsystem) {
            renderizarEsquema(_currentSubsystemId);
        } else {
            adjuntarEventosInteractivos();
            actualizarBadgesSubistema();
            aplicarTransformacion();
        }
    }

    function onDeactivate() {
        desadjuntarEventosInteractivos();
        cerrarInspector();
        _isDragging = false;
        _lastPinchDistance = 0;
        if (_rafId) {
            cancelAnimationFrame(_rafId);
            _rafId = null;
        }
    }

    // ─── UTILIDADES ──────────────────────────────────────────────
    function escSvg(str) {
        if (!str) return "";
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&apos;");
    }

    function truncate(str, max) {
        if (!str) return "";
        return str.length > max ? str.substring(0, max - 1) + "…" : str;
    }

    // ─── API PÚBLICA ─────────────────────────────────────────────
    
    function toggleNodeState(nodeId) {
        if (!_activeSubsystem) return;
        const node = _activeSubsystem.nodes.find(n => n.id === nodeId);
        if (!node) return;
        
        // Toggle simulation state
        node._simState = node._simState === 'fault' ? 'nominal' : 'fault';
        
        const rect = document.getElementById('cv_node_' + nodeId + '_rect');
        const text = document.getElementById('cv_node_' + nodeId + '_text');
        
        if (node._simState === 'fault') {
            if (rect) {
                rect.setAttribute('stroke', '#ef4444');
                rect.setAttribute('fill', 'rgba(239,68,68,0.15)');
            }
            if (text) text.setAttribute('fill', '#ef4444');
            if (typeof window.toast === 'function') window.toast(node.name + ' forzado a FALLA/ABIERTO', 'error');
        } else {
            if (rect) {
                rect.setAttribute('stroke', 'rgba(0, 212, 255, 0.4)');
                rect.setAttribute('fill', 'rgba(10, 15, 29, 0.9)');
            }
            if (text) text.setAttribute('fill', '#00d4ff');
            if (typeof window.toast === 'function') window.toast(node.name + ' restaurado a NOMINAL', 'success');
        }
    }

    cargarDatosSubistemas();

    window.CircuitVisualizer = {
        init: async function() {
            await cargarDatosSubistemas();
        },
        cambiarSubsistema: function(id) {
            limpiarResaltados();
            resetZoom();
            renderizarEsquema(id);
        },
        inspeccionarNodo,
        inspeccionarCable,
        cerrarInspector,
        trazarEnDiagnostico,
        medirEnMultimetro,
        zoomIn,
        zoomOut,
        resetZoom,
        fitToScreen,
        exportSvg,
        buscarEnEsquema,
        limpiarResaltados,
        resaltarUnicoNodo,
        resaltarRuta,
        loadAndHighlightFromTrace,
        onActivate,
        onDeactivate
    };

})(window);
