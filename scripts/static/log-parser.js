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

    static parseTimestamp(ts_str) {
        if (!ts_str) return 0.0;
        let match = ts_str.match(/\b\d{13}\b/);
        if (match) return parseFloat(match[0]) / 1000.0;

        match = ts_str.match(/(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?/);
        if (match) {
            let [_, y, m, d, h, min, s, ms] = match;
            let dObj = new Date(`${y}-${m}-${d}T${h}:${min}:${s}.${ms?ms.substring(0,3):'000'}Z`);
            return dObj.getTime() / 1000.0;
        }
        match = ts_str.match(/(\d{2})\/(\d{2})\/(\d{4}) (\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?/);
        if (match) {
            let [_, p1, p2, y, h, min, s, ms] = match;
            let p1Int = parseInt(p1, 10);
            let d = p1, m = p2;
            if (p1Int <= 12) {
                m = p1; d = p2;
            }
            let dObj = new Date(`${y}-${m}-${d}T${h}:${min}:${s}.${ms?ms.substring(0,3):'000'}Z`);
            return dObj.getTime() / 1000.0;
        }
        return 0.0;
    }

    static parseChunk(lines, startIndex) {
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
                ts_val = this.parseTimestamp(ts_str);
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
                identifiers: ids
            });
        }
        return events;
    }

    static async parseFileClientSide(file) {
        return new Promise((resolve, reject) => {
            const chunkSize = 1024 * 1024;
            let offset = 0;
            let events = [];
            let remainingString = "";
            let totalLines = 0;

            const reader = new FileReader();
            
            const renderProgress = (processed) => {
                const el = document.getElementById("logParsingSpinner");
                if (el) {
                    let msg = el.querySelector("p");
                    if (msg) msg.textContent = `Procesando archivo: ${Math.round((processed / file.size) * 100)}%`;
                }
            };

            reader.onload = function(e) {
                let text = remainingString + e.target.result;
                let lines = text.split(/\r?\n/);
                remainingString = lines.pop();

                events = events.concat(LogParser.parseChunk(lines, totalLines));
                totalLines += lines.length;

                offset += chunkSize;
                renderProgress(Math.min(offset, file.size));

                if (offset < file.size) {
                    setTimeout(() => readNextChunk(), 0);
                } else {
                    if (remainingString) {
                        events = events.concat(LogParser.parseChunk([remainingString], totalLines));
                        totalLines++;
                    }
                    resolve(LogParser.aggregate(events, totalLines));
                }
            };
            
            reader.onerror = () => reject(reader.error);

            function readNextChunk() {
                let slice = file.slice(offset, offset + chunkSize);
                reader.readAsText(slice);
            }

            readNextChunk();
        });
    }

    static aggregate(events, totalLines) {
        events.sort((a, b) => a.timestamp - b.timestamp);
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
                if (ev.timestamp - current_cascade[0].timestamp <= 2.0) {
                    current_cascade.push(ev);
                } else {
                    cascades.push(current_cascade);
                    current_cascade = [ev];
                }
            }
        }
        if (current_cascade.length > 0) cascades.push(current_cascade);

        return { ok: true, total_lines: totalLines, events, cascades, summary };
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
                html += `<p style="font-size:0.8rem; margin:5px 0;"><strong>Causa Raíz:</strong> ${rootEvent.timestamp_str} - ${rootEvent.severity} - ${rootEvent.identifiers.join(", ")}</p>`;
                
                const primaryId = identifiers[0] || '';
                const suggestedTp = LogParser.mapIdentifierToTP(primaryId);
                
                html += `<div style="display:flex;gap:5px;flex-wrap:wrap;margin-top:10px;">
                    <button class="btn btn-ghost btn-sm" onclick="irA('Search'); document.getElementById('q').value='${primaryId}'; buscar();">🔍 Ver en Manuales</button>
                    <button class="btn btn-ghost btn-sm" onclick="irA('Circuits'); if(window.CircuitVisualizer) window.CircuitVisualizer.buscarEnEsquema('${primaryId}');">⚡ Ver en Esquema SVG</button>
                    <button class="btn btn-ghost btn-sm" onclick="irA('Multimeter'); if (window.dmmSelTp) window.dmmSelTp('${suggestedTp}');">📟 Medir con Multímetro (${suggestedTp})</button>
                    <button class="btn btn-primary btn-sm" onclick="LogParser.exportToNotes(${idx})">📝 Exportar a Mis Apuntes</button>
                    <button class="btn btn-ghost btn-sm" onclick="irA('Diagnose'); let inputs = document.querySelectorAll('.symptom-input'); if(inputs.length > 0) inputs[0].value='${primaryId}'; if(window.ejecutarTrazaGrafo) window.ejecutarTrazaGrafo();">🧭 Ver Traza Topológica</button>
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
            let pageSize = 500;
            let rendered = 0;
            const eventsToRender = data.events.filter(e => e.severity === "FATAL" || e.severity === "ERROR" || e.severity === "WARNING");
            
            if (eventsToRender.length === 0) {
                viewer.innerHTML = `<span style="color:var(--muted)">No hay errores, advertencias o eventos críticos para mostrar.</span>`;
            }
            
            const renderPage = () => {
                let toRender = eventsToRender.slice(rendered, rendered + pageSize);
                if (toRender.length === 0) return;
                
                let df = document.createDocumentFragment();
                for (let ev of toRender) {
                    let d = document.createElement("div");
                    d.style.marginBottom = "4px";
                    d.style.padding = "4px";
                    d.style.borderBottom = "1px solid var(--border)";
                    let color = ev.severity === "FATAL" ? "var(--danger)" : (ev.severity === "ERROR" ? "var(--warn)" : "var(--accent)");
                    d.innerHTML = `<span style="color:${color}; width:60px; display:inline-block;">${ev.severity}</span> 
                                   <span style="color:var(--muted); margin-right:10px;">${ev.timestamp_str}</span> 
                                   ${ev.raw.replace(/</g, "&lt;").replace(/>/g, "&gt;")}`;
                    df.appendChild(d);
                }
                viewer.appendChild(df);
                rendered += pageSize;
            };
            
            renderPage();
            viewer.addEventListener("scroll", () => {
                if (viewer.scrollTop + viewer.clientHeight >= viewer.scrollHeight - 50) {
                    renderPage();
                }
            });
        }
    }
    
    static exportToNotes(cascadeIdx) {
        if (!window._currentLogData) return;
        const cascade = window._currentLogData.cascades[cascadeIdx];
        if (!cascade) return;
        
        const rootEvent = cascade[0];
        const identifiers = [...new Set(cascade.flatMap(e => e.identifiers))].join(", ");
        
        const noteText = `Análisis Cronológico de Secuencia de Falla\n\nCascada iniciada: ${rootEvent.timestamp_str}\nSeveridad: ${rootEvent.severity}\nComponentes/IDs involucrados: ${identifiers}\n\nDetalle eventos:\n` +
            cascade.map(e => `- ${e.timestamp_str}: ${e.raw}`).join("\n");
            
        irA('Notes');
        if (typeof abrirFormNota === 'function') {
            abrirFormNota();
            setTimeout(() => {
                document.getElementById('notaTit').value = "Falla detectada: " + (identifiers.split(",")[0] || "Desconocida");
                document.getElementById('notaTxt').value = noteText;
                document.getElementById('notaTags').value = "log, cascade";
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
        
        document.getElementById("logParsingSpinner").style.display = "block";
        document.getElementById("logResults").innerHTML = "";
        
        try {
            const data = await LogParser.parseFileClientSide(f);
            LogParser.renderResults(data);
        } catch (err) {
            alert("Error analizando el archivo: " + err);
        } finally {
            document.getElementById("logParsingSpinner").style.display = "none";
        }
    }
    
    static async handlePaste() {
        const text = document.getElementById("logPasteArea").value;
        if (!text.trim()) return;
        
        document.getElementById("logParsingSpinner").style.display = "block";
        document.getElementById("logResults").innerHTML = "";
        
        try {
            let lines = text.split(/\r?\n/);
            let events = LogParser.parseChunk(lines, 0);
            let data = LogParser.aggregate(events, lines.length);
            LogParser.renderResults(data);
        } catch (err) {
            alert("Error analizando el texto: " + err);
        } finally {
            document.getElementById("logParsingSpinner").style.display = "none";
        }
    }
    
    static loadSample() {
        const sample = `2026-09-15 10:55:57.123 INFO Iniciando sistema
2026-09-15 10:55:58.000 WARNING Dosis rate mismatch
2026-09-15 10:55:58.500 ERROR ITEM 112 failed
2026-09-15 10:55:58.800 FATAL INTERLOCK 283 tripped cascade
2026-09-15 10:55:59.100 FATAL W12 signal lost
2026-09-15 10:56:10.000 INFO Recovery started`;
        document.getElementById("logPasteArea").value = sample;
        LogParser.handlePaste();
    }

    static mapIdentifierToTP(identifier) {
        if (!identifier) return "TP1";
        const id = String(identifier).toUpperCase();
        if (id.includes("283") || id.includes("DOOR") || id.includes("INTERLOCK 2")) return "TP2";
        if (id.includes("FS1") || id.includes("24V") || id.includes("PSU")) return "GEN_VOLT_24";
        if (id.includes("GUN") || id.includes("FILAMENT")) return "TP_GUN";
        if (id.includes("VAC") || id.includes("VAC_ION")) return "TP_VAC";
        if (id.includes("DOSE") || id.includes("DOSIS") || id.includes("100")) return "TP100";
        if (id.includes("HT") || id.includes("MODULAT") || id.includes("PFN")) return "TP_HT";
        if (id.includes("3") || id.includes("PULSE") || id.includes("THYRATRON")) return "TP3";
        if (id.includes("RF")) return "TP_RF";
        if (id.includes("SPEED") || id.includes("TACHO")) return "TP_SPEED";
        if (id.includes("POS") || id.includes("GANTRY")) return "TP_POS";
        if (id.includes("16N") || id.includes("K1") || id.includes("K2") || id.includes("5")) return "TP5";
        return "TP1";
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
});
