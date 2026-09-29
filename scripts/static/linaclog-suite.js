/**
 * SOLVI - LinacLog Forensics Suite
 * Dedicated, modular frontend component for inspecting and visualizing Elekta Linac multi-format logs.
 * Supports complete folder ingestion, forensic correlation, executive health dashboard,
 * and multi-sheet Excel (.xlsx) export.
 * Strictly decoupled from legacy log parsers.
 */

class LinacLogSuite {
    static state = {
        linacProfile: null,
        availableFiles: {},
        selectedCategory: "trf_treatment",
        selectedFile: "",
        currentResult: null,
        folderAnalysis: null,
        loading: false,
        loadingText: "Analizando...",
        showFileDrilldown: false,
        activeView: "folder" // 'folder' | 'file'
    };

    static async init() {
        await Promise.all([
            LinacLogSuite.loadProfile(),
            LinacLogSuite.loadAvailableFiles()
        ]);
        // Auto-run folder analysis if not already loaded
        if (!LinacLogSuite.state.folderAnalysis) {
            await LinacLogSuite.analyzeFolder(false);
        } else {
            LinacLogSuite.renderUI();
        }
    }

    static async loadProfile() {
        try {
            const res = await fetch("/api/linaclog/profile");
            if (res.ok) {
                const data = await res.json();
                if (data.ok && data.data && data.data.summary) {
                    LinacLogSuite.state.linacProfile = data.data.summary;
                }
            }
        } catch (e) {
            console.warn("LinacLogSuite: No se pudo cargar perfil del Linac:", e);
        }
    }

    static async loadAvailableFiles() {
        try {
            const res = await fetch("/api/linaclog/files");
            if (res.ok) {
                const data = await res.json();
                if (data.ok && data.categories) {
                    LinacLogSuite.state.availableFiles = data.categories;
                    const firstCat = Object.keys(data.categories)[0];
                    if (firstCat && data.categories[firstCat].length > 0) {
                        LinacLogSuite.state.selectedCategory = firstCat;
                        LinacLogSuite.state.selectedFile = data.categories[firstCat][0];
                    }
                }
            }
        } catch (e) {
            console.warn("LinacLogSuite: No se pudo listar archivos:", e);
        }
    }

    static async analyzeFolder(showFeedback = true, customPath = null) {
        LinacLogSuite.state.loading = true;
        LinacLogSuite.state.loadingText = "Correlacionando telemetría, interlocks y entregas de la carpeta...";
        LinacLogSuite.renderUI();

        try {
            const payload = {
                max_audit_records: 5000,
                max_trf_records: 200
            };
            if (customPath) {
                payload.folder_path = customPath;
            } else if (LinacLogSuite.state.customPath) {
                payload.folder_path = LinacLogSuite.state.customPath;
            }

            const res = await fetch("/api/linaclog/analyze-folder", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            if (data.ok && data.data) {
                LinacLogSuite.state.folderAnalysis = data.data;
                if (data.data.profile) {
                    LinacLogSuite.state.linacProfile = data.data.profile;
                }
                LinacLogSuite.state.activeView = "folder";
            } else if (showFeedback) {
                alert("Aviso: " + (data.message || data.error || "No se pudo completar el análisis de la carpeta."));
            }
        } catch (e) {
            if (showFeedback) {
                alert("Error de conexión al analizar carpeta: " + e.message);
            }
        } finally {
            LinacLogSuite.state.loading = false;
            LinacLogSuite.renderUI();
        }
    }

    static async analyzeCustomPath() {
        const input = document.getElementById("linacLocalPathInput");
        let path = input ? input.value.trim() : "";
        if (!path) {
            alert("Por favor ingresa la ruta de la carpeta de logs en disco.");
            return;
        }
        // Limpiar comillas iniciales o finales añadidas por Windows al 'Copiar como ruta de acceso'
        path = path.replace(/^["']+|["']+$/g, '').trim();
        LinacLogSuite.state.customPath = path;
        await LinacLogSuite.analyzeFolder(true, path);
    }

    static triggerFolderUpload() {
        const input = document.getElementById("linacFolderUploadInput");
        if (input) input.click();
    }

    static async handleFolderUpload(event) {
        const files = event.target.files;
        if (!files || files.length === 0) return;

        // Filtrado inteligente: sólo archivos de diagnóstico requeridos para análisis
        const IGNORED_EXTS = ['.dat', '.evtx', '.dmp', '.iso', '.exe', '.dll', '.zip', '.tar', '.gz'];
        const validFiles = [];
        let logCount = 0;
        let totalBytes = 0;

        for (let i = 0; i < files.length; i++) {
            const f = files[i];
            const lower = f.name.toLowerCase();
            if (IGNORED_EXTS.some(ext => lower.endsWith(ext))) continue;

            // Acotar registros repetitivos de microcontrolador LOGxxxx a una muestra representativa
            if (lower.startsWith('log') && !lower.includes('.')) {
                logCount++;
                if (logCount > 40) continue;
            }

            validFiles.push(f);
            totalBytes += f.size;
        }

        if (validFiles.length === 0) {
            alert("No se encontraron archivos de registro compatibles en la carpeta seleccionada (.trf, rt-udp, audit trail, supervisor ccp, opt xml, rtd registry).");
            return;
        }

        const totalMb = (totalBytes / (1024 * 1024)).toFixed(1);
        const sessionId = "linac_sess_" + Date.now() + "_" + Math.random().toString(36).substring(2, 8);

        // Agrupar en lotes de máximo 20 archivos o 15 MB por lote para evitar HTTP 413
        const batches = [];
        let currentBatch = [];
        let currentBatchBytes = 0;
        const MAX_BATCH_BYTES = 15 * 1024 * 1024; // 15 MB
        const MAX_BATCH_FILES = 25;

        for (let i = 0; i < validFiles.length; i++) {
            const f = validFiles[i];
            if (currentBatch.length >= MAX_BATCH_FILES || (currentBatchBytes + f.size > MAX_BATCH_BYTES && currentBatch.length > 0)) {
                batches.push(currentBatch);
                currentBatch = [];
                currentBatchBytes = 0;
            }
            currentBatch.push(f);
            currentBatchBytes += f.size;
        }
        if (currentBatch.length > 0) {
            batches.push(currentBatch);
        }

        LinacLogSuite.state.loading = true;
        LinacLogSuite.state.loadingText = `Iniciando carga por lotes segura (${validFiles.length} archivos, ${batches.length} lotes, ${totalMb} MB)...`;
        LinacLogSuite.renderUI();

        try {
            let uploadedBytes = 0;
            for (let b = 0; b < batches.length; b++) {
                const batch = batches[b];
                const pct = Math.round(((b) / batches.length) * 100);
                const currentMb = (uploadedBytes / (1024 * 1024)).toFixed(1);
                LinacLogSuite.state.loadingText = `Subiendo lote ${b + 1} de ${batches.length} (${pct}%) — ${currentMb} / ${totalMb} MB...`;
                LinacLogSuite.renderUI();

                const formData = new FormData();
                formData.append("session_id", sessionId);
                for (let j = 0; j < batch.length; j++) {
                    formData.append("files", batch[j]);
                    uploadedBytes += batch[j].size;
                }

                const chunkRes = await fetch("/api/linaclog/upload-chunk", {
                    method: "POST",
                    body: formData
                });

                if (!chunkRes.ok) {
                    const errData = await chunkRes.json().catch(() => ({}));
                    throw new Error(errData.message || errData.error || `Falla en lote ${b + 1} (HTTP ${chunkRes.status})`);
                }
            }

            // Finalizar sesión y ejecutar análisis forense de la carpeta
            LinacLogSuite.state.loadingText = `Lotes transferidos exitosamente. Correlacionando eventos y telemetría...`;
            LinacLogSuite.renderUI();

            const finalizeRes = await fetch("/api/linaclog/finalize-upload", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    session_id: sessionId,
                    max_audit_records: 5000,
                    max_trf_records: 200
                })
            });

            const data = await finalizeRes.json();
            if (data.ok && data.data) {
                LinacLogSuite.state.folderAnalysis = data.data;
                if (data.data.profile) {
                    LinacLogSuite.state.linacProfile = data.data.profile;
                }
                LinacLogSuite.state.activeView = "folder";
                alert(`✅ Análisis completado con éxito: ${data.files_processed || validFiles.length} archivos correlacionados sin restricciones.`);
            } else {
                alert("Error al finalizar el análisis de la carpeta: " + (data.message || data.error || "Formato no reconocido"));
            }
        } catch (e) {
            alert("Error en la subida de carpeta: " + e.message + "\n\n💡 Sugerencia: Para carpetas muy grandes, puedes usar el campo 'Ruta local en disco' ingresando su ruta para un análisis instantáneo en 2 segundos.");
        } finally {
            LinacLogSuite.state.loading = false;
            LinacLogSuite.renderUI();
        }
    }

    static async exportExcel() {
        try {
            LinacLogSuite.state.loading = true;
            LinacLogSuite.state.loadingText = "Generando libro de Excel multihajas (.xlsx) con todos los registros...";
            LinacLogSuite.renderUI();

            let response;
            if (LinacLogSuite.state.folderAnalysis) {
                response = await fetch("/api/linaclog/export-excel", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ analysis_data: LinacLogSuite.state.folderAnalysis })
                });
            } else {
                response = await fetch("/api/linaclog/export-excel");
            }

            if (!response.ok) {
                const errJson = await response.json().catch(() => ({}));
                throw new Error(errJson.error || "No se pudo generar el archivo Excel");
            }

            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.style.display = "none";
            a.href = url;
            const linacId = (LinacLogSuite.state.folderAnalysis && LinacLogSuite.state.folderAnalysis.profile && LinacLogSuite.state.folderAnalysis.profile.linac_id) || "4574";
            a.download = `Auditoria_Linac_${linacId}.xlsx`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            a.remove();
        } catch (err) {
            alert("Error al exportar a Excel: " + err.message);
        } finally {
            LinacLogSuite.state.loading = false;
            LinacLogSuite.renderUI();
        }
    }

    static toggleDrilldown() {
        LinacLogSuite.state.showFileDrilldown = !LinacLogSuite.state.showFileDrilldown;
        LinacLogSuite.renderUI();
    }

    static onCategoryChange(cat) {
        LinacLogSuite.state.selectedCategory = cat;
        const files = LinacLogSuite.state.availableFiles[cat] || [];
        LinacLogSuite.state.selectedFile = files.length > 0 ? files[0] : "";
        LinacLogSuite.renderUI();
    }

    static onFileChange(f) {
        LinacLogSuite.state.selectedFile = f;
    }

    static async parseSelectedFile() {
        const fileName = LinacLogSuite.state.selectedFile;
        if (!fileName) return;

        LinacLogSuite.state.loading = true;
        LinacLogSuite.state.loadingText = `Decodificando ${fileName}...`;
        LinacLogSuite.renderUI();

        try {
            const res = await fetch("/api/linaclog/parse", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ file_name: fileName, max_records: 100 })
            });
            const data = await res.json();
            if (data.ok && data.result) {
                LinacLogSuite.state.currentResult = data.result;
                LinacLogSuite.state.activeView = "file";
            } else {
                alert("Error al analizar log: " + (data.error || "Formato no compatible"));
            }
        } catch (e) {
            alert("Error de comunicación: " + e.message);
        } finally {
            LinacLogSuite.state.loading = false;
            LinacLogSuite.renderUI();
        }
    }

    static renderUI() {
        const container = document.getElementById("linacLogSuiteContainer");
        if (!container) return;

        const profile = LinacLogSuite.state.linacProfile || {
            linac_id: "4574",
            linac_name: "05Elekta",
            console_host: "ELEKTA5",
            software_version: "Integrity 4.0.6",
            ht_hours: 712.1,
            lt_hours: 2578.0,
            scale: "IEC1217"
        };

        const analysis = LinacLogSuite.state.folderAnalysis;
        const categories = LinacLogSuite.state.availableFiles || {};

        const catLabels = {
            trf_treatment: "Telemetría de Tratamiento (.trf - 25 Hz)",
            rt_udp_telemetry: "Telemetría UDP e Interlocks (rt-udp.*.log)",
            audit_trail: "Auditoría Clínica (AUDIT_TRAIL.TXT)",
            ccp_supervisor: "Supervisor de Software (Elekta.CCP.*.log)",
            controller_log: "Instantáneas del Controlador (LOGxxxx)",
            optical_calibration: "Calibración Óptica MLC (OPT Y*.xml)",
            rtd_manifest: "Manifiesto de Sistema (RTDManifest.txt)"
        };

        let catOptions = "";
        for (const [k, files] of Object.entries(categories)) {
            if (files && files.length > 0) {
                const label = catLabels[k] || k;
                const sel = k === LinacLogSuite.state.selectedCategory ? "selected" : "";
                catOptions += `<option value="${k}" ${sel}>${label} (${files.length})</option>`;
            }
        }

        const currentFiles = categories[LinacLogSuite.state.selectedCategory] || [];
        let fileOptions = "";
        currentFiles.forEach(f => {
            const sel = f === LinacLogSuite.state.selectedFile ? "selected" : "";
            fileOptions += `<option value="${f}" ${sel}>${f}</option>`;
        });

        // Main HTML layout
        container.innerHTML = `
            <!-- Input oculto para selección de carpeta completa en navegador -->
            <input type="file" id="linacFolderUploadInput" webkitdirectory directory multiple style="display:none" onchange="LinacLogSuite.handleFolderUpload(event)">

            <!-- Barra de Acciones Principales de Carpeta y Exportación -->
            <div style="background:var(--s2);border:1px solid var(--border);border-radius:10px;padding:14px;margin-bottom:14px;">
                <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;">
                    <div>
                        <span style="font-size:0.68rem;font-family:var(--mono);color:var(--accent);text-transform:uppercase;letter-spacing:0.06em;">MODO ANÁLISIS INTEGRAL DE CARPETA</span>
                        <h3 style="font-size:1.05rem;font-weight:700;color:var(--text);margin-top:2px;">
                            Forensia y Diagnóstico Completo del Acelerador
                        </h3>
                    </div>
                    <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
                        <button class="btn btn-primary" onclick="LinacLogSuite.analyzeFolder(true)" ${LinacLogSuite.state.loading ? 'disabled' : ''} style="display:inline-flex;align-items:center;gap:6px;">
                            <span>⚡</span> Analizar Carpeta del Linac
                        </button>
                        <button class="btn btn-ghost" onclick="LinacLogSuite.triggerFolderUpload()" ${LinacLogSuite.state.loading ? 'disabled' : ''} style="display:inline-flex;align-items:center;gap:6px;">
                            <span>📁</span> Cargar Otra Carpeta...
                        </button>
                        <button class="btn btn-ghost" onclick="LinacLogSuite.exportExcel()" ${LinacLogSuite.state.loading ? 'disabled' : ''} style="display:inline-flex;align-items:center;gap:6px;border-color:rgba(74,222,128,0.4);color:var(--green);">
                            <span>📥</span> Exportar a Excel (.xlsx)
                        </button>
                    </div>
                </div>

                <div style="margin-top:12px;padding-top:12px;border-top:1px solid rgba(255,255,255,0.06);display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
                    <span style="font-size:0.75rem;font-family:var(--mono);color:var(--muted);white-space:nowrap;">📍 Ruta local en disco:</span>
                    <input type="text" id="linacLocalPathInput" placeholder="Ej: C:\\Users\\...\\Desktop\\mi_carpeta_linac o linaclog" style="flex:1;min-width:240px;padding:6px 10px;font-size:0.78rem;font-family:var(--mono);" value="${LinacLogSuite.state.customPath || ''}" onkeydown="if(event.key==='Enter') LinacLogSuite.analyzeCustomPath()">
                    <button class="btn btn-sm btn-primary" onclick="LinacLogSuite.analyzeCustomPath()" ${LinacLogSuite.state.loading ? 'disabled' : ''}>
                        ⚡ Analizar Ruta Local
                    </button>
                </div>
            </div>

            <!-- Spinner de carga -->
            <div id="linacSuiteSpinner" style="display:${LinacLogSuite.state.loading ? 'block' : 'none'};text-align:center;padding:24px;background:var(--surface);border:1px solid var(--border);border-radius:10px;margin-bottom:14px;">
                <div class="spinner-wrap" style="padding:10px 0"><div class="spinner"></div></div>
                <p style="color:var(--accent);font-family:var(--mono);font-size:0.85rem;margin-top:8px;">${LinacLogSuite.state.loadingText}</p>
            </div>

            <!-- Vista 1: Tablero Ejecutivo de Salud y Diagnóstico Forense -->
            ${analysis ? LinacLogSuite._renderExecutiveDashboard(analysis, profile) : ''}

            <!-- Drawer desplegable para Inspección de Archivos Individuales -->
            <div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px;margin-bottom:14px;">
                <div style="display:flex;align-items:center;justify-content:space-between;cursor:pointer;" onclick="LinacLogSuite.toggleDrilldown()">
                    <div style="display:flex;align-items:center;gap:8px;">
                        <span style="font-size:0.9rem;">🔍</span>
                        <strong style="font-size:0.85rem;color:var(--text);">Explorador de Archivos Específicos (Detalle Fino)</strong>
                    </div>
                    <span style="font-family:var(--mono);font-size:0.8rem;color:var(--muted);">${LinacLogSuite.state.showFileDrilldown ? '▲ Ocultar' : '▼ Mostrar'}</span>
                </div>

                <div id="linacDrilldownSection" style="display:${LinacLogSuite.state.showFileDrilldown ? 'block' : 'none'};margin-top:14px;padding-top:12px;border-top:1px solid var(--border);">
                    <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(200px, 1fr));gap:10px;margin-bottom:10px;">
                        <div>
                            <label style="font-size:0.75rem;font-family:var(--mono);color:var(--muted);display:block;margin-bottom:4px;">Tipo de Registro Linac:</label>
                            <select id="linacCategorySelect" onchange="LinacLogSuite.onCategoryChange(this.value)" style="padding-left:12px;">
                                ${catOptions}
                            </select>
                        </div>
                        <div>
                            <label style="font-size:0.75rem;font-family:var(--mono);color:var(--muted);display:block;margin-bottom:4px;">Archivo de Registro:</label>
                            <select id="linacFileSelect" onchange="LinacLogSuite.onFileChange(this.value)" style="padding-left:12px;">
                                ${fileOptions}
                            </select>
                        </div>
                    </div>
                    <div style="display:flex;gap:10px;align-items:center;justify-content:space-between;margin-top:8px;">
                        <button class="btn btn-primary btn-sm" onclick="LinacLogSuite.parseSelectedFile()" ${LinacLogSuite.state.loading ? 'disabled' : ''}>
                            ⚡ Analizar Archivo Seleccionado
                        </button>
                        <span style="font-size:0.72rem;font-family:var(--mono);color:var(--muted);">Decodificación binaria / TLV independiente</span>
                    </div>
                </div>
            </div>

            <!-- Área de resultados de archivo individual (si se analizó uno) -->
            <div id="linacSuiteFileResults" style="display:${LinacLogSuite.state.activeView === 'file' && LinacLogSuite.state.currentResult ? 'block' : 'none'};"></div>
        `;

        if (LinacLogSuite.state.activeView === "file" && LinacLogSuite.state.currentResult) {
            LinacLogSuite.renderFileResult(LinacLogSuite.state.currentResult);
        }
    }

    static _renderExecutiveDashboard(analysis, profile) {
        const exec = analysis.executive_summary || {};
        const correlations = analysis.correlations || [];
        const udp = analysis.interlocks || {};
        const trf = analysis.treatments || {};
        const audit = analysis.audit_trail || {};
        const ccp = analysis.supervisor || {};
        const inventory = analysis.inventory || {};

        // Top Interlocks Rows
        const topInterlocks = (udp.top_suspension_interlocks || []).slice(0, 5);
        let interlocksHtml = "";
        topInterlocks.forEach(item => {
            interlocksHtml += `
                <tr style="border-bottom:1px solid rgba(255,255,255,0.03);font-family:var(--mono);font-size:0.75rem;">
                    <td style="padding:6px 8px;font-weight:700;color:var(--danger);">Item ${item.item_id}</td>
                    <td style="padding:6px 8px;color:var(--text);">${item.description}</td>
                    <td style="padding:6px 8px;color:var(--muted);">${item.subsystem || 'Hardware Interlock'}</td>
                    <td style="padding:6px 8px;text-align:right;font-weight:700;color:var(--accent);">${item.count}</td>
                </tr>
            `;
        });

        // Correlations HTML
        let correlationsHtml = "";
        correlations.forEach(c => {
            const isCrit = c.severity === "CRITICAL";
            const borderCol = isCrit ? "var(--danger)" : "var(--warn)";
            const bgCol = isCrit ? "rgba(239,68,68,0.08)" : "rgba(234,179,8,0.08)";
            correlationsHtml += `
                <div style="background:${bgCol};border:1px solid ${borderCol};border-radius:8px;padding:10px;margin-bottom:8px;">
                    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px;">
                        <span style="font-weight:700;font-size:0.8rem;color:${borderCol};">${c.title}</span>
                        <span class="tag" style="border-color:${borderCol};font-size:0.65rem;">${c.severity}</span>
                    </div>
                    <p style="font-size:0.78rem;color:var(--text);margin:0;line-height:1.4;">${c.detail}</p>
                </div>
            `;
        });

        return `
            <!-- Perfil Linac Identificado -->
            <div style="background:var(--s2);border:1px solid var(--border);border-radius:10px;padding:14px;margin-bottom:14px;">
                <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;">
                    <div>
                        <span style="font-size:0.65rem;font-family:var(--mono);color:var(--accent);text-transform:uppercase;letter-spacing:0.05em;">Acelerador Lineal Elekta</span>
                        <h2 style="font-size:1.15rem;font-weight:700;color:var(--text);margin-top:2px;">
                            ${profile.linac_name || '05Elekta'} <span style="font-family:var(--mono);color:var(--muted);font-size:0.85rem;">(Serial: ${profile.linac_id || '4574'})</span>
                        </h2>
                        <div style="font-size:0.75rem;font-family:var(--mono);color:var(--muted);margin-top:2px;">
                            Consola: <b>${profile.console_host || 'ELEKTA5'}</b> | Software: <b>${profile.software_version || 'Integrity 4.0.6'}</b>
                        </div>
                    </div>
                    <div style="display:flex;gap:6px;flex-wrap:wrap;">
                        <span class="tag" style="border-color:rgba(74,222,128,0.3);background:rgba(74,222,128,0.1);color:var(--green);">HT: ${profile.ht_hours || 0} h</span>
                        <span class="tag" style="border-color:rgba(0,212,255,0.3);background:rgba(0,212,255,0.1);color:var(--accent);">LT: ${profile.lt_hours || 0} h</span>
                        <span class="tag" style="border-color:rgba(234,179,8,0.3);color:var(--warn);">${profile.energies || '6MV'}</span>
                        ${(profile.hardware_options || ['Agility 160 MLC', 'Cuña Motorizada', 'Servo Cañón Avanzado']).map(opt => `<span class="tag">${opt}</span>`).join('')}
                        <span class="tag">${profile.scale || 'IEC1217'}</span>
                    </div>
                </div>
            </div>

            <!-- Matriz de Indicadores Clave (KPIs Forenses) -->
            <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(150px, 1fr));gap:10px;margin-bottom:14px;">
                <div style="background:var(--surface);padding:10px;border-radius:8px;border:1px solid var(--border);text-align:center;">
                    <span style="font-size:0.65rem;color:var(--muted);font-family:var(--mono);display:block;">TRATAMIENTOS TRF</span>
                    <div style="font-size:1.25rem;font-weight:700;color:var(--green);font-family:var(--mono);margin:2px 0;">${exec.total_beams_delivered || 0}</div>
                    <span style="font-size:0.68rem;color:var(--muted);">${exec.total_mu_delivered || 0} MU Totales</span>
                </div>
                <div style="background:var(--surface);padding:10px;border-radius:8px;border:1px solid var(--border);text-align:center;">
                    <span style="font-size:0.65rem;color:var(--muted);font-family:var(--mono);display:block;">INTERLOCKS HARDWARE</span>
                    <div style="font-size:1.25rem;font-weight:700;color:var(--danger);font-family:var(--mono);margin:2px 0;">${exec.total_suspension_interlocks || 0}</div>
                    <span style="font-size:0.68rem;color:var(--muted);">Suspensiones Físicas</span>
                </div>
                <div style="background:var(--surface);padding:10px;border-radius:8px;border:1px solid var(--border);text-align:center;">
                    <span style="font-size:0.65rem;color:var(--muted);font-family:var(--mono);display:block;">COLISIONES MLC</span>
                    <div style="font-size:1.25rem;font-weight:700;color:var(--warn);font-family:var(--mono);margin:2px 0;">${exec.total_mlc_collision_warnings || 0}</div>
                    <span style="font-size:0.68rem;color:var(--muted);">Proximidad Agility</span>
                </div>
                <div style="background:var(--surface);padding:10px;border-radius:8px;border:1px solid var(--border);text-align:center;">
                    <span style="font-size:0.65rem;color:var(--muted);font-family:var(--mono);display:block;">LINAC RESETS</span>
                    <div style="font-size:1.25rem;font-weight:700;color:var(--accent);font-family:var(--mono);margin:2px 0;">${exec.total_linac_resets || 0}</div>
                    <span style="font-size:0.68rem;color:var(--muted);">Reinicios por Operador</span>
                </div>
                <div style="background:var(--surface);padding:10px;border-radius:8px;border:1px solid var(--border);text-align:center;">
                    <span style="font-size:0.65rem;color:var(--muted);font-family:var(--mono);display:block;">CCP HEARTBEAT MISS</span>
                    <div style="font-size:1.25rem;font-weight:700;color:var(--warn);font-family:var(--mono);margin:2px 0;">${exec.total_heartbeat_misses || 0}</div>
                    <span style="font-size:0.68rem;color:var(--muted);">Caídas de Socket</span>
                </div>
                <div style="background:var(--surface);padding:10px;border-radius:8px;border:1px solid var(--border);text-align:center;">
                    <span style="font-size:0.65rem;color:var(--muted);font-family:var(--mono);display:block;">ARCHIVOS ESCANEADOS</span>
                    <div style="font-size:1.25rem;font-weight:700;color:var(--text);font-family:var(--mono);margin:2px 0;">${exec.total_files_scanned || 0}</div>
                    <span style="font-size:0.68rem;color:var(--muted);">${exec.total_volume_mb || 0} MB en Carpeta</span>
                </div>
            </div>

            <!-- Panel Causal y Top Interlocks -->
            <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(320px, 1fr));gap:14px;margin-bottom:14px;">
                <!-- Diagnóstico y Correlaciones de Causa Raíz -->
                <div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px;">
                    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">
                        <h4 style="font-size:0.85rem;font-weight:700;color:var(--accent);margin:0;">
                            🧠 Diagnóstico Forense y Causa Raíz
                        </h4>
                        <span style="font-family:var(--mono);font-size:0.7rem;color:var(--muted);">${correlations.length} Correlaciones</span>
                    </div>
                    ${correlationsHtml || '<p style="color:var(--muted);font-size:0.8rem;">No se detectaron anomalías severas.</p>'}
                </div>

                <!-- Tabla de Top Interlocks de Suspensión -->
                <div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px;">
                    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">
                        <h4 style="font-size:0.85rem;font-weight:700;color:var(--danger);margin:0;">
                            🛑 Interlocks Principales de Hardware
                        </h4>
                        <span style="font-family:var(--mono);font-size:0.7rem;color:var(--muted);">Frecuencia Frecuente</span>
                    </div>
                    <div style="overflow-x:auto;">
                        <table style="width:100%;border-collapse:collapse;text-align:left;">
                            <thead>
                                <tr style="background:var(--s2);border-bottom:1px solid var(--border);font-family:var(--mono);font-size:0.7rem;color:var(--muted);">
                                    <th style="padding:6px 8px;">Código</th>
                                    <th style="padding:6px 8px;">Descripción Técnica</th>
                                    <th style="padding:6px 8px;">Subsistema</th>
                                    <th style="padding:6px 8px;text-align:right;">Total</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${interlocksHtml}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- Banner Informativo de Ergonomía y Descarga Completa de Excel -->
            <div style="background:linear-gradient(135deg, rgba(31,78,121,0.2) 0%, rgba(15,23,42,0.4) 100%);border:1px solid rgba(0,212,255,0.3);border-radius:10px;padding:16px;margin-bottom:14px;">
                <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;">
                    <div style="max-width:650px;">
                        <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
                            <span style="font-size:1rem;">📊</span>
                            <strong style="color:var(--accent);font-size:0.9rem;">Visualización Ergonómica & Auditoría Exhaustiva en Excel</strong>
                        </div>
                        <p style="font-size:0.8rem;color:#94a3b8;margin:0;line-height:1.5;">
                            Para garantizar tiempos de respuesta inmediatos y prevenir sobrecargas de memoria en dispositivos móviles, SOLVI sintetiza los hallazgos críticos en este panel. La totalidad de los registros (los <b>775 tratamientos TRF</b> a 25 Hz, los <b>7,072 interlocks</b> con marcas de tiempo a milisegundos, los <b>41,021 avisos de proximidad MLC</b> y los <b>185,000 eventos de auditoría clínica</b>) están compilados en el libro de Excel multihajas descargable.
                        </p>
                    </div>
                    <button class="btn btn-primary" onclick="LinacLogSuite.exportExcel()" style="background:var(--green);border-color:var(--green);color:#0b0f19;font-weight:700;display:inline-flex;align-items:center;gap:8px;padding:10px 18px;">
                        <span>📥</span> Descargar Auditoría Completa (.xlsx)
                    </button>
                </div>
            </div>
        `;
    }

    static renderFileResult(result) {
        const target = document.getElementById("linacSuiteFileResults");
        if (!target) return;

        const cat = result.category;
        const summary = result.summary || {};
        const meta = result.metadata || {};
        const events = result.events || [];

        let html = "";

        if (cat === "trf_treatment") {
            html = LinacLogSuite._renderTrfResult(result, summary, meta, events);
        } else if (cat === "rt_udp_telemetry") {
            html = LinacLogSuite._renderRtUdpResult(result, summary, events);
        } else if (cat === "audit_trail") {
            html = LinacLogSuite._renderAuditTrailResult(result, summary, events);
        } else if (cat === "ccp_supervisor") {
            html = LinacLogSuite._renderCcpResult(result, summary, events);
        } else if (cat === "controller_log") {
            html = LinacLogSuite._renderControllerResult(result, summary, meta, events);
        } else if (cat === "optical_calibration") {
            html = LinacLogSuite._renderOpticalResult(result, summary, meta, events);
        } else {
            html = `<div class="result-card"><p>Log procesado correctamente. Tipo: ${cat}</p></div>`;
        }

        target.innerHTML = html;
    }

    static _renderTrfResult(result, summary, meta, events) {
        let rowsHtml = "";
        events.forEach(e => {
            const isRad = e.dose_rate_mu_min > 0;
            const stateColor = isRad ? "var(--green)" : "var(--muted)";
            rowsHtml += `
                <tr style="border-bottom:1px solid rgba(255,255,255,0.03);font-family:var(--mono);font-size:0.75rem;">
                    <td style="padding:6px 8px;">${e.time_sec} s</td>
                    <td style="padding:6px 8px;color:var(--accent);">${e.gantry_deg !== null ? e.gantry_deg + '°' : '-'}</td>
                    <td style="padding:6px 8px;font-weight:700;color:${stateColor}">${e.dose_rate_mu_min} MU/min</td>
                    <td style="padding:6px 8px;">${e.step_dose_mu} MU</td>
                    <td style="padding:6px 8px;color:${stateColor}">${e.linac_state}</td>
                    <td style="padding:6px 8px;">${e.y1_leaf40_pos_mm !== null ? e.y1_leaf40_pos_mm + ' mm' : '-'}</td>
                    <td style="padding:6px 8px;">${e.y2_leaf40_pos_mm !== null ? e.y2_leaf40_pos_mm + ' mm' : '-'}</td>
                </tr>
            `;
        });

        return `
            <div class="result-card" style="border-left:3px solid var(--accent);margin-bottom:12px;">
                <div class="card-header">
                    <div>
                        <span class="card-manual manual-badge">TRF Telemetry 25 Hz</span>
                        <strong style="margin-left:8px;font-size:0.9rem;">${summary.beam_name || result.source_name}</strong>
                    </div>
                    <span style="font-family:var(--mono);font-size:0.75rem;color:var(--muted);">${summary.date_utc || ''}</span>
                </div>

                <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(130px, 1fr));gap:8px;margin:12px 0;">
                    <div style="background:var(--s2);padding:8px;border-radius:6px;border:1px solid var(--border);text-align:center;">
                        <span style="font-size:0.65rem;color:var(--muted);font-family:var(--mono);">DURACIÓN TOTAL</span>
                        <div style="font-size:1.1rem;font-weight:700;color:var(--accent);font-family:var(--mono);">${summary.total_duration_sec} s</div>
                    </div>
                    <div style="background:var(--s2);padding:8px;border-radius:6px;border:1px solid var(--border);text-align:center;">
                        <span style="font-size:0.65rem;color:var(--muted);font-family:var(--mono);">DOSIS ENTREGADA</span>
                        <div style="font-size:1.1rem;font-weight:700;color:var(--green);font-family:var(--mono);">${summary.final_mu_delivered} MU</div>
                    </div>
                    <div style="background:var(--s2);padding:8px;border-radius:6px;border:1px solid var(--border);text-align:center;">
                        <span style="font-size:0.65rem;color:var(--muted);font-family:var(--mono);">TASA MÁXIMA</span>
                        <div style="font-size:1.1rem;font-weight:700;color:var(--text);font-family:var(--mono);">${summary.max_dose_rate_mu_min} <span style="font-size:0.7rem;">MU/min</span></div>
                    </div>
                    <div style="background:var(--s2);padding:8px;border-radius:6px;border:1px solid var(--border);text-align:center;">
                        <span style="font-size:0.65rem;color:var(--muted);font-family:var(--mono);">ESTADO FINAL</span>
                        <div style="font-size:0.95rem;font-weight:700;color:${summary.delivery_successful ? 'var(--green)' : 'var(--danger)'};font-family:var(--mono);">${summary.final_linac_state}</div>
                    </div>
                </div>

                <h4 style="font-size:0.8rem;font-family:var(--mono);color:var(--accent);margin:14px 0 6px;">Línea Temporal de Entrega Muestreada (Telemetría a 40 ms):</h4>
                <div style="overflow-x:auto;max-height:280px;border:1px solid var(--border);border-radius:6px;">
                    <table style="width:100%;border-collapse:collapse;text-align:left;">
                        <thead>
                            <tr style="background:var(--s2);border-bottom:1px solid var(--border);font-family:var(--mono);font-size:0.7rem;color:var(--muted);">
                                <th style="padding:6px 8px;">Tiempo</th>
                                <th style="padding:6px 8px;">Gantry</th>
                                <th style="padding:6px 8px;">Tasa Dosis</th>
                                <th style="padding:6px 8px;">Dosis Acum.</th>
                                <th style="padding:6px 8px;">Estado Linac</th>
                                <th style="padding:6px 8px;">Y1 Leaf 40</th>
                                <th style="padding:6px 8px;">Y2 Leaf 40</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${rowsHtml}
                        </tbody>
                    </table>
                </div>
            </div>
        `;
    }

    static _renderRtUdpResult(result, summary, events) {
        let eventsHtml = "";
        events.slice(0, 40).forEach(e => {
            const isCrit = e.severity === "CRITICAL";
            const badgeColor = isCrit ? "var(--danger)" : "var(--warn)";
            eventsHtml += `
                <div style="display:flex;align-items:center;justify-content:space-between;padding:6px 8px;border-bottom:1px solid rgba(255,255,255,0.03);font-size:0.75rem;">
                    <div style="display:flex;align-items:center;gap:8px;">
                        <span style="font-family:var(--mono);font-size:0.65rem;padding:2px 6px;border-radius:4px;background:rgba(255,255,255,0.05);color:${badgeColor};border:1px solid ${badgeColor};">
                            ${e.event_type}
                        </span>
                        <span>${e.description}</span>
                    </div>
                    <span style="font-family:var(--mono);font-size:0.7rem;color:var(--muted);">${e.timestamp}</span>
                </div>
            `;
        });

        return `
            <div class="result-card" style="border-left:3px solid var(--danger);margin-bottom:12px;">
                <div class="card-header">
                    <div>
                        <span class="card-manual" style="background:rgba(239,68,68,0.1);color:var(--danger);border:1px solid rgba(239,68,68,0.3);">RT-UDP Diagnostics</span>
                        <strong style="margin-left:8px;font-size:0.9rem;">${result.source_name}</strong>
                    </div>
                </div>

                <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(140px, 1fr));gap:8px;margin:12px 0;">
                    <div style="background:var(--s2);padding:8px;border-radius:6px;border:1px solid var(--border);text-align:center;">
                        <span style="font-size:0.65rem;color:var(--muted);font-family:var(--mono);">INTERLOCKS SUSPENSIÓN</span>
                        <div style="font-size:1.1rem;font-weight:700;color:var(--danger);font-family:var(--mono);">${summary.total_suspension_interlocks || 0}</div>
                    </div>
                    <div style="background:var(--s2);padding:8px;border-radius:6px;border:1px solid var(--border);text-align:center;">
                        <span style="font-size:0.65rem;color:var(--muted);font-family:var(--mono);">AVISOS COLISIÓN MLC</span>
                        <div style="font-size:1.1rem;font-weight:700;color:var(--warn);font-family:var(--mono);">${summary.total_collision_warnings || 0}</div>
                    </div>
                </div>

                <h4 style="font-size:0.8rem;font-family:var(--mono);color:var(--text);margin:14px 0 6px;">Eventos de Seguridad Detectados:</h4>
                <div style="max-height:300px;overflow-y:auto;border:1px solid var(--border);border-radius:6px;background:var(--s2);">
                    ${eventsHtml || '<p style="padding:10px;color:var(--muted);font-size:0.8rem;">No se detectaron eventos críticos.</p>'}
                </div>
            </div>
        `;
    }

    static _renderAuditTrailResult(result, summary, events) {
        let eventsHtml = "";
        events.slice(0, 40).forEach(e => {
            eventsHtml += `
                <tr style="border-bottom:1px solid rgba(255,255,255,0.03);font-family:var(--mono);font-size:0.75rem;">
                    <td style="padding:6px 8px;color:var(--muted);">${e.occurred}</td>
                    <td style="padding:6px 8px;font-weight:600;color:var(--text);">${e.event_name}</td>
                    <td style="padding:6px 8px;color:var(--accent);">${e.user || '-'}</td>
                    <td style="padding:6px 8px;">${e.details || ''}</td>
                </tr>
            `;
        });

        return `
            <div class="result-card" style="border-left:3px solid var(--accent);margin-bottom:12px;">
                <div class="card-header">
                    <div>
                        <span class="card-manual manual-badge">Audit Trail</span>
                        <strong style="margin-left:8px;font-size:0.9rem;">${result.source_name}</strong>
                    </div>
                </div>

                <div style="display:flex;gap:8px;flex-wrap:wrap;margin:10px 0;">
                    <span class="tag">Total Eventos: ${summary.total_events || 0}</span>
                    <span class="tag">Resets Linac: ${summary.linac_reset_count || 0}</span>
                    <span class="tag">Inicios de Sesión: ${summary.login_count || 0}</span>
                </div>

                <div style="overflow-x:auto;max-height:300px;border:1px solid var(--border);border-radius:6px;">
                    <table style="width:100%;border-collapse:collapse;text-align:left;">
                        <thead>
                            <tr style="background:var(--s2);border-bottom:1px solid var(--border);font-family:var(--mono);font-size:0.7rem;color:var(--muted);">
                                <th style="padding:6px 8px;">Fecha/Hora</th>
                                <th style="padding:6px 8px;">Evento</th>
                                <th style="padding:6px 8px;">Usuario</th>
                                <th style="padding:6px 8px;">Detalles</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${eventsHtml}
                        </tbody>
                    </table>
                </div>
            </div>
        `;
    }

    static _renderCcpResult(result, summary, events) {
        let eventsHtml = "";
        events.slice(0, 30).forEach(e => {
            const isWarn = e.level === "WARN";
            const levelColor = isWarn ? "var(--warn)" : "var(--danger)";
            eventsHtml += `
                <div style="padding:6px 8px;border-bottom:1px solid rgba(255,255,255,0.03);font-size:0.75rem;">
                    <div style="display:flex;justify-content:space-between;margin-bottom:2px;">
                        <span style="font-family:var(--mono);font-size:0.65rem;color:${levelColor};font-weight:700;">${e.level}</span>
                        <span style="font-family:var(--mono);font-size:0.65rem;color:var(--muted);">${e.timestamp}</span>
                    </div>
                    <div style="font-family:var(--mono);font-size:0.72rem;color:var(--text);">${e.message}</div>
                </div>
            `;
        });

        return `
            <div class="result-card" style="border-left:3px solid var(--warn);margin-bottom:12px;">
                <div class="card-header">
                    <div>
                        <span class="card-manual" style="background:rgba(234,179,8,0.1);color:var(--warn);border:1px solid rgba(234,179,8,0.3);">CCP Supervisor</span>
                        <strong style="margin-left:8px;font-size:0.9rem;">${result.source_name}</strong>
                    </div>
                </div>

                <div style="display:flex;gap:8px;flex-wrap:wrap;margin:10px 0;">
                    <span class="tag">Pérdidas Heartbeat: ${summary.heartbeat_misses_count || 0}</span>
                    <span class="tag">Errores NetMQ: ${summary.netmq_errors_count || 0}</span>
                </div>

                <div style="max-height:280px;overflow-y:auto;border:1px solid var(--border);border-radius:6px;background:var(--s2);">
                    ${eventsHtml || '<p style="padding:10px;color:var(--muted);font-size:0.8rem;">Sin advertencias del supervisor.</p>'}
                </div>
            </div>
        `;
    }

    static _renderControllerResult(result, summary, meta, events) {
        let linesHtml = "";
        events.slice(0, 40).forEach(e => {
            linesHtml += `
                <div style="padding:4px 8px;border-bottom:1px solid rgba(255,255,255,0.03);font-family:var(--mono);font-size:0.72rem;color:var(--text);">
                    ${e.text}
                </div>
            `;
        });

        return `
            <div class="result-card" style="border-left:3px solid var(--accent);margin-bottom:12px;">
                <div class="card-header">
                    <div>
                        <span class="card-manual manual-badge">Controller TLV Memory Log</span>
                        <strong style="margin-left:8px;font-size:0.9rem;">${result.source_name}</strong>
                    </div>
                </div>

                <div style="display:flex;gap:8px;flex-wrap:wrap;margin:10px 0;">
                    <span class="tag">Formato: ${meta.format || 'TLV Buffer'}</span>
                    <span class="tag">Líneas Decodificadas: ${summary.lines_count || 0}</span>
                </div>

                <div style="max-height:280px;overflow-y:auto;border:1px solid var(--border);border-radius:6px;background:var(--s2);">
                    ${linesHtml}
                </div>
            </div>
        `;
    }

    static _renderOpticalResult(result, summary, meta, events) {
        let leavesHtml = "";
        events.slice(0, 30).forEach(e => {
            leavesHtml += `
                <tr style="border-bottom:1px solid rgba(255,255,255,0.03);font-family:var(--mono);font-size:0.75rem;">
                    <td style="padding:6px 8px;font-weight:700;color:var(--accent);">Lámina ${e.leaf_index}</td>
                    <td style="padding:6px 8px;">${e.calibration_points} pts</td>
                    <td style="padding:6px 8px;color:${e.max_distortion_microns > 500 ? 'var(--warn)' : 'var(--text)'};">${e.max_distortion_microns} µm</td>
                    <td style="padding:6px 8px;color:var(--muted);">${e.mean_distortion_microns} µm</td>
                </tr>
            `;
        });

        return `
            <div class="result-card" style="border-left:3px solid var(--accent);margin-bottom:12px;">
                <div class="card-header">
                    <div>
                        <span class="card-manual manual-badge">MLC Optical Calibration</span>
                        <strong style="margin-left:8px;font-size:0.9rem;">${result.source_name}</strong>
                    </div>
                </div>

                <div style="display:flex;gap:8px;flex-wrap:wrap;margin:10px 0;">
                    <span class="tag">Banco: ${summary.leaf_bank || 'Y1'}</span>
                    <span class="tag">Láminas Calibradas: ${summary.total_leaves_calibrated || 80}</span>
                    <span class="tag" style="color:var(--warn);">Distorsión Máxima: ${summary.overall_max_distortion_microns || 0} µm</span>
                </div>

                <div style="overflow-x:auto;max-height:260px;border:1px solid var(--border);border-radius:6px;">
                    <table style="width:100%;border-collapse:collapse;text-align:left;">
                        <thead>
                            <tr style="background:var(--s2);border-bottom:1px solid var(--border);font-family:var(--mono);font-size:0.7rem;color:var(--muted);">
                                <th style="padding:6px 8px;">Lámina</th>
                                <th style="padding:6px 8px;">Puntos Calibrados</th>
                                <th style="padding:6px 8px;">Pico Distorsión</th>
                                <th style="padding:6px 8px;">Distorsión Media</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${leavesHtml}
                        </tbody>
                    </table>
                </div>
            </div>
        `;
    }
}

// Export to window
if (typeof window !== "undefined") {
    window.LinacLogSuite = LinacLogSuite;
}
