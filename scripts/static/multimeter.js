/**
 * SOLVI - Módulo de Integración de Multímetro Digital (DMM)
 *
 * Soporte especializado para modelos antiguos de multímetros (Entrada Manual Táctil),
 * Simulador de Banco Linac con inyección de fallas y telemetría virtual,
 * y pasarela lista para hardware futuro (Web Bluetooth / Web Serial).
 *
 * Diseñado con salvaguardas estrictas contra saturación de RAM, límites acotados
 * de historial, protección de batería/CPU en segundo plano y operación desacoplada 100% offline.
 */

(function (window, document) {
    "use strict";

    // ─── CONSTANTES Y LÍMITES DE MEMORIA ─────────────────────────────────
    const MAX_HISTORY_RECORDS = 50; // Búfer circular estricto contra fugas de RAM
    const THROTTLE_SIMULATION_MS = 240; // Frecuencia controlada (aprox. 4 Hz)

    // Catálogo integrado offline de Puntos de Prueba (sincronizado con planos Linac)
    
    let OFFLINE_CATALOG = {};
    async function loadCatalog() {
        try {
            const resp = await fetch('/static/multimeter_catalog.json');
            if(resp.ok) { OFFLINE_CATALOG = await resp.json(); }
            else {
                const apiResp = await fetch('/multimeter/test-points');
                if(apiResp.ok) { OFFLINE_CATALOG = await apiResp.json(); }
            }
            const sel = document.getElementById("dmmTpSelect");
            if (sel) {
                sel.innerHTML = generarOpcionesPuntosPrueba();
                if (_activeTpId) sel.value = _activeTpId;
            }
            renderizarPresetsDinamicos();
        } catch(e) {}
    }
    loadCatalog();


    // Mapeo inteligente de nodos del visualizador de esquemas a puntos de prueba del catálogo
    const NODE_TO_TP_MAP = {
        "PSU_24V": "GEN_VOLT_24",
        "PSU1 +24V": "GEN_VOLT_24",
        "ESTOP_CONSOLE": "GEN_CONT_LOOP",
        "ESTOP_GANTRY": "GEN_CONT_LOOP",
        "ESTOP_ROOM": "GEN_CONT_LOOP",
        "DOOR_SW_283": "GEN_CONT_LOOP",
        "COLLISION_HEAD": "GEN_CONT_LOOP",
        "KEY_SERVICE": "GEN_CONT_LOOP",
        "K1_K2_DRV": "TP5",
        "GUN_FILAMENT": "TP_GUN",
        "VAC_PUMP": "TP_VAC",
        "ION_CHAMBER": "TP100"
    };

    // ─── ESTADO INTERNO DEL MÓDULO ───────────────────────────────────────
    let _activeTpId = "TP1";
    let _activeMode = "manual"; // 'manual', 'simulation', 'hardware'
    let _currentInputStr = "";
    let _history = []; // Registros históricos limitados a MAX_HISTORY_RECORDS
    let _lastEvaluation = null; // Última evaluación generada (activa en pantalla)
    let _simulationIntervalId = null;
    let _simFaultType = "normal";
    let _audioContext = null;
    let _audioBuzzerEnabled = false;
    let _bleDevice = null;
    let _serialPort = null;
    let _serialReader = null;
    let _serialAbortController = null;
    let _isModalOpen = false;
    let _pausedByVisibility = false;

    // ─── UTILIDADES DE SEGURIDAD Y FORMATO ──────────────────────────────
    function esc(str) {
        return String(str || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function safeNumber(val, fallback) {
        const num = parseFloat(val);
        return (!isNaN(num) && isFinite(num)) ? num : fallback;
    }

    // ─── RESOLUCIÓN INTELIGENTE DE PUNTOS DE PRUEBA ──────────────────────
    function resolverPuntoDePrueba(idOrCode, fallbackDefault = false) {
        const raw = String(idOrCode || "").trim();
        if (!raw) return fallbackDefault ? OFFLINE_CATALOG["TP1"] : null;
        if (OFFLINE_CATALOG[raw]) return OFFLINE_CATALOG[raw];

        const upper = raw.toUpperCase();
        if (OFFLINE_CATALOG[upper]) return OFFLINE_CATALOG[upper];

        if (NODE_TO_TP_MAP[upper] && OFFLINE_CATALOG[NODE_TO_TP_MAP[upper]]) {
            return OFFLINE_CATALOG[NODE_TO_TP_MAP[upper]];
        }

        const direct = Object.values(OFFLINE_CATALOG).find(t =>
            t.code.toUpperCase() === upper || t.id.toUpperCase() === upper
        );
        if (direct) return direct;

        const match = upper.match(/^(TP\w*|GEN_\w+)/);
        if (match && OFFLINE_CATALOG[match[1]]) {
            return OFFLINE_CATALOG[match[1]];
        }

        return fallbackDefault ? OFFLINE_CATALOG["TP1"] : null;
    }

    // ─── EVALUADOR DE TOLERANCIAS 100% OFFLINE ───────────────────────────
    function evaluarLectura(tpId, valorMedido) {
        const val = safeNumber(valorMedido, 0.0);
        const tp = resolverPuntoDePrueba(tpId, false);

        if (!tp) {
            return {
                ok: false,
                error: "unknown_test_point",
                test_point_id: tpId,
                test_point_code: tpId || "DESCONOCIDO",
                test_point_name: `Punto no catalogado (${tpId || "N/D"})`,
                subsystem: "unknown",
                subsystem_name: "Punto Desconocido",
                role: "Punto de prueba auxiliar no registrado en manuales",
                manual: "",
                page: 0,
                measured_value: val,
                nominal_value: null,
                tolerance_min: null,
                tolerance_max: null,
                unit: "V",
                delta: 0,
                percent_error: null,
                status: "FUERA_DE_TOLERANCIA",
                status_badge: "DESCONOCIDO",
                status_label: "PUNTO NO IDENTIFICADO",
                color: "var(--muted)",
                recommendation: `El punto de prueba "${tpId}" no está en el catálogo. Verifique el identificador o consulte esquemas del Linac.`,
                notes: "Punto no catalogado. Requiere verificación previa de planos antes de evaluar tolerancias.",
                is_known_test_point: false,
                timestamp: new Date().toISOString()
            };
        }

        const nominal = tp.nominal;
        const tMin = tp.tolerance_min;
        const tMax = tp.tolerance_max;
        const wLow = tp.warning_low !== undefined ? tp.warning_low : tMin;
        const wHigh = tp.warning_high !== undefined ? tp.warning_high : tMax;

        const delta = Math.round((val - nominal) * 10000) / 10000;
        let percentError = null;
        if (Math.abs(nominal) > 1e-6) {
            percentError = Math.round((delta / Math.abs(nominal)) * 10000) / 100;
        } else {
            percentError = null;
        }

        const pctStr = (percentError !== null && percentError !== undefined && !isNaN(percentError))
            ? `${percentError >= 0 ? '+' : ''}${percentError}%`
            : "N/A";

        let status = "DENTRO_DE_TOLERANCIA";
        let statusBadge = "OK";
        let statusLabel = "DENTRO DE TOLERANCIA";
        let color = "#4ade80"; // Verde
        let recommendation = "Valor nominal en rango óptimo de operación. No se requieren ajustes.";

        if (val >= tMin && val <= tMax) {
            if (val >= wLow && val <= wHigh) {
                status = "DENTRO_DE_TOLERANCIA";
                statusBadge = "OK";
                statusLabel = "DENTRO DE TOLERANCIA";
                color = "#4ade80";
                recommendation = "Valor nominal en rango óptimo de operación.";
            } else {
                status = "ADVERTENCIA_MARGINAL";
                statusBadge = "MARGINAL";
                statusLabel = "ADVERTENCIA MARGINAL";
                color = "#f59e0b"; // Naranja
                recommendation = `Lectura próxima al umbral crítico [${tMin} a ${tMax} ${tp.unit}]. Verificar estabilidad y carga.`;
            }
        } else {
            status = "FUERA_DE_TOLERANCIA";
            statusBadge = "FALLA";
            statusLabel = "FUERA DE TOLERANCIA";
            color = "#ef4444"; // Rojo
            if (val < tMin) {
                recommendation = `Tensión/lectura inferior al mínimo (${val.toFixed(2)} ${tp.unit} < ${tMin.toFixed(2)} ${tp.unit}). Δ = ${delta >= 0 ? '+' : ''}${delta.toFixed(2)} ${tp.unit} (${pctStr}). ${tp.notes}`;
            } else {
                recommendation = `Tensión/lectura superior al máximo (${val.toFixed(2)} ${tp.unit} > ${tMax.toFixed(2)} ${tp.unit}). Δ = ${delta >= 0 ? '+' : ''}${delta.toFixed(2)} ${tp.unit} (${pctStr}). Riesgo de sobrevoltaje. ${tp.notes}`;
            }
        }

        return {
            ok: true,
            test_point_id: tp.id,
            test_point_code: tp.code,
            test_point_name: tp.name,
            subsystem: tp.subsystem,
            subsystem_name: tp.subsystem_name,
            role: tp.role,
            manual: tp.manual,
            page: tp.page,
            measured_value: val,
            nominal_value: nominal,
            tolerance_min: tMin,
            tolerance_max: tMax,
            unit: tp.unit,
            delta: delta,
            percent_error: percentError,
            status: status,
            status_badge: statusBadge,
            status_label: statusLabel,
            color: color,
            recommendation: recommendation,
            notes: tp.notes,
            is_known_test_point: true,
            timestamp: new Date().toISOString()
        };
    }

    // ─── GENERADOR DE LECTURAS DE BANCO SIMULADO ─────────────────────────
    function generarLecturaSimulada(tpId, faultType) {
        const tp = resolverPuntoDePrueba(tpId, false);
        if (!tp) {
            return {
                test_point_id: tpId,
                test_point_code: tpId || "DESCONOCIDO",
                test_point_name: `Punto no catalogado (${tpId || "N/D"})`,
                status: "FUERA_DE_TOLERANCIA",
                status_badge: "DESCONOCIDO",
                status_label: "PUNTO DESCONOCIDO",
                color: "var(--muted)",
                recommendation: `No se puede simular lectura para el punto de prueba desconocido "${tpId}".`,
                is_known_test_point: false,
                is_simulation: true,
                fault_injected: String(faultType || "normal").toLowerCase()
            };
        }
        const nominal = tp.nominal;
        const fault = String(faultType || "normal").toLowerCase();

        let baseVal = nominal;
        if (fault === "open_circuit") {
            baseVal = (tp.mode === "resistance_continuity") ? 999999.0 : 0.05;
        } else if (fault === "resistive_drop") {
            baseVal = (tp.mode === "resistance_continuity") ? 16.5 : (nominal * 0.74);
        } else if (fault === "short_circuit") {
            baseVal = (tp.mode === "resistance_continuity") ? 0.02 : 0.00;
        } else if (fault === "overvoltage") {
            baseVal = (tp.mode === "resistance_continuity") ? 45.0 : (nominal * 1.21);
        }

        // Fluctuación térmica realista (jitter acotado)
        let simulatedVal = baseVal;
        if (fault !== "open_circuit") {
            const spread = Math.max(Math.abs(baseVal) * 0.006, 0.02);
            const noise = (Math.random() * (spread * 2)) - spread;
            simulatedVal = Math.round((baseVal + noise) * 1000) / 1000;
        }

        // Físicamente la resistencia y continuidad no pueden ser negativas
        if (tp.mode === "resistance_continuity") {
            simulatedVal = Math.max(0.001, simulatedVal);
        }

        const ev = evaluarLectura(tp.id, simulatedVal);
        ev.fault_injected = fault;
        ev.is_simulation = true;
        return ev;
    }

    // ─── AUDIO BEEPER DE CONTINUIDAD (WEB AUDIO SEGURO) ──────────────────
    function sonarBeeper(frecuencia, duracionMs) {
        if (!_audioBuzzerEnabled) return;
        try {
            const AudioCtx = window.AudioContext || window.webkitAudioContext;
            if (!AudioCtx) return;
            if (!_audioContext) {
                _audioContext = new AudioCtx();
            }
            const dur = (duracionMs || 100) / 1000;
            const playTone = () => {
                try {
                    const osc = _audioContext.createOscillator();
                    const gain = _audioContext.createGain();
                    osc.type = "sine";
                    osc.frequency.setValueAtTime(frecuencia || 1760, _audioContext.currentTime); // Tono tipo multímetro Fluke
                    gain.gain.setValueAtTime(0.08, _audioContext.currentTime);
                    gain.gain.exponentialRampToValueAtTime(0.001, _audioContext.currentTime + dur);
                    osc.connect(gain);
                    gain.connect(_audioContext.destination);
                    osc.onended = () => {
                        try {
                            osc.disconnect();
                            gain.disconnect();
                        } catch (_) {}
                    };
                    osc.start();
                    osc.stop(_audioContext.currentTime + dur);
                } catch (_) {}
            };

            if (_audioContext.state === "suspended") {
                _audioContext.resume().then(playTone).catch(() => {});
            } else {
                playTone();
            }
        } catch (e) {
            // Silencioso en caso de bloqueo de reproducción por políticas del navegador
        }
    }

    // ─── MANEJO DE REGISTROS HISTÓRICOS CON REGLA ANTIFUGA DE RAM ────────
    function registrarEnHistorial(evaluacion) {
        if (!evaluacion) return;
        _history.unshift(evaluacion);
        if (_history.length > MAX_HISTORY_RECORDS) {
            _history.length = MAX_HISTORY_RECORDS;
        }
        renderHistorial();
    }

    // ─── ENTRADA MANUAL TÁCTIL (TECLADO NUMÉRICO) ────────────────────────
    function keypadPress(char) {
        if (char === "C") {
            _currentInputStr = "";
        } else if (char === "BS") {
            _currentInputStr = _currentInputStr.slice(0, -1);
        } else if (char === "±") {
            if (_currentInputStr === "") {
                _currentInputStr = "-";
            } else if (_currentInputStr === "-") {
                _currentInputStr = "";
            } else if (_currentInputStr.startsWith("-")) {
                _currentInputStr = _currentInputStr.slice(1);
            } else {
                _currentInputStr = "-" + _currentInputStr;
            }
        } else if (char === ".") {
            if (!_currentInputStr.includes(".")) {
                if (_currentInputStr === "" || _currentInputStr === "-") {
                    _currentInputStr += "0.";
                } else {
                    _currentInputStr += ".";
                }
            }
        } else {
            // Dígitos 0-9
            if (_currentInputStr === "0") {
                _currentInputStr = char;
            } else if (_currentInputStr === "-0") {
                _currentInputStr = "-" + char;
            } else if (_currentInputStr.length < 10) {
                _currentInputStr += char;
            }
        }

        actualizarDisplayManual();
    }

    function aplicarPreset(valor) {
        _currentInputStr = String(valor);
        actualizarDisplayManual();
        procesarLecturaManual();
    }

    function actualizarDisplayManual() {
        const tp = resolverPuntoDePrueba(_activeTpId, true);
        const strToShow = (_currentInputStr === "" || _currentInputStr === "-") ? "0.00" : _currentInputStr;

        // Pantalla principal
        const dispVal = document.getElementById("dmmDisplayValue");
        if (dispVal) dispVal.textContent = strToShow;
        const dispUnit = document.getElementById("dmmDisplayUnit");
        if (dispUnit) dispUnit.textContent = tp.unit;
        const dispInput = document.getElementById("dmmManualInputBox");
        if (dispInput && document.activeElement !== dispInput) dispInput.value = _currentInputStr;

        // Modal flotante (identificadores específicos para sincronización exacta)
        const modalDispVal = document.getElementById("dmmModalDisplayValue");
        if (modalDispVal) modalDispVal.textContent = strToShow;
        const modalDispUnit = document.getElementById("dmmModalDisplayUnit");
        if (modalDispUnit) modalDispUnit.textContent = tp.unit;
        const modalDispInput = document.getElementById("dmmModalManualInputBox");
        if (modalDispInput && document.activeElement !== modalDispInput) modalDispInput.value = _currentInputStr;
    }

    function procesarLecturaManual() {
        let str = _currentInputStr;
        if (str === "" || str === "-") {
            str = "0.0";
        } else if (str === ".") {
            return;
        }

        const val = parseFloat(str);
        if (isNaN(val) || !isFinite(val)) return;

        const evaluacion = evaluarLectura(_activeTpId, val);
        _lastEvaluation = evaluacion;
        mostrarResultado(evaluacion);
        registrarEnHistorial(evaluacion);

        if (!evaluacion.ok || evaluacion.is_known_test_point === false || evaluacion.status_badge === "DESCONOCIDO") {
            sonarBeeper(300, 250);
            if (typeof window.toast === "function") {
                window.toast(`Punto de prueba no catalogado: ${_activeTpId || 'desconocido'}`, "warn");
            }
        } else if (evaluacion.status === "DENTRO_DE_TOLERANCIA") {
            sonarBeeper(1760, 80);
        } else if (evaluacion.status === "FUERA_DE_TOLERANCIA") {
            sonarBeeper(440, 200);
        }
    }

    // ─── CONTROL DE SIMULADOR DE BANCO ───────────────────────────────────
    function iniciarTelemetriaVirtual() {
        if (_simulationIntervalId) return;

        const setSimButtons = (playDisp, pauseDisp) => {
            ["dmmBtnSimPlay", "dmmModalBtnSimPlay"].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.style.display = playDisp;
            });
            ["dmmBtnSimPause", "dmmModalBtnSimPause"].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.style.display = pauseDisp;
            });
        };

        setSimButtons("none", "inline-flex");

        _simulationIntervalId = setInterval(() => {
            const ev = generarLecturaSimulada(_activeTpId, _simFaultType);
            _lastEvaluation = ev;

            const valStr = ev.measured_value.toFixed(3);
            const dispVal = document.getElementById("dmmDisplayValue");
            if (dispVal) dispVal.textContent = valStr;
            const modalDispVal = document.getElementById("dmmModalDisplayValue");
            if (modalDispVal) modalDispVal.textContent = valStr;

            mostrarResultado(ev);
        }, THROTTLE_SIMULATION_MS);
    }

    function pausarTelemetriaVirtual() {
        if (_simulationIntervalId) {
            clearInterval(_simulationIntervalId);
            _simulationIntervalId = null;
        }

        const setSimButtons = (playDisp, pauseDisp) => {
            ["dmmBtnSimPlay", "dmmModalBtnSimPlay"].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.style.display = playDisp;
            });
            ["dmmBtnSimPause", "dmmModalBtnSimPause"].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.style.display = pauseDisp;
            });
        };

        setSimButtons("inline-flex", "none");
    }

    function capturarMuestraSimulada() {
        const ev = generarLecturaSimulada(_activeTpId, _simFaultType);
        _lastEvaluation = ev;

        const valStr = ev.measured_value.toFixed(3);
        const dispVal = document.getElementById("dmmDisplayValue");
        if (dispVal) dispVal.textContent = valStr;
        const modalDispVal = document.getElementById("dmmModalDisplayValue");
        if (modalDispVal) modalDispVal.textContent = valStr;

        mostrarResultado(ev);
        registrarEnHistorial(ev);

        if (ev.status === "DENTRO_DE_TOLERANCIA") sonarBeeper(1760, 90);
        else sonarBeeper(440, 150);
    }

    function cambiarFallaSimulada(tipoFalla) {
        _simFaultType = tipoFalla;
        if (!_simulationIntervalId) {
            capturarMuestraSimulada();
        }
    }

    // ─── PASARELA HARDWARE (WEB BLUETOOTH / WEB SERIAL) ──────────────────
    async function conectarBluetooth() {
        if (!navigator.bluetooth) {
            alertarHardwareNoSoportado("Bluetooth");
            return;
        }

        try {
            const statusEl = document.getElementById("dmmHwStatus");
            if (statusEl) statusEl.textContent = "Buscando multímetro BLE cercano...";

            const device = await navigator.bluetooth.requestDevice({
                acceptAllDevices: true,
                optionalServices: ["generic_access", 0xFFF0, 0xFFE0]
            });

            _bleDevice = device;
            device.addEventListener("gattserverdisconnected", () => {
                if (statusEl) statusEl.textContent = "Multímetro BLE desconectado.";
                if (typeof window.toast === "function") window.toast("Multímetro BLE desconectado", "warn");
            });

            if (device.gatt) {
                try {
                    await device.gatt.connect();
                } catch (_connErr) {
                    // Si el dispositivo requiere pairing previo, informamos al operador
                }
            }

            if (statusEl) statusEl.textContent = `Conectado: ${device.name || 'DMM Bluetooth'}`;
            if (typeof window.toast === "function") window.toast(`Conectado a ${device.name || 'DMM BLE'}`, "ok");
        } catch (err) {
            const statusEl = document.getElementById("dmmHwStatus");
            if (err && err.name === "NotFoundError") {
                if (statusEl) statusEl.textContent = "Búsqueda cancelada por el operador.";
            } else {
                if (statusEl) statusEl.textContent = "No se pudo enlazar multímetro BLE.";
            }
        }
    }

    async function conectarSerial() {
        if (!navigator.serial) {
            alertarHardwareNoSoportado("Serial / USB");
            return;
        }

        try {
            const statusEl = document.getElementById("dmmHwStatus");
            if (statusEl) statusEl.textContent = "Esperando selección de puerto USB/Serie...";

            const port = await navigator.serial.requestPort();
            await port.open({ baudRate: 9600 });
            _serialPort = port;

            if (statusEl) statusEl.textContent = "Puerto COM abierto (9600 baud). Recibiendo datos...";
            if (typeof window.toast === "function") window.toast("Puerto COM abierto", "ok");

            leerFlujoSerial(port);
        } catch (err) {
            const statusEl = document.getElementById("dmmHwStatus");
            if (err && err.name === "NotFoundError") {
                if (statusEl) statusEl.textContent = "Selección de puerto cancelada.";
            } else {
                if (statusEl) statusEl.textContent = "Error al abrir puerto COM.";
            }
        }
    }

    async function leerFlujoSerial(port) {
        try {
            _serialAbortController = new AbortController();
            const textDecoder = new TextDecoderStream();
            port.readable.pipeTo(textDecoder.writable, { signal: _serialAbortController.signal }).catch(() => {});
            const reader = textDecoder.readable.getReader();
            _serialReader = reader;

            let buffer = "";
            while (true) {
                const { value, done } = await reader.read();
                if (done) break;
                buffer += value;
                const lines = buffer.split(/[\r\n]+/);
                buffer = lines.pop(); // Mantener segmento incompleto

                for (const line of lines) {
                    procesarLineaDmm(line);
                }
            }
        } catch (err) {
            if (err && err.name !== "AbortError") {
                console.warn("DMM Serial error:", err);
            }
        }
    }

    function procesarLineaDmm(line) {
        if (!line || !line.trim()) return;
        const match = line.match(/([+-]?\d+(?:\.\d+)?)/);
        if (match) {
            const val = parseFloat(match[1]);
            if (!isNaN(val) && isFinite(val)) {
                _currentInputStr = String(val);
                actualizarDisplayManual();
                procesarLecturaManual();
            }
        }
    }

    function alertarHardwareNoSoportado(tipo) {
        const statusEl = document.getElementById("dmmHwStatus");
        const msg = `Tu navegador o protocolo actual no dispone de soporte para Web ${tipo}. Usa la Entrada Manual Rápida para multímetros clásicos sin conexión.`;
        if (statusEl) {
            statusEl.innerHTML = `<span style="color:var(--warn)">ℹ️ ${msg}</span>`;
        }
        if (typeof window.toast === "function") {
            window.toast("Función disponible para navegadores compatibles", "warn");
        }
    }

    function desconectarHardware() {
        try {
            if (_serialAbortController) {
                _serialAbortController.abort();
                _serialAbortController = null;
            }
            if (_serialReader) {
                _serialReader.cancel().catch(() => {});
                _serialReader = null;
            }
            if (_serialPort) {
                _serialPort.close().catch(() => {});
                _serialPort = null;
            }
            if (_bleDevice && _bleDevice.gatt && _bleDevice.gatt.connected) {
                _bleDevice.gatt.disconnect();
                _bleDevice = null;
            }
            const statusEl = document.getElementById("dmmHwStatus");
            if (statusEl) statusEl.textContent = "Desconectado.";
            if (typeof window.toast === "function") window.toast("Dispositivo desconectado", "ok");
        } catch (e) {
            // Silencioso
        }
    }

    // ─── RENDERIZADO VISUAL Y RESULTADOS ─────────────────────────────────
    function generarHtmlTarjetaResultado(ev) {
        return `
        <div style="background:var(--surface);border:1px solid var(--border);border-left:4px solid ${ev.color};border-radius:10px;padding:14px;animation:fadeIn 0.2s ease;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;flex-wrap:wrap;gap:6px;">
                <span style="font-family:var(--mono);font-size:0.7rem;font-weight:700;color:${ev.color};background:${ev.color}15;border:1px solid ${ev.color}35;padding:3px 8px;border-radius:12px;">
                    ⬤ ${esc(ev.status_label)} [${esc(ev.status_badge)}]
                </span>
                <span style="font-family:var(--mono);font-size:0.68rem;color:var(--muted);">
                    ${new Date().toLocaleTimeString()}
                </span>
            </div>

            <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(130px, 1fr));gap:8px;margin:10px 0;background:rgba(0,0,0,0.25);border:1px solid var(--border);padding:10px;border-radius:8px;font-family:var(--mono);font-size:0.78rem;">
                <div><span style="color:var(--muted);">Medido:</span> <strong style="color:${ev.color}">${(typeof ev.measured_value === "number" && isFinite(ev.measured_value)) ? ev.measured_value.toFixed(2) + " " + esc(ev.unit) : "N/D"}</strong></div>
                <div><span style="color:var(--muted);">Nominal:</span> <strong>${(typeof ev.nominal_value === "number" && isFinite(ev.nominal_value)) ? ev.nominal_value.toFixed(2) + " " + esc(ev.unit) : "N/D"}</strong></div>
                <div><span style="color:var(--muted);">Tolerancia:</span> <strong>${(typeof ev.tolerance_min === "number" && typeof ev.tolerance_max === "number") ? `${ev.tolerance_min.toFixed(1)} a ${ev.tolerance_max.toFixed(1)} ${esc(ev.unit)}` : "N/D"}</strong></div>
                <div><span style="color:var(--muted);">Desviación:</span> <strong style="color:${(typeof ev.delta === 'number' && ev.delta >= 0) ? 'var(--green)' : 'var(--danger)'}">${(typeof ev.delta === 'number' && isFinite(ev.delta)) ? `${ev.delta >= 0 ? '+' : ''}${ev.delta.toFixed(2)} ${esc(ev.unit)} (${(ev.percent_error !== null && ev.percent_error !== undefined && isFinite(ev.percent_error)) ? `${ev.percent_error >= 0 ? '+' : ''}${ev.percent_error}%` : 'N/A'})` : "N/D"}</strong></div>
            </div>

            <div style="font-size:0.8rem;color:#cbd5e1;line-height:1.5;margin-bottom:12px;background:rgba(255,255,255,0.02);padding:8px 10px;border-radius:6px;border-left:2px solid ${ev.color};">
                <strong>Diagnóstico de Ingeniería:</strong> ${esc(ev.recommendation)}
            </div>

            <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;">
                <button type="button" class="btn btn-primary btn-sm" data-dmm-action="exportar-apuntes" style="box-shadow:0 0 10px rgba(0,212,255,0.2);">
                    📝 Guardar en Mis Apuntes
                </button>
                <button type="button" class="btn btn-ghost btn-sm" data-dmm-action="ver-plano" data-tp-id="${esc(ev.test_point_id)}">
                    ⚡ Ver en Esquema SVG
                </button>
                <button type="button" class="btn btn-ghost btn-sm" data-dmm-action="trazar" data-tp-code="${esc(ev.test_point_code)}">
                    🧭 Trazar en Relacionar
                </button>
            </div>
        </div>`;
    }

    function mostrarResultado(ev) {
        _lastEvaluation = ev;
        const html = generarHtmlTarjetaResultado(ev);

        // Actualizar en pantalla principal
        const resBox = document.getElementById("dmmResultBox");
        if (resBox) {
            resBox.style.display = "block";
            resBox.innerHTML = html;
        }

        // Actualizar en modal flotante (si está visible)
        const modalWrap = document.getElementById("dmmModalResultWrap");
        if (modalWrap) {
            modalWrap.style.display = "block";
            modalWrap.innerHTML = html;
        }
    }

    function renderHistorial() {
        const histContainer = document.getElementById("dmmHistoryList");
        if (!histContainer) return;

        if (_history.length === 0) {
            histContainer.innerHTML = '<p style="font-size:0.75rem;color:var(--muted);text-align:center;padding:12px 0;">No hay lecturas registradas en esta sesión.</p>';
            return;
        }

        histContainer.innerHTML = _history.map((h, idx) => {
            const nomStr = (typeof h.nominal_value === "number" && isFinite(h.nominal_value)) ? `${h.nominal_value.toFixed(1)}${esc(h.unit)}` : "N/D";
            const measStr = (typeof h.measured_value === "number" && isFinite(h.measured_value)) ? `${h.measured_value.toFixed(2)} ${esc(h.unit)}` : "N/D";
            return `
            <div style="display:flex;justify-content:space-between;align-items:center;padding:7px 10px;margin-bottom:5px;background:var(--surface);border:1px solid var(--border);border-left:3px solid ${h.color};border-radius:6px;font-family:var(--mono);font-size:0.72rem;animation:fadeIn 0.2s ease;">
                <div>
                    <strong style="color:var(--accent);">${esc(h.test_point_code)}</strong> · 
                    <span style="color:${h.color};font-weight:700;">${measStr}</span>
                    <span style="color:var(--muted);font-size:0.65rem;">(Nom: ${nomStr})</span>
                </div>
                <div style="display:flex;align-items:center;gap:6px;">
                    <span style="font-size:0.62rem;color:${h.color};background:${h.color}15;padding:2px 6px;border-radius:8px;">${esc(h.status_badge)}</span>
                    <button type="button" data-dmm-action="exportar-registro" data-idx="${idx}" title="Exportar este apunte" style="background:none;border:none;cursor:pointer;color:var(--muted);font-size:0.8rem;">📝</button>
                </div>
            </div>
        `;}).join("");
    }

    function limpiarHistorial() {
        _history = [];
        renderHistorial();
        if (typeof window.toast === "function") window.toast("Historial limpiado", "ok");
    }

    // ─── PRESETS DINÁMICOS ADAPTADOS AL PUNTO ACTIVO ─────────────────────
    function renderizarPresetsDinamicos() {
        const tp = resolverPuntoDePrueba(_activeTpId, true);
        const presets = [];

        // 1. Preset nominal directo del punto
        presets.push({ label: `🎯 Nominal (${tp.nominal}${tp.unit})`, val: tp.nominal, highlight: true });

        // 2. Presets adaptados al tipo de medición
        if (tp.mode === "resistance_continuity") {
            presets.push({ label: "0.0Ω (Masa)", val: 0.0 });
            presets.push({ label: "0.2Ω (Contacto OK)", val: 0.2 });
            presets.push({ label: "0.8Ω (Límite)", val: 0.8 });
            presets.push({ label: "15.0Ω (Degradado)", val: 15.0 });
        } else {
            // Niveles comunes de tensión Linac
            if (tp.nominal !== 0.0) presets.push({ label: "0.0V (Masa)", val: 0.0 });
            if (tp.nominal !== 1.8) presets.push({ label: "1.8V (Filamento)", val: 1.8 });
            if (tp.nominal !== 5.0) presets.push({ label: "5.0V (TTL)", val: 5.0 });
            if (tp.nominal !== 12.0) presets.push({ label: "12.0V (Aux)", val: 12.0 });
            if (tp.nominal !== 15.0) presets.push({ label: "15.0V (OpAmp)", val: 15.0 });
            if (tp.nominal !== -15.0 && (tp.nominal < 0 || tp.id.includes("15"))) presets.push({ label: "-15.0V (Simétrico)", val: -15.0 });
            if (tp.nominal !== 24.0) presets.push({ label: "24.0V (Seguridad)", val: 24.0 });
            if (tp.nominal === -150.0 || tp.id === "TP7") presets.push({ label: "-150V (Corte)", val: -150.0 });
            if (tp.nominal === 400.0 || tp.id === "TP100") presets.push({ label: "400V (Dosis)", val: 400.0 });
            if (tp.nominal === 800.0 || tp.id === "TP3") presets.push({ label: "800V (RF)", val: 800.0 });
        }

        const makeHtml = () => presets.map(p => {
            const extraStyle = p.highlight
                ? "border-color:rgba(0,212,255,0.5);color:var(--accent);background:rgba(0,212,255,0.08);font-weight:700;"
                : "";
            return `<button type="button" class="btn btn-ghost btn-sm" data-dmm-action="preset" data-val="${p.val}" style="font-family:var(--mono);padding:4px 8px;font-size:0.75rem;${extraStyle}">${esc(p.label)}</button>`;
        }).join("");

        const containerMain = document.getElementById("dmmDynamicPresets");
        if (containerMain) containerMain.innerHTML = makeHtml();

        const containerModal = document.getElementById("dmmModalDynamicPresets");
        if (containerModal) containerModal.innerHTML = makeHtml();
    }

    // ─── EXPORTACIÓN A "APUNTES TÉCNICOS" EN 1 CLIC ───────────────────────
    function exportarAApuntes(evaluacionPersonalizada) {
        const ev = evaluacionPersonalizada || _lastEvaluation || _history[0];
        if (!ev) {
            if (typeof window.toast === "function") window.toast("Realiza o captura una lectura antes de exportar", "warn");
            return;
        }

        // Si el modal flotante está abierto, lo cerramos para permitir editar el apunte con total visibilidad
        cerrarInspectorModal();

        const tpCode = ev.test_point_code || ev.test_point_id || 'N/A';
        const tpName = ev.test_point_name || 'Desconocido';
        const titulo = `[MEDICIÓN DMM] ${tpCode} - ${tpName}`;
        const fechaLocal = new Date().toLocaleString("es-ES", { dateStyle: "medium", timeStyle: "medium" });

        const measuredStr = (typeof ev.measured_value === "number" && isFinite(ev.measured_value)) ? `${ev.measured_value.toFixed(2)} ${ev.unit || ''}` : "N/D";
        const nominalStr = (typeof ev.nominal_value === "number" && isFinite(ev.nominal_value)) ? `${ev.nominal_value.toFixed(2)} ${ev.unit || ''}` : "N/D";
        const rangeStr = (typeof ev.tolerance_min === "number" && typeof ev.tolerance_max === "number") ? `${ev.tolerance_min.toFixed(2)} a ${ev.tolerance_max.toFixed(2)} ${ev.unit || ''}` : "N/D";
        const deltaStr = (typeof ev.delta === "number" && isFinite(ev.delta)) ? `${ev.delta >= 0 ? '+' : ''}${ev.delta.toFixed(2)} ${ev.unit || ''} (${(ev.percent_error !== null && ev.percent_error !== undefined && isFinite(ev.percent_error)) ? `${ev.percent_error >= 0 ? '+' : ''}${ev.percent_error}%` : 'N/A'})` : "N/D";

        const contenido =
`=========================================
REGISTRO TÉCNICO DE MEDICIÓN CON MULTÍMETRO
=========================================
Fecha y Hora: ${fechaLocal}
Punto de Prueba: ${tpCode} (${tpName})
Subsistema Linac: ${ev.subsystem_name || ev.subsystem || 'N/D'}
Función del Punto: ${ev.role || 'Monitor de circuito'}

RESULTADOS ELÉCTRICOS:
-----------------------------------------
- Valor Medido:    ${measuredStr}
- Valor Nominal:   ${nominalStr}
- Rango Permitido: ${rangeStr}
- Desviación (Δ):  ${deltaStr}
- Estado:          ${ev.status_label || ev.status_badge || 'N/D'}

DIAGNÓSTICO Y RECOMENDACIÓN:
-----------------------------------------
${ev.recommendation || 'Sin recomendación registrada.'}

OBSERVACIONES DE CAMPO:
${ev.notes || 'Lectura de banco verificada según manual de servicio técnico.'}`;

        const tags = `multimetro, medicion, ${String(tpCode).toLowerCase()}, ${ev.subsystem || 'linac'}`;

        if (typeof window.irA === "function") {
            window.irA("Notes");
        }
        if (typeof window.abrirFormNota === "function") {
            window.abrirFormNota();
        }

        const inputTit = document.getElementById("notaTit");
        const inputTxt = document.getElementById("notaTxt");
        const inputTags = document.getElementById("notaTags");

        if (inputTit) inputTit.value = titulo;
        if (inputTxt) inputTxt.value = contenido;
        if (inputTags) inputTags.value = tags;

        if (typeof window.toast === "function") {
            window.toast("Medición transferida al formulario de Apuntes", "ok");
        }
    }

    function exportarRegistroHistorial(idx) {
        if (_history[idx]) {
            exportarAApuntes(_history[idx]);
        }
    }

    // ─── NAVEGACIÓN Y SINCRONIZACIÓN CON ESQUEMAS Y TRAZAS ────────────────
    function verEnPlanoSvg(tpId) {
        const tp = resolverPuntoDePrueba(tpId || _activeTpId, true);
        cerrarInspectorModal();

        if (typeof window.irA === "function") {
            window.irA("Circuits");
        }

        // Si el punto de prueba pertenece a la categoría general, mapear al subsistema donde reside
        let subId = tp.subsystem;
        let targetNodeId = tp.id;
        if (subId === "general" || !subId) {
            subId = "safety_loop";
            if (tp.id === "GEN_VOLT_24") targetNodeId = "PSU_24V";
            else if (tp.id === "GEN_CONT_LOOP") targetNodeId = "ESTOP_CONSOLE";
            else targetNodeId = "TP1";
        }

        const cambiarSubsistemaYAislar = () => {
            if (window.CircuitVisualizer) {
                if (typeof window.CircuitVisualizer.cambiarSubsistema === "function") {
                    window.CircuitVisualizer.cambiarSubsistema(subId);
                }
                setTimeout(() => {
                    if (typeof window.CircuitVisualizer.resaltarUnicoNodo === "function") {
                        window.CircuitVisualizer.resaltarUnicoNodo(targetNodeId);
                    }
                }, 120);
            }
        };

        if (window.requestAnimationFrame) {
            window.requestAnimationFrame(() => setTimeout(cambiarSubsistemaYAislar, 60));
        } else {
            setTimeout(cambiarSubsistemaYAislar, 80);
        }
    }

    function trazarEnDiagnostico(componentCode) {
        cerrarInspectorModal();
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

    // ─── CAMBIO DE PUNTO DE PRUEBA ACTIVO ────────────────────────────────
    function seleccionarPuntoDePrueba(tpId) {
        const tp = resolverPuntoDePrueba(tpId, true);
        _activeTpId = tp.id;
        _currentInputStr = ""; // Limpiar entrada previa para evitar falsas alarmas de desviación

        // Actualizar selectores
        const selScreen = document.getElementById("dmmTpSelect");
        if (selScreen) selScreen.value = _activeTpId;
        const selModal = document.getElementById("dmmModalTpSelect");
        if (selModal) selModal.value = _activeTpId;

        // Actualizar badges e info en pantalla principal
        const infoNominal = document.getElementById("dmmInfoNominal");
        if (infoNominal) infoNominal.textContent = `${tp.nominal.toFixed(1)} ${tp.unit}`;
        const infoTol = document.getElementById("dmmInfoTol");
        if (infoTol) infoTol.textContent = `${tp.tolerance_min.toFixed(1)} a ${tp.tolerance_max.toFixed(1)} ${tp.unit}`;
        const infoRole = document.getElementById("dmmInfoRole");
        if (infoRole) infoRole.textContent = `${tp.name} (${tp.subsystem_name}): ${tp.role}`;

        // Actualizar badges e info en modal flotante
        const modalNominal = document.getElementById("dmmModalInfoNominal");
        if (modalNominal) modalNominal.textContent = `${tp.nominal.toFixed(1)} ${tp.unit}`;
        const modalTol = document.getElementById("dmmModalInfoTol");
        if (modalTol) modalTol.textContent = `${tp.tolerance_min.toFixed(1)} a ${tp.tolerance_max.toFixed(1)} ${tp.unit}`;

        actualizarDisplayManual();
        renderizarPresetsDinamicos();

        // En simulación continua, el siguiente ciclo del timer leerá automáticamente el nuevo punto
    }

    // ─── CAMBIO DE MODO DE OPERACIÓN ─────────────────────────────────────
    function cambiarModo(modo) {
        _activeMode = modo;
        pausarTelemetriaVirtual();

        ["manual", "simulation", "hardware"].forEach(m => {
            const tabBtn = document.getElementById(`dmmTab_${m}`);
            const panel = document.getElementById(`dmmPanel_${m}`);
            if (tabBtn) tabBtn.classList.toggle("active", m === modo);
            if (panel) panel.style.display = m === modo ? "block" : "none";
        });

        if (modo === "simulation") {
            capturarMuestraSimulada();
        }
    }

    // ─── MODAL FLOTANTE DOCK INSPECTOR ───────────────────────────────────
    function abrirInspectorModal(tpId) {
        if (tpId) seleccionarPuntoDePrueba(tpId);
        _isModalOpen = true;

        let modal = document.getElementById("dmmFloatingModal");
        if (!modal) {
            crearModalFlotante();
            modal = document.getElementById("dmmFloatingModal");
        }

        if (modal) {
            modal.style.display = "flex";
            const tp = resolverPuntoDePrueba(_activeTpId, true);
            const tit = document.getElementById("dmmModalTitle");
            if (tit) tit.textContent = `${tp.code} · ${tp.name}`;

            const modalNominal = document.getElementById("dmmModalInfoNominal");
            if (modalNominal) modalNominal.textContent = `${tp.nominal.toFixed(1)} ${tp.unit}`;
            const modalTol = document.getElementById("dmmModalInfoTol");
            if (modalTol) modalTol.textContent = `${tp.tolerance_min.toFixed(1)} a ${tp.tolerance_max.toFixed(1)} ${tp.unit}`;

            actualizarDisplayManual();
            renderizarPresetsDinamicos();
        }
    }

    function cerrarInspectorModal() {
        _isModalOpen = false;
        const modal = document.getElementById("dmmFloatingModal");
        if (modal) modal.style.display = "none";
        pausarTelemetriaVirtual();
    }

    function crearModalFlotante() {
        const div = document.createElement("div");
        div.id = "dmmFloatingModal";
        div.style.cssText = "display:none;position:fixed;inset:0;background:rgba(11,15,26,0.85);z-index:2500;align-items:center;justify-content:center;padding:14px;backdrop-filter:blur(6px);";
        
        // Cerrar al tocar el fondo oscuro exterior
        div.addEventListener("click", (e) => {
            if (e.target === div) {
                cerrarInspectorModal();
            }
        });

        const tp = resolverPuntoDePrueba(_activeTpId, true);

        div.innerHTML = `
        <div style="background:var(--surface);border:1px solid var(--border);border-top:4px solid var(--accent);border-radius:12px;width:100%;max-width:520px;max-height:90vh;display:flex;flex-direction:column;box-shadow:0 15px 40px rgba(0,0,0,0.7);overflow:hidden;">
            <div style="padding:12px 16px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;background:rgba(255,255,255,0.02);">
                <div style="display:flex;align-items:center;gap:8px;">
                    <span style="font-size:1.1rem;">📟</span>
                    <div>
                        <h3 id="dmmModalTitle" style="font-size:0.95rem;color:var(--text);margin:0;font-weight:700;">Multímetro Digital</h3>
                        <span style="font-size:0.65rem;color:var(--muted);font-family:var(--mono);">MODO ENTRADA RÁPIDA &amp; BANCO</span>
                    </div>
                </div>
                <button type="button" data-dmm-action="cerrar-modal" style="background:none;border:none;color:var(--muted);font-size:1.3rem;cursor:pointer;padding:4px 8px;">✕</button>
            </div>
            <div style="padding:14px;overflow-y:auto;-webkit-overflow-scrolling:touch;flex:1;">
                <div style="margin-bottom:10px;background:rgba(0,0,0,0.2);padding:8px 10px;border-radius:8px;border:1px solid var(--border);">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
                        <label style="font-size:0.7rem;color:var(--muted);font-family:var(--mono);">Punto de Prueba Activo:</label>
                        <div style="font-family:var(--mono);font-size:0.7rem;display:flex;gap:8px;">
                            <span style="color:var(--muted)">Nominal: <strong id="dmmModalInfoNominal" style="color:var(--text);">${tp.nominal.toFixed(1)} ${tp.unit}</strong></span>
                            <span style="color:var(--muted)">Tol: <strong id="dmmModalInfoTol" style="color:var(--green);">${tp.tolerance_min.toFixed(1)} a ${tp.tolerance_max.toFixed(1)} ${tp.unit}</strong></span>
                        </div>
                    </div>
                    <select id="dmmModalTpSelect" style="padding-left:10px;">
                        ${generarOpcionesPuntosPrueba()}
                    </select>
                </div>

                <div style="background:rgba(0,212,255,0.04);border:1px solid rgba(0,212,255,0.2);border-radius:8px;padding:8px 10px;margin-bottom:10px;font-size:0.7rem;color:var(--muted);line-height:1.4;">
                    <strong style="color:var(--accent);">Guía rápida:</strong> Introduce la lectura de tu multímetro de taller con el teclado numérico o presets y pulsa <b style="color:var(--accent);">OK</b> para evaluar tolerancias nominales. Puedes inyectar lecturas con <b style="color:var(--accent);">Inyectar Lectura Simulada</b> o exportar a notas de campo con <b style="color:var(--accent);">Guardar en Mis Apuntes</b>. Para telemetría continua y enlace digital BLE/USB, pulsa <i>Ver Pantalla Completa</i>.
                </div>

                <div id="dmmModalKeypadWrap">
                    <!-- Display LCD Estilo Instrumento en Modal -->
                    <div style="background:#050d18;border:2px solid rgba(0,212,255,0.4);border-radius:10px;padding:12px 16px;margin-bottom:12px;box-shadow:inset 0 2px 10px rgba(0,0,0,0.8);position:relative;">
                        <div style="display:flex;justify-content:space-between;align-items:center;font-family:var(--mono);font-size:0.65rem;color:var(--muted);margin-bottom:4px;">
                            <span style="color:var(--accent);">HOLD · AUTO-RANGE</span>
                            <span style="color:var(--green);">100% OFFLINE</span>
                        </div>
                        <div style="display:flex;justify-content:flex-end;align-items:baseline;gap:8px;">
                            <span id="dmmModalDisplayValue" style="font-family:'Share Tech Mono',monospace;font-size:2.4rem;font-weight:700;color:#00d4ff;letter-spacing:0.06em;text-shadow:0 0 12px rgba(0,212,255,0.6);">0.00</span>
                            <span id="dmmModalDisplayUnit" style="font-family:'Share Tech Mono',monospace;font-size:1.2rem;color:var(--muted);font-weight:700;">${tp.unit}</span>
                        </div>
                    </div>

                    <!-- Presets Rápidos Linac Dinámicos -->
                    <div style="margin-bottom:10px;">
                        <div style="font-size:0.65rem;font-family:var(--mono);color:var(--muted);margin-bottom:4px;">PRESETS RÁPIDOS LINAC:</div>
                        <div id="dmmModalDynamicPresets" style="display:flex;gap:5px;flex-wrap:wrap;"></div>
                    </div>

                    <!-- Teclado Numérico Táctil Modal -->
                    <div style="display:grid;grid-template-columns:repeat(4, 1fr);gap:6px;max-width:320px;margin:0 auto 12px;">
                        <button type="button" class="btn btn-ghost" data-dmm-keypad="7" style="font-size:1.1rem;font-weight:700;padding:12px 0;">7</button>
                        <button type="button" class="btn btn-ghost" data-dmm-keypad="8" style="font-size:1.1rem;font-weight:700;padding:12px 0;">8</button>
                        <button type="button" class="btn btn-ghost" data-dmm-keypad="9" style="font-size:1.1rem;font-weight:700;padding:12px 0;">9</button>
                        <button type="button" class="btn btn-danger" data-dmm-keypad="C" style="font-size:0.85rem;padding:12px 0;">CLR</button>

                        <button type="button" class="btn btn-ghost" data-dmm-keypad="4" style="font-size:1.1rem;font-weight:700;padding:12px 0;">4</button>
                        <button type="button" class="btn btn-ghost" data-dmm-keypad="5" style="font-size:1.1rem;font-weight:700;padding:12px 0;">5</button>
                        <button type="button" class="btn btn-ghost" data-dmm-keypad="6" style="font-size:1.1rem;font-weight:700;padding:12px 0;">6</button>
                        <button type="button" class="btn btn-ghost" data-dmm-keypad="BS" style="font-size:0.9rem;padding:12px 0;">⌫</button>

                        <button type="button" class="btn btn-ghost" data-dmm-keypad="1" style="font-size:1.1rem;font-weight:700;padding:12px 0;">1</button>
                        <button type="button" class="btn btn-ghost" data-dmm-keypad="2" style="font-size:1.1rem;font-weight:700;padding:12px 0;">2</button>
                        <button type="button" class="btn btn-ghost" data-dmm-keypad="3" style="font-size:1.1rem;font-weight:700;padding:12px 0;">3</button>
                        <button type="button" class="btn btn-ghost" data-dmm-keypad="±" style="font-size:0.95rem;padding:12px 0;">±</button>

                        <button type="button" class="btn btn-ghost" data-dmm-keypad="0" style="grid-column:span 2;font-size:1.1rem;font-weight:700;padding:12px 0;">0</button>
                        <button type="button" class="btn btn-ghost" data-dmm-keypad="." style="font-size:1.2rem;font-weight:700;padding:12px 0;">.</button>
                        <button type="button" class="btn btn-primary" data-dmm-action="procesar" style="font-size:0.85rem;padding:12px 0;box-shadow:0 0 10px rgba(0,212,255,0.3);">OK</button>
                    </div>

                    <!-- Atajo para simular muestra instantánea -->
                    <div style="display:flex;justify-content:center;gap:8px;margin-bottom:10px;">
                        <button type="button" class="btn btn-ghost btn-sm" data-dmm-action="sim-muestra" style="font-size:0.75rem;">⚡ Inyectar Lectura Simulada</button>
                    </div>
                </div>
                <div id="dmmModalResultWrap" style="margin-top:12px;"></div>
            </div>
            <div style="padding:10px 16px;border-top:1px solid var(--border);background:rgba(0,0,0,0.25);display:flex;justify-content:space-between;align-items:center;">
                <button type="button" class="btn btn-ghost btn-sm" data-dmm-action="pantalla-completa">Ver Pantalla Completa</button>
                <button type="button" class="btn btn-primary btn-sm" data-dmm-action="cerrar-modal">Listo</button>
            </div>
        </div>`;

        const modalSelect = div.querySelector("#dmmModalTpSelect");
        if (modalSelect) {
            modalSelect.addEventListener("change", (e) => {
                seleccionarPuntoDePrueba(e.target.value);
            });
        }
        div.addEventListener("click", (e) => {
            const btn = e.target.closest("[data-dmm-keypad], [data-dmm-action], [data-dmm-preset]");
            if (!btn) return;
            e.preventDefault();
            if (btn.dataset.dmmKeypad) {
                keypadPress(btn.dataset.dmmKeypad);
            } else if (btn.dataset.dmmPreset) {
                aplicarPreset(parseFloat(btn.dataset.dmmPreset));
            } else if (btn.dataset.dmmAction === "cerrar-modal") {
                cerrarInspectorModal();
            } else if (btn.dataset.dmmAction === "procesar") {
                procesarLecturaManual();
            } else if (btn.dataset.dmmAction === "sim-muestra") {
                capturarMuestraSimulada();
            } else if (btn.dataset.dmmAction === "pantalla-completa") {
                abrirPantallaCompleta();
            } else if (btn.dataset.dmmAction === "exportar-apuntes") {
                exportarAApuntes();
            } else if (btn.dataset.dmmAction === "ver-plano") {
                verEnPlanoSvg(btn.dataset.tpId);
            } else if (btn.dataset.dmmAction === "trazar") {
                trazarEnDiagnostico(btn.dataset.tpCode);
            }
        });
        document.body.appendChild(div);
    }

    function abrirPantallaCompleta() {
        cerrarInspectorModal();
        if (typeof window.irA === "function") {
            window.irA("Multimeter");
        }
    }

    function generarOpcionesPuntosPrueba() {
        const groups = {
            "safety_loop": "Bucle de Seguridad",
            "radiation_beam": "Radiación y Modulador RF",
            "dosimetry": "Dosimetría Doble Canal",
            "gantry_collimator": "Gantry y Colimador",
            "vacuum_gun": "Vacío y Cañón de Electrones",
            "general": "Líneas de Alimentación General"
        };

        let html = "";
        for (const [subKey, subTitle] of Object.entries(groups)) {
            html += `<optgroup label="${subTitle}">`;
            for (const tp of Object.values(OFFLINE_CATALOG)) {
                if (tp.subsystem === subKey) {
                    const sel = tp.id === _activeTpId ? "selected" : "";
                    html += `<option value="${tp.id}" ${sel}>${tp.code} · ${tp.name} (${tp.nominal}${tp.unit})</option>`;
                }
            }
            html += `</optgroup>`;
        }
        return html;
    }

    // ─── CICLO DE VIDA (ACTIVAR / DESACTIVAR / VISIBILIDAD) ─────────────
    function onActivate() {
        const sel = document.getElementById("dmmTpSelect");
        if (sel && sel.options.length === 0) {
            sel.innerHTML = generarOpcionesPuntosPrueba();
            if (_activeTpId) sel.value = _activeTpId;
        }
        actualizarDisplayManual();
        renderizarPresetsDinamicos();
        renderHistorial();
    }

    function onDeactivate() {
        pausarTelemetriaVirtual();
        desconectarHardware();
        if (_audioContext && typeof _audioContext.suspend === "function") {
            _audioContext.suspend().catch(() => {});
        }
    }

    // ─── INICIALIZACIÓN Y EVENTOS DE ENTRADA ─────────────────────────────
    function init() {
        // Población dinámica de puntos de prueba desde catálogo canónico (Finding 4.6)
        const selScreen = document.getElementById("dmmTpSelect");
        if (selScreen) {
            selScreen.innerHTML = generarOpcionesPuntosPrueba();
            selScreen.value = _activeTpId;
            selScreen.addEventListener("change", (e) => {
                seleccionarPuntoDePrueba(e.target.value);
            });
        }

        const resBox = document.getElementById("dmmResultBox");
        if (resBox && !resBox.dataset.listenerAttached) {
            resBox.dataset.listenerAttached = "true";
            resBox.addEventListener("click", (e) => {
                const btn = e.target.closest("[data-dmm-action]");
                if (!btn) return;
                e.preventDefault();
                const act = btn.dataset.dmmAction;
                if (act === "exportar-apuntes") exportarAApuntes();
                else if (act === "ver-plano") verEnPlanoSvg(btn.dataset.tpId);
                else if (act === "trazar") trazarEnDiagnostico(btn.dataset.tpCode);
            });
        }

        const histList = document.getElementById("dmmHistoryList");
        if (histList && !histList.dataset.listenerAttached) {
            histList.dataset.listenerAttached = "true";
            histList.addEventListener("click", (e) => {
                const btn = e.target.closest("[data-dmm-action='exportar-registro']");
                if (!btn) return;
                e.preventDefault();
                exportarRegistroHistorial(parseInt(btn.dataset.idx, 10));
            });
        }

        const presetsMain = document.getElementById("dmmDynamicPresets");
        if (presetsMain && !presetsMain.dataset.listenerAttached) {
            presetsMain.dataset.listenerAttached = "true";
            presetsMain.addEventListener("click", (e) => {
                const btn = e.target.closest("[data-dmm-action='preset']");
                if (!btn) return;
                e.preventDefault();
                aplicarPreset(parseFloat(btn.dataset.val));
            });
        }

        // Escuchar cambios en campos de entrada física si tienen el foco
        const inputField = document.getElementById("dmmManualInputBox");
        if (inputField) {
            inputField.addEventListener("input", (e) => {
                _currentInputStr = e.target.value;
                actualizarDisplayManual();
            });
            inputField.addEventListener("keydown", (e) => {
                if (e.key === "Enter") {
                    e.preventDefault();
                    procesarLecturaManual();
                }
            });
        }

        // Listener global de teclado físico (Numpad y dígitos para banco de taller)
        document.addEventListener("keydown", (e) => {
            const scr = document.getElementById("screenMultimeter");
            const isScreenActive = scr && scr.classList.contains("active");
            if (!isScreenActive && !_isModalOpen) return;

            const tag = (e.target && e.target.tagName) ? e.target.tagName.toUpperCase() : "";
            const isEditable = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (e.target && e.target.isContentEditable);

            if (e.key === "Escape") {
                if (_isModalOpen) {
                    e.preventDefault();
                    cerrarInspectorModal();
                } else {
                    keypadPress("C");
                }
                return;
            }

            if (isEditable) {
                return;
            } else if (e.key >= "0" && e.key <= "9") {
                keypadPress(e.key);
            } else if (e.key === "." || e.key === ",") {
                keypadPress(".");
            } else if (e.key === "-" || e.key === "_") {
                keypadPress("±");
            } else if (e.key === "Backspace") {
                keypadPress("BS");
            } else if (e.key === "Enter") {
                e.preventDefault();
                procesarLecturaManual();
            }
        });

        // Pausa automática de simulación cuando la pestaña se minimiza o se bloquea la pantalla
        document.addEventListener("visibilitychange", () => {
            if (document.visibilityState === "hidden") {
                if (_simulationIntervalId) {
                    pausarTelemetriaVirtual();
                    _pausedByVisibility = true;
                }
                if (_audioContext && _audioContext.state === "running") {
                    _audioContext.suspend().catch(() => {});
                }
            } else if (document.visibilityState === "visible") {
                if (_pausedByVisibility) {
                    _pausedByVisibility = false;
                    iniciarTelemetriaVirtual();
                }
            }
        });

        renderizarPresetsDinamicos();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

    // ─── API PÚBLICA EXPUESTA ─────────────────────────────────────────────
    window.Multimeter = {
        get OFFLINE_CATALOG() { return OFFLINE_CATALOG; },
        NODE_TO_TP_MAP: NODE_TO_TP_MAP,
        evaluarLectura: evaluarLectura,
        generarLecturaSimulada: generarLecturaSimulada,
        resolverPuntoDePrueba: resolverPuntoDePrueba,
        seleccionarPuntoDePrueba: seleccionarPuntoDePrueba,
        keypadPress: keypadPress,
        aplicarPreset: aplicarPreset,
        procesarLecturaManual: procesarLecturaManual,
        cambiarModo: cambiarModo,
        iniciarTelemetriaVirtual: iniciarTelemetriaVirtual,
        pausarTelemetriaVirtual: pausarTelemetriaVirtual,
        capturarMuestraSimulada: capturarMuestraSimulada,
        cambiarFallaSimulada: cambiarFallaSimulada,
        conectarBluetooth: conectarBluetooth,
        conectarSerial: conectarSerial,
        desconectarHardware: desconectarHardware,
        abrirInspectorModal: abrirInspectorModal,
        cerrarInspectorModal: cerrarInspectorModal,
        abrirPantallaCompleta: abrirPantallaCompleta,
        exportarAApuntes: exportarAApuntes,
        exportarRegistroHistorial: exportarRegistroHistorial,
        limpiarHistorial: limpiarHistorial,
        verEnPlanoSvg: verEnPlanoSvg,
        trazarEnDiagnostico: trazarEnDiagnostico,
        toggleBuzzer: function (enabled) { _audioBuzzerEnabled = !!enabled; },
        onActivate: onActivate,
        onDeactivate: onDeactivate,
        generarOpcionesPuntosPrueba: generarOpcionesPuntosPrueba
    };

})(window, document);
