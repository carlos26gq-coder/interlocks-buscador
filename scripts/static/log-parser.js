class LogParser {
    static async parseTextBackend(text) {
        try {
            const res = await fetch("/logs/parse", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ text })
            });
            if (!res.ok) throw new Error("Error parsing logs");
            return await res.json();
        } catch (e) {
            console.error(e);
            throw e;
        }
    }

    static detectDateLocale(text) {
        if (!text) return false;
        const regex = /\b(\d{2})\/(\d{2})\/(\d{4})\b/g;
        let match;
        while ((match = regex.exec(text)) !== null) {
            let p1 = parseInt(match[1], 10);
            let p2 = parseInt(match[2], 10);
            if (p1 > 12 && p2 <= 12) return false; // Dia > 12 -> DD/MM/YYYY (Euro)
            if (p1 <= 12 && p2 > 12) return true;  // Dia > 12 en segunda posicion -> MM/DD/YYYY (US)
        }
        return false; // Por defecto Euro
    }

    static parseTimestamp(ts_str, isUs = null) {
        if (!ts_str) return 0.0;
        let match = ts_str.match(/\b\d{13}\b/);
        if (match) {
            let val = parseFloat(match[0]) / 1000.0;
            return Number.isFinite(val) ? val : 0.0;
        }

        match = ts_str.match(/(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?/);
        if (match) {
            let [_, y, m, d, h, min, s, ms] = match;
            let msStr = ms ? ms.padEnd(3, '0').substring(0, 3) : '000';
            let dObj = new Date(`${y}-${m}-${d}T${h}:${min}:${s}.${msStr}Z`);
            let t = dObj.getTime();
            return Number.isFinite(t) ? t / 1000.0 : 0.0;
        }
        match = ts_str.match(/(\d{2})\/(\d{2})\/(\d{4}) (\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?/);
        if (match) {
            let [_, p1, p2, y, h, min, s, ms] = match;
            let p1Int = parseInt(p1, 10);
            let p2Int = parseInt(p2, 10);
            let d, m;
            let targetIsUs = isUs;
            if (targetIsUs === null || targetIsUs === undefined) {
                if (p1Int <= 12 && p2Int > 12) targetIsUs = true;
                else if (p1Int > 12 && p2Int <= 12) targetIsUs = false;
                else targetIsUs = false;
            }

            if (targetIsUs) {
                m = p1; d = p2;
            } else {
                d = p1; m = p2;
            }

            if (parseInt(m, 10) > 12 && parseInt(d, 10) <= 12) {
                let tmp = m; m = d; d = tmp;
            }
            let msStr = ms ? ms.padEnd(3, '0').substring(0, 3) : '000';
            let dObj = new Date(`${y}-${m}-${d}T${h}:${min}:${s}.${msStr}Z`);
            let t = dObj.getTime();
            return Number.isFinite(t) ? t / 1000.0 : 0.0;
        }
        return 0.0;
    }

    static parseChunk(lines, startIndex, isUs = false) {
        const events = [];
        const SEV_REGEX = /\b(FATAL|CR[ÍI]TICO|ERROR|WARNING|ADVERTENCIA|INFO)\b/i;
        const ID_REGEX = /\b(INTERLOCK \d+|ITEM \d+|ERROR \d+|PCB \w+|W\d+|COLLISION|VAC_ION)\b/gi;
        const TS_REGEX = /(?:\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?)|(?:\d{2}\/\d{2}\/\d{4} \d{2}:\d{2}:\d{2}(?:\.\d+)?)|(?:\b\d{13}\b)/;

        for (let i = 0; i < lines.length; i++) {
            let line = lines[i].trim();
            if (!line) continue;

            let ts_str = "";
            let ts_val = 0.0;
            let ts_match = line.match(TS_REGEX);
            if (ts_match) {
                ts_str = ts_match[0];
                ts_val = this.parseTimestamp(ts_str, isUs);
            }

            let sev = "INFO";
            let sev_match = line.match(SEV_REGEX);
            if (sev_match) {
                sev = sev_match[0].toUpperCase();
                if (sev === "CRÍTICO" || sev === "CRITICO") sev = "FATAL";
                if (sev === "ADVERTENCIA") sev = "WARNING";
            }

            let ids = [];
            let id_match;
            while ((id_match = ID_REGEX.exec(line)) !== null) {
                ids.push(id_match[0].toUpperCase());
            }

            events.push({
                line_number: startIndex + i + 1,
                raw: line,
                timestamp: ts_val,
                timestamp_str: ts_str,
                severity: sev,
                identifiers: ids,
                precursors: []
            });
        }
        return events;
    }

    static async parseFileClientSide(file) {
        return new Promise(async (resolve, reject) => {
            const chunkSize = 1024 * 1024;
            let offset = 0;
            let chunkResults = [];
            let remainingString = "";
            let totalLines = 0;

            let isUs = false;
            if (typeof file.slice === "function") {
                try {
                    const sampleSlice = file.slice(0, Math.min(file.size, 512 * 1024));
                    let sampleText = "";
                    if (typeof sampleSlice.text === "function") {
                        sampleText = await sampleSlice.text();
                    } else {
                        sampleText = await new Promise((res) => {
                            const r = new FileReader();
                            r.onload = () => res(r.result || "");
                            r.onerror = () => res("");
                            r.readAsText(sampleSlice);
                        });
                    }
                    isUs = LogParser.detectDateLocale(sampleText);
                } catch (e) {
                    // Fall back a Euro por defecto
                }
            }

            const decoder = new TextDecoder("utf-8");
            const reader = new FileReader();
            
            const renderProgress = (processed) => {
                const el = document.getElementById("logParsingSpinner");
                if (el) {
                    let msg = el.querySelector("p");
                    if (msg) msg.textContent = `Procesando archivo: ${Math.round((processed / file.size) * 100)}%`;
                }
            };

            reader.onload = function(e) {
                const hasMore = (offset + chunkSize) < file.size;
                const textChunk = decoder.decode(e.target.result, { stream: hasMore });
                let text = remainingString + textChunk;
                let lines = text.split(/\r?\n/);
                remainingString = lines.pop() || "";

                const chunkEvents = LogParser.parseChunk(lines, totalLines, isUs);
                chunkResults.push(chunkEvents);
                totalLines += lines.length;

                offset += chunkSize;
                renderProgress(Math.min(offset, file.size));

                if (offset < file.size) {
                    setTimeout(() => readNextChunk(), 0);
                } else {
                    if (remainingString) {
                        chunkResults.push(LogParser.parseChunk([remainingString], totalLines, isUs));
                        totalLines++;
                    }
                    const events = [];
                    for (let c = 0; c < chunkResults.length; c++) {
                        const cArr = chunkResults[c];
                        for (let j = 0; j < cArr.length; j++) {
                            events.push(cArr[j]);
                        }
                    }
                    resolve(LogParser.aggregate(events, totalLines));
                }
            };
            
            reader.onerror = () => reject(reader.error);

            function readNextChunk() {
                let slice = file.slice(offset, offset + chunkSize);
                reader.readAsArrayBuffer(slice);
            }

            readNextChunk();
        });
    }

    static aggregate(events, totalLines) {
        events.sort((a, b) => (a.timestamp - b.timestamp) || (a.line_number - b.line_number));
        let cascades = [];
        let current_cascade = [];
        
        let summary = { fatals: 0, errors: 0, warnings: 0, infos: 0 };
        for (let ev of events) {
            if (ev.severity === "FATAL") summary.fatals++;
            else if (ev.severity === "ERROR") summary.errors++;
            else if (ev.severity === "WARNING") summary.warnings++;
            else summary.infos++;

            if (ev.severity !== "FATAL" && ev.severity !== "ERROR") continue;
            
            if (current_cascade.length === 0) {
                current_cascade.push(ev);
            } else {
                let inCascade = false;
                if (ev.timestamp > 0 && current_cascade[0].timestamp > 0) {
                    let diff = ev.timestamp - current_cascade[0].timestamp;
                    inCascade = (diff >= 0 && diff <= 2.0);
                } else {
                    // Si falta timestamp, solo agrupar lineas consecutivas inmediatas (<= 2 lineas)
                    inCascade = Math.abs(ev.line_number - current_cascade[current_cascade.length - 1].line_number) <= 2;
                }

                if (inCascade) {
                    current_cascade.push(ev);
                } else {
                    cascades.push(current_cascade);
                    current_cascade = [ev];
                }
            }
        }
        if (current_cascade.length > 0) cascades.push(current_cascade);

        // P3: Deteccion de eventos WARNING precursores (ventana corta de 5s previo al evento raiz)
        const usedPrecursors = new Set();
        for (let cascade of cascades) {
            const root = cascade[0];
            const rootT = root.timestamp;
            const rootLine = root.line_number;
            const precursors = [];

            for (let ev of events) {
                if (ev.severity !== "WARNING") continue;
                if (usedPrecursors.has(ev.line_number)) continue;

                let isCandidate = false;
                if (rootT > 0 && ev.timestamp > 0) {
                    const diff = rootT - ev.timestamp;
                    if (diff >= 0 && diff <= 5.0 && ev.line_number < rootLine) {
                        isCandidate = true;
                    }
                } else if (rootLine - ev.line_number > 0 && rootLine - ev.line_number <= 5) {
                    isCandidate = true;
                }

                if (isCandidate) {
                    precursors.push(ev);
                    usedPrecursors.add(ev.line_number);
                }
            }
            root.precursors = precursors;
            cascade.precursors = precursors;
        }

        return { ok: true, total_lines: totalLines, events, cascades, summary };
    }
    
    static actionSearch(id) {
        irA('Search');
        const qEl = document.getElementById('q');
        if (qEl) qEl.value = id || '';
        if (typeof buscar === 'function') buscar();
        else if (typeof window.buscar === 'function') window.buscar();
    }

    static actionCircuits(id) {
        irA('Circuits');
        if (window.CircuitVisualizer && typeof window.CircuitVisualizer.buscarEnEsquema === 'function') {
            window.CircuitVisualizer.buscarEnEsquema(id || '');
        }
    }

    static actionMultimeter(tp) {
        irA('Multimeter');
        if (typeof window.dmmSelTp === 'function') {
            window.dmmSelTp(tp);
        } else if (window.Multimeter && typeof window.Multimeter.seleccionarPuntoDePrueba === 'function') {
            window.Multimeter.seleccionarPuntoDePrueba(tp);
        }
    }

    static actionDiagnose(id) {
        irA('Diagnose');
        const inputs = document.querySelectorAll('.symptom-input');
        if (inputs.length > 0) inputs[0].value = id || '';
        if (typeof window.ejecutarTrazaGrafo === 'function') {
            window.ejecutarTrazaGrafo();
        } else if (typeof ejecutarTrazaGrafo === 'function') {
            ejecutarTrazaGrafo();
        }
    }

    static renderResults(data) {
        const container = document.getElementById("logResults");
        if (!container) return;
        
        let html = `<div class="info-box">
            <p>Total Líneas: ${data.total_lines}</p>
            <p>Cascadas Detectadas: ${data.cascades.length}</p>
            <p>Errores: ${data.summary.errors}, Críticos: ${data.summary.fatals}</p>
        </div>`;
        
        if (data.cascades.length > 0) {
            html += `<h4 style="margin-top:15px; margin-bottom:10px;">Cascadas de Fallo (Causa Raíz)</h4>`;
            data.cascades.forEach((cascade, idx) => {
                if (idx >= 50) return;
                html += `<div style="border-left:3px solid var(--danger); background:var(--surface); padding:10px; margin-bottom:10px; border-radius:4px;">
                    <h5 style="color:var(--danger)">Cascada ${idx + 1}</h5>`;
                
                const rootEvent = cascade[0];
                const rootIds = (rootEvent.identifiers && rootEvent.identifiers.length > 0) ? rootEvent.identifiers.join(", ") : "Sin identificador";
                html += `<p style="font-size:0.8rem; margin:5px 0;"><strong>Causa Raíz:</strong> ${rootEvent.timestamp_str} - ${rootEvent.severity} - ${rootIds}</p>`;
                
                if (rootEvent.precursors && rootEvent.precursors.length > 0) {
                    const precList = rootEvent.precursors.map(p => `${p.timestamp_str ? p.timestamp_str + ' · ' : ''}${p.raw.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")}`).join('<br>');
                    html += `<p style="font-size:0.78rem; margin:4px 0; color:var(--warn, #e6a23c);">⚠️ <strong>Posible precursor:</strong><br>${precList}</p>`;
                }

                // P0-1: Corregido ReferenceError: identifiers no estaba en scope
                const primaryId = (rootEvent.identifiers && rootEvent.identifiers[0]) || '';
                const suggestedTp = LogParser.mapIdentifierToTP(primaryId);
                
                html += `<div style="display:flex;gap:5px;flex-wrap:wrap;margin-top:10px;">
                    <button type="button" class="btn btn-ghost btn-sm" data-log-action="search" data-target="${primaryId}">🔍 Ver en Manuales</button>
                    <button type="button" class="btn btn-ghost btn-sm" data-log-action="circuits" data-target="${primaryId}">⚡ Ver en Esquema SVG</button>
                    ${suggestedTp ? `<button type="button" class="btn btn-ghost btn-sm" data-log-action="multimeter" data-target="${suggestedTp}">📟 Medir con Multímetro (${suggestedTp})</button>` : ''}
                    <button type="button" class="btn btn-primary btn-sm" data-log-action="export-notes" data-idx="${idx}">📝 Exportar a Mis Apuntes</button>
                    <button type="button" class="btn btn-ghost btn-sm" data-log-action="diagnose" data-target="${primaryId}">🧭 Ver Traza Topológica</button>
                </div>`;
                html += `</div>`;
            });
            if (data.cascades.length > 50) {
                html += `<p style="color:var(--muted); font-size:0.8rem;">Y ${data.cascades.length - 50} cascadas más...</p>`;
            }
        }
        
        html += `<h4 style="margin-top:15px; margin-bottom:10px;">Visor de Eventos</h4>
        <div id="logViewerContainer" style="background:var(--surface); border:1px solid var(--border); border-radius:4px; max-height:400px; overflow-y:auto; padding:10px; font-family:var(--mono); font-size:0.75rem; color:var(--text);">
        </div>`;
        
        container.innerHTML = html;
        window._currentLogData = data;

        const viewer = document.getElementById("logViewerContainer");
        if (viewer) {
            // P2-2: Limite de seguridad de elementos DOM para fluidez en tablets de baja RAM
            const MAX_DOM_EVENTS = 2000;
            let pageSize = 200;
            let rendered = 0;
            const eventsToRender = data.events.filter(e => e.severity === "FATAL" || e.severity === "ERROR" || e.severity === "WARNING");
            
            if (eventsToRender.length === 0) {
                viewer.innerHTML = `<span style="color:var(--muted)">No hay errores, advertencias o eventos críticos para mostrar.</span>`;
            } else {
                let ceilingReached = false;
                const renderPage = () => {
                    if (ceilingReached) return;
                    if (rendered >= MAX_DOM_EVENTS) {
                        ceilingReached = true;
                        let notice = document.createElement("div");
                        notice.style.padding = "8px";
                        notice.style.textAlign = "center";
                        notice.style.color = "var(--warn, #e6a23c)";
                        notice.style.borderTop = "1px dashed var(--border)";
                        notice.style.marginTop = "6px";
                        notice.style.fontStyle = "italic";
                        notice.textContent = `Mostrando los primeros ${MAX_DOM_EVENTS} eventos de ${eventsToRender.length} totales (límite de seguridad para fluidez en pantalla).`;
                        viewer.appendChild(notice);
                        return;
                    }

                    let end = Math.min(rendered + pageSize, MAX_DOM_EVENTS, eventsToRender.length);
                    let toRender = eventsToRender.slice(rendered, end);
                    if (toRender.length === 0) return;
                    
                    let df = document.createDocumentFragment();
                    for (let ev of toRender) {
                        let d = document.createElement("div");
                        d.style.marginBottom = "4px";
                        d.style.padding = "4px";
                        d.style.borderBottom = "1px solid var(--border)";
                        let color = ev.severity === "FATAL" ? "var(--danger)" : (ev.severity === "ERROR" ? "var(--warn)" : "var(--accent)");
                        let rawEscaped = String(ev.raw || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
                        d.innerHTML = `<span style="color:${color}; width:60px; display:inline-block;">${ev.severity}</span> 
                                       <span style="color:var(--muted); margin-right:10px;">${ev.timestamp_str}</span> 
                                       ${rawEscaped}`;
                        df.appendChild(d);
                    }
                    viewer.appendChild(df);
                    rendered = end;

                    if (rendered >= MAX_DOM_EVENTS && rendered < eventsToRender.length && !ceilingReached) {
                        ceilingReached = true;
                        let notice = document.createElement("div");
                        notice.style.padding = "8px";
                        notice.style.textAlign = "center";
                        notice.style.color = "var(--warn, #e6a23c)";
                        notice.style.borderTop = "1px dashed var(--border)";
                        notice.style.marginTop = "6px";
                        notice.style.fontStyle = "italic";
                        notice.textContent = `Mostrando los primeros ${MAX_DOM_EVENTS} eventos de ${eventsToRender.length} totales (límite de seguridad para fluidez en pantalla).`;
                        viewer.appendChild(notice);
                    }
                };
                
                renderPage();
                viewer.addEventListener("scroll", () => {
                    if (viewer.scrollTop + viewer.clientHeight >= viewer.scrollHeight - 50) {
                        renderPage();
                    }
                });
            }
        }
    }
    
    static exportToNotes(cascadeIdx) {
        if (!window._currentLogData) return;
        const cascade = window._currentLogData.cascades[cascadeIdx];
        if (!cascade) return;
        
        const rootEvent = cascade[0];
        const identifiers = [...new Set(cascade.reduce((acc, e) => acc.concat(e.identifiers || []), []))].join(", ");
        
        let noteText = `Análisis Cronológico de Secuencia de Falla\n\nCascada iniciada: ${rootEvent.timestamp_str}\nSeveridad: ${rootEvent.severity}\nComponentes/IDs involucrados: ${identifiers}\n`;
        
        if (rootEvent.precursors && rootEvent.precursors.length > 0) {
            noteText += `\n⚠️ Posibles precursores detectados (5s previos):\n` +
                rootEvent.precursors.map(p => `- ${p.timestamp_str}: ${p.raw}`).join("\n") + "\n";
        }

        noteText += `\nDetalle eventos:\n` +
            cascade.map(e => `- ${e.timestamp_str}: ${e.raw}`).join("\n");
            
        irA('Notes');
        const abrirFn = (typeof window.abrirFormNota === 'function') ? window.abrirFormNota : ((typeof abrirFormNota === 'function') ? abrirFormNota : null);
        if (abrirFn) {
            abrirFn();
            setTimeout(() => {
                const elTit = document.getElementById('notaTit');
                const elTxt = document.getElementById('notaTxt');
                const elTags = document.getElementById('notaTags');
                const firstId = (identifiers.split(",")[0] || "").trim();
                if (elTit) elTit.value = "Falla detectada: " + (firstId || "Desconocida");
                if (elTxt) elTxt.value = noteText;
                if (elTags) elTags.value = "log, cascade";
            }, 100);
        }
    }
    
    static triggerFileInput() {
        const input = document.getElementById('logFileInput');
        if (input) input.click();
    }
    
    static async handleFileSelect(evt) {
        evt.stopPropagation();
        evt.preventDefault();
        
        const files = evt.dataTransfer ? evt.dataTransfer.files : evt.target.files;
        if (!files || files.length === 0) return;
        
        const f = files[0];
        
        const spinner = document.getElementById("logParsingSpinner");
        if (spinner) spinner.style.display = "block";
        const resEl = document.getElementById("logResults");
        if (resEl) resEl.innerHTML = "";
        
        try {
            const data = await LogParser.parseFileClientSide(f);
            LogParser.renderResults(data);
        } catch (err) {
            alert("Error analizando el archivo: " + err);
        } finally {
            if (spinner) spinner.style.display = "none";
            if (evt.target && evt.target.value) {
                try { evt.target.value = ""; } catch (e) {}
            }
        }
    }
    
    static async handlePaste() {
        const pasteArea = document.getElementById("logPasteArea");
        const text = pasteArea ? pasteArea.value : "";
        if (!text.trim()) return;
        
        const spinner = document.getElementById("logParsingSpinner");
        if (spinner) spinner.style.display = "block";
        const resEl = document.getElementById("logResults");
        if (resEl) resEl.innerHTML = "";
        
        try {
            const isUs = LogParser.detectDateLocale(text);
            let lines = text.split(/\r?\n/);
            let events = LogParser.parseChunk(lines, 0, isUs);
            let data = LogParser.aggregate(events, lines.length);
            LogParser.renderResults(data);
        } catch (err) {
            alert("Error analizando el texto: " + err);
        } finally {
            if (spinner) spinner.style.display = "none";
        }
    }
    
    static loadSample() {
        const sample = `2026-09-15 10:55:57.123 INFO Iniciando sistema
2026-09-15 10:55:58.000 WARNING Dosis rate mismatch
2026-09-15 10:55:58.500 ERROR ITEM 112 failed
2026-09-15 10:55:58.800 FATAL INTERLOCK 283 tripped cascade
2026-09-15 10:55:59.100 FATAL W12 signal lost
2026-09-15 10:56:10.000 INFO Recovery started`;
        const pasteArea = document.getElementById("logPasteArea");
        if (pasteArea) pasteArea.value = sample;
        LogParser.handlePaste();
    }

    static mapIdentifierToTP(identifier) {
        if (!identifier) return null;
        const id = String(identifier).trim().toUpperCase();
        const validTps = new Set([
            "TP1", "TP2", "TP5", "TP3", "TP_HT", "TP_RF", "TP100", "TP_DOSE1", "TP_DOSE2",
            "TP_SPEED", "TP_POS", "TP_VAC", "TP_GUN", "TP7", "GEN_VOLT_24", "GEN_VOLT_15",
            "GEN_VOLT_M15", "GEN_VOLT_12", "GEN_VOLT_5", "GEN_CONT_LOOP"
        ]);
        if (validTps.has(id)) return id;

        if (/\b(TP2|INTERLOCK\s*(?:283|2\b)|DOOR|E-?STOP)\b/i.test(id)) return "TP2";
        if (/\b(FS1|24V|PSU)\b/i.test(id)) return "GEN_VOLT_24";
        if (/\b(TP7)\b/i.test(id)) return "TP7";
        if (/\b(TP_DOSE1|DOSE\s*1)\b/i.test(id)) return "TP_DOSE1";
        if (/\b(TP_DOSE2|DOSE\s*2)\b/i.test(id)) return "TP_DOSE2";
        if (/\b(GUN|FILAMENT)\b/i.test(id)) return "TP_GUN";
        if (/\b(TP_VAC|VAC\w*|VAC_ION|ITEM\s*112)\b/i.test(id)) return "TP_VAC";
        if (/\b(TP100|DOS(?:E|IS)\w*|ION\s*CHAMBER)\b/i.test(id)) return "TP100";
        if (/\b(TP_HT|MODULAT\w*|PFN|HT(?:\s*SUPPLY)?)\b/i.test(id)) return "TP_HT";
        if (/\b(TP3|THYRATRON|PCB\s*(?:22|3\b)|ITEM\s*474|PULSE)\b/i.test(id)) return "TP3";
        if (/\b(TP_RF|RF|MAGNETRON|KLYSTRON)\b/i.test(id)) return "TP_RF";
        if (/\b(TP_SPEED|SPEED|TACHO|TG1)\b/i.test(id)) return "TP_SPEED";
        if (/\b(TP_POS|POS|GANTRY|ENCODER)\b/i.test(id)) return "TP_POS";
        if (/\b(TP5|PCB\s*(?:16N?|5\b)|16N|RELAY\s*K[12]|K1|K2|W12)\b/i.test(id)) return "TP5";
        if (/\b(TP1|SAFETY\s*CHAIN|INTERLOCK\s*CHAIN)\b/i.test(id)) return "TP1";
        if (/\b(GEN_CONT_LOOP|CONTINUITY|LOOP\s*CONT)\b/i.test(id)) return "GEN_CONT_LOOP";
        if (/\b(GEN_VOLT_15|\+?15V(?:\s*DC)?)\b/i.test(id)) return "GEN_VOLT_15";
        if (/\b(GEN_VOLT_M15|-15V(?:\s*DC)?)\b/i.test(id)) return "GEN_VOLT_M15";
        if (/\b(GEN_VOLT_12|\+?12V(?:\s*DC)?)\b/i.test(id)) return "GEN_VOLT_12";
        if (/\b(GEN_VOLT_5|\+?5V(?:\s*DC)?|TTL)\b/i.test(id)) return "GEN_VOLT_5";
        return null;
    }
}

document.addEventListener("DOMContentLoaded", () => {
    const dropZone = document.getElementById("logDropZone");
    if (dropZone) {
        dropZone.addEventListener("dragover", (e) => {
            e.stopPropagation();
            e.preventDefault();
            e.dataTransfer.dropEffect = "copy";
        });
        dropZone.addEventListener("drop", LogParser.handleFileSelect);
    }
    
    const fileInput = document.getElementById("logFileInput");
    if (fileInput) {
        fileInput.addEventListener("change", LogParser.handleFileSelect);
    }

    const entriesContainer = document.getElementById("logEntriesContainer");
    if (entriesContainer) {
        entriesContainer.addEventListener("click", (e) => {
            const btn = e.target.closest("[data-log-action]");
            if (!btn) return;
            e.preventDefault();
            const act = btn.dataset.logAction;
            if (act === "search") LogParser.actionSearch(btn.dataset.target);
            else if (act === "circuits") LogParser.actionCircuits(btn.dataset.target);
            else if (act === "multimeter") LogParser.actionMultimeter(btn.dataset.target);
            else if (act === "export-notes") LogParser.exportToNotes(parseInt(btn.dataset.idx, 10));
            else if (act === "diagnose") LogParser.actionDiagnose(btn.dataset.target);
        });
    }
});
