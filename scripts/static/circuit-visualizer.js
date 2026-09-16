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
    const EMBEDDED_SUBSYSTEMS = {"safety_loop": {"id": "safety_loop", "name": "Bucle de Seguridad de Interlocks (Safety Loop Chain)", "short_name": "Bucle de Seguridad", "badge": "24V DC / Interlocks", "icon": "🔒", "description": "Cadena de seguridad en serie de 24V DC: pulsadores de parada de emergencia, switches de colisión, llave de servicio y contactores de potencia K1/K2.", "manual_references": ["diagrams (Pág 14)", "technical (Pág 82)", "power_supplies (Pág 24)"], "viewBox": "0 0 1200 680", "nodes": [{"id": "PSU_24V", "code": "PSU1 +24V", "name": "Fuente 24V DC Seguridad", "type": "source", "x": 50, "y": 140, "width": 150, "height": 75, "spec": "24.0V DC ± 0.5V (Alimentación primaria de bucle de seguridad)", "manual": "power_supplies", "page": 24, "role": "Alimentación primaria aislada del lazo de parada"}, {"id": "TP1", "code": "TP1", "name": "Punto de Prueba TP1", "type": "test_point", "x": 240, "y": 155, "width": 60, "height": 42, "spec": "24.0V DC (Alimentación bucle OK)", "manual": "diagrams", "page": 14, "role": "Monitor de tensión positiva de entrada de cadena"}, {"id": "ESTOP_CONSOLE", "code": "E-STOP CON", "name": "Seta Parada Consola", "type": "switch", "x": 340, "y": 140, "width": 130, "height": 75, "spec": "Contacto NC 24V / 2A (Pulsador seta con enclavamiento mecánico)", "manual": "diagrams", "page": 14, "role": "Parada de emergencia en mesa de control exterior"}, {"id": "ESTOP_GANTRY", "code": "E-STOP GAN", "name": "Seta Parada Gantry", "type": "switch", "x": 510, "y": 140, "width": 130, "height": 75, "spec": "Contacto NC Doble Canal (Pulsadores en frontales de estativo)", "manual": "diagrams", "page": 14, "role": "Parada de emergencia en estativo del acelerador"}, {"id": "ESTOP_ROOM", "code": "E-STOP ROOM", "name": "Pulsador Bunker Sala", "type": "switch", "x": 680, "y": 140, "width": 130, "height": 75, "spec": "Contacto NC en pared interior del búnker", "manual": "diagrams", "page": 14, "role": "Parada de emergencia en paredes perimetrales de sala"}, {"id": "TP2", "code": "TP2", "name": "Punto de Prueba TP2", "type": "test_point", "x": 850, "y": 155, "width": 60, "height": 42, "spec": "24.0V DC (Retorno pulsadores de emergencia cerrado)", "manual": "diagrams", "page": 15, "role": "Verificación de continuidad en bucle de setas"}, {"id": "DOOR_SW_283", "code": "INTERLOCK 283", "name": "Puerta Bunker (Sw 283)", "type": "interlock", "x": 950, "y": 140, "width": 160, "height": 75, "spec": "ITEM 2283 Microswitch NC + Sensor magnético de acceso", "manual": "diagrams", "page": 15, "role": "Enclavamiento de puerta de acceso a la sala de tratamiento"}, {"id": "COLLISION_HEAD", "code": "ANTI-CRASH", "name": "Colisión Cabezal", "type": "interlock", "x": 950, "y": 300, "width": 160, "height": 75, "spec": "Anillo capacitivo / microswitches perimetrales NC", "manual": "accessory", "page": 42, "role": "Protección contra impacto mecánico de cabezal y aplicadores"}, {"id": "KEY_SWITCH_IS1", "code": "KEY IS1", "name": "Llave Servicio IS1", "type": "switch", "x": 750, "y": 300, "width": 145, "height": 75, "spec": "Enclavamiento de llave física en consola de control", "manual": "technical", "page": 82, "role": "Habilitación de operación por personal autorizado"}, {"id": "INTLK_202", "code": "INTERLOCK 202", "name": "Permisivo Vacío/Agua", "type": "interlock", "x": 550, "y": 300, "width": 150, "height": 75, "spec": "Relé de circuito de refrigeración por agua y presión de vacío OK", "manual": "diagrams", "page": 16, "role": "Enclavamiento preventivo de subsistemas auxiliares"}, {"id": "PCB_16N", "code": "PCB 16N", "name": "Placa Lógica de Seguridad", "type": "pcb", "x": 260, "y": 290, "width": 230, "height": 100, "spec": "Safety Loop Logic Controller & Interlock Monitor", "manual": "diagrams", "page": 14, "role": "Procesamiento lógico de enclavamientos y excitación de relés"}, {"id": "TP5", "code": "TP5", "name": "Punto de Prueba TP5", "type": "test_point", "x": 160, "y": 325, "width": 60, "height": 42, "spec": "24.0V DC (Driver de contactores activo / permisivo OK)", "manual": "diagrams", "page": 16, "role": "Salida de control hacia bobinas de contactores"}, {"id": "RELAY_K1", "code": "RELAY K1", "name": "Contactor Potencia K1", "type": "relay", "x": 150, "y": 480, "width": 165, "height": 85, "spec": "Bobina 24V DC / Contactos 380V Trifásica de Red", "manual": "diagrams", "page": 18, "role": "Contactor maestro de alimentación trifásica de potencia"}, {"id": "RELAY_K2", "code": "RELAY K2", "name": "Contactor Auxiliar K2", "type": "relay", "x": 370, "y": 480, "width": 165, "height": 85, "spec": "Bobina 24V DC / Permisivo de Generación de Alta Tensión", "manual": "diagrams", "page": 18, "role": "Habilitación redundante de etapa de alta tensión"}, {"id": "CABLE_W10", "code": "CABLE W10", "name": "Mazo W10 Consola-Gantry", "type": "cable", "x": 600, "y": 490, "width": 170, "height": 65, "spec": "Mazo 12x0.75mm² apantallado con malla a tierra", "manual": "diagrams", "page": 14, "role": "Conducción de señales de parada y colisiones hacia PCB 16N"}, {"id": "CABLE_W12", "code": "CABLE W12", "name": "Línea Bobinas W12", "type": "cable", "x": 820, "y": 490, "width": 160, "height": 65, "spec": "Línea de control de bobinas K1/K2 4x1.5mm²", "manual": "diagrams", "page": 18, "role": "Alimentación de bobinas de contactores de potencia"}, {"id": "PL1", "code": "PL1", "name": "Conector PL1", "type": "connector", "x": 510, "y": 250, "width": 60, "height": 34, "spec": "Conector Harting de 24 pines (E/S Seguridad)", "manual": "diagrams", "page": 14, "role": "Interfaz de mazo de interlocks en PCB 16N"}, {"id": "SK1", "code": "SK1", "name": "Zócalo SK1", "type": "connector", "x": 200, "y": 250, "width": 60, "height": 34, "spec": "Zócalo chasis retorno de bucle", "manual": "diagrams", "page": 14, "role": "Punto de interconexión con fuente de seguridad"}], "wires": [{"id": "W1", "from": "PSU_24V", "to": "TP1", "points": [[200, 175], [240, 175]], "label": "+24V", "type": "power"}, {"id": "W2", "from": "TP1", "to": "ESTOP_CONSOLE", "points": [[300, 175], [340, 175]], "label": "SAFE_BUS", "type": "power"}, {"id": "W3", "from": "ESTOP_CONSOLE", "to": "ESTOP_GANTRY", "points": [[470, 175], [510, 175]], "label": "NC_LOOP", "type": "safety"}, {"id": "W4", "from": "ESTOP_GANTRY", "to": "ESTOP_ROOM", "points": [[640, 175], [680, 175]], "label": "NC_LOOP", "type": "safety"}, {"id": "W5", "from": "ESTOP_ROOM", "to": "TP2", "points": [[810, 175], [850, 175]], "label": "SAFE_RTN", "type": "safety"}, {"id": "W6", "from": "TP2", "to": "DOOR_SW_283", "points": [[910, 175], [950, 175]], "label": "DOOR_IN", "type": "safety"}, {"id": "W7", "from": "DOOR_SW_283", "to": "COLLISION_HEAD", "points": [[1030, 215], [1030, 300]], "label": "SERIES_BUS", "type": "safety"}, {"id": "W8", "from": "COLLISION_HEAD", "to": "KEY_SWITCH_IS1", "points": [[950, 337], [895, 337]], "label": "CRASH_OK", "type": "safety"}, {"id": "W9", "from": "KEY_SWITCH_IS1", "to": "INTLK_202", "points": [[750, 337], [700, 337]], "label": "KEY_OK", "type": "safety"}, {"id": "W10", "from": "INTLK_202", "to": "PL1", "points": [[550, 337], [540, 337], [540, 284]], "label": "LOOP_COMPL", "type": "safety"}, {"id": "W11", "from": "PL1", "to": "PCB_16N", "points": [[510, 267], [450, 267], [450, 290]], "label": "INTLK_STATUS", "type": "signal"}, {"id": "W12", "from": "PCB_16N", "to": "TP5", "points": [[260, 345], [220, 345]], "label": "COIL_DRV", "type": "signal"}, {"id": "W13", "from": "TP5", "to": "RELAY_K1", "points": [[190, 367], [190, 480]], "label": "24V_COIL", "type": "power"}, {"id": "W14", "from": "RELAY_K1", "to": "RELAY_K2", "points": [[315, 522], [370, 522]], "label": "AUX_EN", "type": "power"}, {"id": "W15", "from": "RELAY_K2", "to": "CABLE_W10", "points": [[535, 522], [600, 522]], "label": "W10_BUS", "type": "cable"}, {"id": "W16", "from": "CABLE_W10", "to": "CABLE_W12", "points": [[770, 522], [820, 522]], "label": "W12_BUS", "type": "cable"}, {"id": "W17", "from": "PCB_16N", "to": "SK1", "points": [[260, 310], [230, 310], [230, 284]], "label": "CHAS_GND", "type": "power"}]}, "radiation_beam": {"id": "radiation_beam", "name": "Habilitación de Radiación y Modulador RF (Radiation Enable / RF Driver)", "short_name": "Radiación y Modulador RF", "badge": "45kV / RF Banda-S", "icon": "⚡", "description": "Cadena de generación de pulso RF: permisivo de radiación, señal ITEM 409, disparo ITEM 474, tiratrón PFN, magnetrón/klistrón y protección de potencia inversa.", "manual_references": ["ht_rf (Pág 22)", "diagrams (Pág 45)", "beam physics (Pág 18)"], "viewBox": "0 0 1200 680", "nodes": [{"id": "PCB_16N", "code": "PCB 16N", "name": "Permisivo Maestro de Seguridad", "type": "pcb", "x": 50, "y": 140, "width": 180, "height": 80, "spec": "Master Safety Interlock Permissive (24V nivel alto)", "manual": "diagrams", "page": 14, "role": "Habilitación general de estado de tratamiento"}, {"id": "ITEM_409", "code": "ITEM 409", "name": "Señal RAD_ON Consola", "type": "signal", "x": 270, "y": 140, "width": 150, "height": 80, "spec": "ITEM 409 / Comando digital de inicio de emisión", "manual": "catalogue", "page": 62, "role": "Señal emitida por el operador desde consola para iniciar radiación"}, {"id": "PCB_22", "code": "PCB 22", "name": "Placa Control Modulador", "type": "pcb", "x": 470, "y": 130, "width": 210, "height": 100, "spec": "Modulator Timing, Pulse Generator & Bias Board", "manual": "ht_rf", "page": 22, "role": "Sincronización de pulsos y control de disparo de tiratrón"}, {"id": "ITEM_474", "code": "ITEM 474", "name": "Trigger Disparo Rejilla", "type": "signal", "x": 720, "y": 140, "width": 145, "height": 80, "spec": "ITEM 474 / Pulso TTL de 5V y 500ns de duración", "manual": "ht_rf", "page": 25, "role": "Comando de disparo rápido hacia etapa excitadora de rejilla"}, {"id": "TP3", "code": "TP3", "name": "Punto de Prueba TP3", "type": "test_point", "x": 900, "y": 155, "width": 60, "height": 42, "spec": "800V pico / 3.5µs (Pulso de rejilla de tiratrón)", "manual": "ht_rf", "page": 26, "role": "Monitor de forma de onda del pulso de disparo"}, {"id": "THYRATRON_V1", "code": "TIRATRÓN V1", "name": "Tubo Tiratrón Cerámico", "type": "load", "x": 995, "y": 130, "width": 165, "height": 95, "spec": "Tubo cerámico de hidrógeno conmutador 45kV / 500A pico", "manual": "ht_rf", "page": 28, "role": "Conmutación ultrarrápida para descarga de la red PFN"}, {"id": "PFN_LINE", "code": "PFN LINE", "name": "Pulse Forming Network", "type": "load", "x": 995, "y": 290, "width": 165, "height": 85, "spec": "Red LC de 5 Ohms / Pulso de alta tensión 45kV conformada", "manual": "ht_rf", "page": 30, "role": "Formación de pulso cuadrado rectangular de 3.5µs"}, {"id": "HT_SUPPLY", "code": "HT SUPPLY", "name": "Fuente Alta Tensión Tank", "type": "source", "x": 730, "y": 290, "width": 170, "height": 85, "spec": "10kV - 18kV DC en baño de aceite dieléctrico", "manual": "ht_rf", "page": 34, "role": "Alimentación de carga de la red formadora de pulsos"}, {"id": "TP_HT", "code": "TP_HT", "name": "Punto de Prueba TP_HT", "type": "test_point", "x": 630, "y": 310, "width": 65, "height": 42, "spec": "Divisor resistivo 1:1000 (1V medido = 1kV en tanque)", "manual": "ht_rf", "page": 35, "role": "Monitoreo seguro de la tensión continua del modulador"}, {"id": "MAGNETRON_M1", "code": "MAGNETRÓN M1", "name": "Magnetrón / Klistrón Banda-S", "type": "load", "x": 985, "y": 460, "width": 180, "height": 95, "spec": "2.998 GHz / Potencia pico 2.5 MW microondas", "manual": "ht_rf", "page": 40, "role": "Generación de microondas para aceleración de electrones"}, {"id": "CIRCULATOR", "code": "CIRCULADOR RF", "name": "Circulador 4 Puertos", "type": "load", "x": 740, "y": 465, "width": 160, "height": 85, "spec": "Ferrita no recíproca con carga de agua atenuadora", "manual": "ht_rf", "page": 44, "role": "Protege el magnetrón contra ondas reflejadas por la guía"}, {"id": "ITEM_394", "code": "ITEM 394", "name": "Potencia Inversa Inhibit", "type": "interlock", "x": 520, "y": 470, "width": 160, "height": 75, "spec": "ITEM 394 / Disparo por potencia reflejada > 15%", "manual": "ht_rf", "page": 46, "role": "Interlock de corte de radiación por desacoplo de RF"}, {"id": "RF_DRIVER_AMP", "code": "RF DRIVER", "name": "Excitador Driver RF", "type": "source", "x": 300, "y": 465, "width": 165, "height": 85, "spec": "Amplificador transistorizado clase C 200W RF", "manual": "ht_rf", "page": 48, "role": "Generación de señal piloto de radiofrecuencia precisa"}, {"id": "TP_RF", "code": "TP_RF", "name": "Punto de Prueba TP_RF", "type": "test_point", "x": 190, "y": 485, "width": 65, "height": 42, "spec": "Muestreador atenuador coaxial de -50dB", "manual": "ht_rf", "page": 50, "role": "Punto de muestreo para analizador de espectros / detector"}, {"id": "CABLE_W20", "code": "CABLE W20", "name": "Coaxial Disparo HT W20", "type": "cable", "x": 50, "y": 320, "width": 160, "height": 65, "spec": "Cable de alta tensión blindado RG-213", "manual": "diagrams", "page": 45, "role": "Conducción de impulsos de disparo con apantallamiento total"}, {"id": "CABLE_W22", "code": "CABLE W22", "name": "Línea Disparo W22", "type": "cable", "x": 50, "y": 475, "width": 160, "height": 65, "spec": "Línea coaxial de baja inductancia para pulsos rápidos", "manual": "diagrams", "page": 45, "role": "Distribución de pulsos de RF sincronizados"}], "wires": [{"id": "W201", "from": "PCB_16N", "to": "ITEM_409", "points": [[230, 180], [270, 180]], "label": "PERM_OK", "type": "safety"}, {"id": "W202", "from": "ITEM_409", "to": "PCB_22", "points": [[420, 180], [470, 180]], "label": "RAD_CMD", "type": "signal"}, {"id": "W203", "from": "PCB_22", "to": "ITEM_474", "points": [[680, 180], [720, 180]], "label": "TRIG_GEN", "type": "signal"}, {"id": "W204", "from": "ITEM_474", "to": "TP3", "points": [[865, 180], [900, 180]], "label": "GRID_PULSE", "type": "high_voltage"}, {"id": "W205", "from": "TP3", "to": "THYRATRON_V1", "points": [[960, 180], [995, 180]], "label": "GRID_FIRE", "type": "high_voltage"}, {"id": "W206", "from": "THYRATRON_V1", "to": "PFN_LINE", "points": [[1075, 225], [1075, 290]], "label": "DISCHARGE", "type": "high_voltage"}, {"id": "W207", "from": "HT_SUPPLY", "to": "PFN_LINE", "points": [[900, 332], [995, 332]], "label": "HT_CHARGE", "type": "high_voltage"}, {"id": "W208", "from": "HT_SUPPLY", "to": "TP_HT", "points": [[730, 332], [695, 332]], "label": "SENSE_DIV", "type": "signal"}, {"id": "W209", "from": "PFN_LINE", "to": "MAGNETRON_M1", "points": [[1075, 375], [1075, 460]], "label": "PULSE_45KV", "type": "high_voltage"}, {"id": "W210", "from": "MAGNETRON_M1", "to": "CIRCULATOR", "points": [[985, 507], [900, 507]], "label": "RF_WAVEGUIDE", "type": "rf"}, {"id": "W211", "from": "CIRCULATOR", "to": "ITEM_394", "points": [[740, 507], [680, 507]], "label": "REFL_SAMPLE", "type": "signal"}, {"id": "W212", "from": "ITEM_394", "to": "RF_DRIVER_AMP", "points": [[520, 507], [465, 507]], "label": "INHIBIT_ACT", "type": "safety"}, {"id": "W213", "from": "RF_DRIVER_AMP", "to": "TP_RF", "points": [[300, 507], [255, 507]], "label": "RF_SAMPLE", "type": "rf"}, {"id": "W214", "from": "TP_RF", "to": "CABLE_W22", "points": [[190, 507], [210, 507]], "label": "W22_COAX", "type": "cable"}, {"id": "W215", "from": "PCB_22", "to": "CABLE_W20", "points": [[575, 230], [575, 260], [130, 260], [130, 320]], "label": "W20_HT", "type": "cable"}]}, "dosimetry": {"id": "dosimetry", "name": "Dosimetría y Doble Canal Independiente (Dual Channel Dosimetry)", "short_name": "Dosimetría Doble Canal", "badge": "400V Bias / D_RATE 1 & 2", "icon": "🎯", "description": "Cámara de ionización plana de transmisión segmentada: polarización +400V HV, integración de carga analógica en PCB 17 y PCB 18, señales D_RATE 1/2 y corte redundante por Interlock 66.", "manual_references": ["dosimetry (Pág 18)", "technical (Pág 104)", "diagrams (Pág 22)"], "viewBox": "0 0 1200 680", "nodes": [{"id": "HV_BIAS_400V", "code": "+400V BIAS", "name": "Fuente Polarización HV", "type": "source", "x": 50, "y": 140, "width": 165, "height": 80, "spec": "+400.0V DC polarización constante de cámara", "manual": "dosimetry", "page": 12, "role": "Generación de campo eléctrico para colección de iones"}, {"id": "TP100", "code": "TP100", "name": "Punto de Prueba TP100", "type": "test_point", "x": 245, "y": 155, "width": 65, "height": 42, "spec": "+400V DC ± 2V (Monitor de Polarización)", "manual": "dosimetry", "page": 13, "role": "Verificación de estabilidad de la tensión de polarización"}, {"id": "ION_CHAMBER", "code": "ION CHAMBER", "name": "Cámara Ionización Dual", "type": "sensor", "x": 345, "y": 125, "width": 205, "height": 110, "spec": "Cámara plana sellada de transmisión con sectores A y B", "manual": "dosimetry", "page": 18, "role": "Detección y medida absoluta de radiación ionizante"}, {"id": "CABLE_W15", "code": "CABLE W15", "name": "Triaxial Cámara W15", "type": "cable", "x": 585, "y": 150, "width": 150, "height": 65, "spec": "Cable triaxial de bajísima corriente de fuga < 0.5 pA", "manual": "dosimetry", "page": 20, "role": "Conducción de corriente pA apantallada contra ruido"}, {"id": "PREAMP_CH1", "code": "PREAMP CH1", "name": "Preamplificador Canal 1", "type": "sensor", "x": 765, "y": 140, "width": 155, "height": 75, "spec": "Convertidor Corriente a Frecuencia (I/F) de alta linealidad", "manual": "dosimetry", "page": 22, "role": "Conversión de carga colectada en tren de impulsos"}, {"id": "PCB_17", "code": "PCB 17", "name": "Tarjeta Dosis Canal 1", "type": "pcb", "x": 955, "y": 120, "width": 200, "height": 100, "spec": "Integrador primario de Unidades Monitor (MU Channel 1)", "manual": "dosimetry", "page": 24, "role": "Cómputo principal de dosis acumulada y tasa instantánea"}, {"id": "D_RATE_1", "code": "D_RATE 1", "name": "Tasa Dosis Canal 1", "type": "signal", "x": 955, "y": 250, "width": 140, "height": 60, "spec": "D_RATE 1 / Voltaje proporcional a cGy/min (0 a +10V)", "manual": "dosimetry", "page": 26, "role": "Señal analógica de tasa de dosis para servocontrol de cañón"}, {"id": "TP_DOSE1", "code": "TP_DOSE1", "name": "Punto de Prueba TP_DOSE1", "type": "test_point", "x": 1115, "y": 260, "width": 70, "height": 42, "spec": "0-10V DC (1V = 100 cGy/min calibrado)", "manual": "dosimetry", "page": 27, "role": "Lectura directa en multímetro de la tasa de canal primario"}, {"id": "ITEM_327", "code": "ITEM 327", "name": "Límite Dosis 1 (Preset)", "type": "signal", "x": 765, "y": 250, "width": 155, "height": 65, "spec": "ITEM 327 / Comparador de dosis prescrita alcanzada", "manual": "catalogue", "page": 55, "role": "Señal de finalización normal del campo de tratamiento"}, {"id": "PREAMP_CH2", "code": "PREAMP CH2", "name": "Preamplificador Canal 2", "type": "sensor", "x": 765, "y": 380, "width": 155, "height": 75, "spec": "Canal independiente y físicamente aislado de Canal 1", "manual": "dosimetry", "page": 28, "role": "Pre-amplificación redundante de seguridad"}, {"id": "PCB_18", "code": "PCB 18", "name": "Tarjeta Dosis Canal 2", "type": "pcb", "x": 955, "y": 360, "width": 200, "height": 100, "spec": "Integrador redundante de backup (Channel 2 Backup)", "manual": "dosimetry", "page": 30, "role": "Monitoreo independiente de sobre-dosis"}, {"id": "D_RATE_2", "code": "D_RATE 2", "name": "Tasa Dosis Canal 2", "type": "signal", "x": 955, "y": 490, "width": 140, "height": 60, "spec": "D_RATE 2 / Señal analógica secundaria redundante", "manual": "dosimetry", "page": 32, "role": "Verificación de coincidencia con D_RATE 1"}, {"id": "TP_DOSE2", "code": "TP_DOSE2", "name": "Punto de Prueba TP_DOSE2", "type": "test_point", "x": 1115, "y": 500, "width": 70, "height": 42, "spec": "0-10V DC (Calibrado a tasa secundaria)", "manual": "dosimetry", "page": 33, "role": "Punto de prueba para contraste de calibración de canales"}, {"id": "ITEM_332", "code": "ITEM 332", "name": "Corte Backup Canal 2", "type": "signal", "x": 765, "y": 485, "width": 155, "height": 65, "spec": "ITEM 332 / Disparo por exceso de dosis (+10% MU o +25MU)", "manual": "catalogue", "page": 58, "role": "Disparo de seguridad en caso de fallo del canal primario"}, {"id": "INTLK_66", "code": "INTERLOCK 66", "name": "Fallo Desbalance Ratio", "type": "interlock", "x": 480, "y": 380, "width": 170, "height": 75, "spec": "INTERLOCK 66 / Disparo si desbalance |CH1 - CH2| > 3%", "manual": "diagrams", "page": 22, "role": "Enclavamiento crítico por fallo o asimetría entre canales"}, {"id": "BEAM_TERMINATE", "code": "BEAM TERMINATE", "name": "Relé Terminación de Haz", "type": "relay", "x": 250, "y": 380, "width": 180, "height": 80, "spec": "Relé de disparo ultrarrápido con corte de haz < 15ms", "manual": "diagrams", "page": 22, "role": "Desactiva inmediatamente el disparo del tiratrón y cañón"}, {"id": "CABLE_W16", "code": "CABLE W16", "name": "Línea Redundante W16", "type": "cable", "x": 50, "y": 390, "width": 155, "height": 65, "spec": "Mazo apantallado de señales dosimétricas de control", "manual": "dosimetry", "page": 21, "role": "Transmisión de estados de dosimetría hacia consola"}], "wires": [{"id": "W301", "from": "HV_BIAS_400V", "to": "TP100", "points": [[215, 175], [245, 175]], "label": "+400V", "type": "high_voltage"}, {"id": "W302", "from": "TP100", "to": "ION_CHAMBER", "points": [[310, 175], [345, 175]], "label": "BIAS_IN", "type": "high_voltage"}, {"id": "W303", "from": "ION_CHAMBER", "to": "CABLE_W15", "points": [[550, 175], [585, 175]], "label": "ION_CURRENT", "type": "signal"}, {"id": "W304", "from": "CABLE_W15", "to": "PREAMP_CH1", "points": [[735, 175], [765, 175]], "label": "CH1_pA", "type": "signal"}, {"id": "W305", "from": "PREAMP_CH1", "to": "PCB_17", "points": [[920, 175], [955, 175]], "label": "CH1_FREQ", "type": "signal"}, {"id": "W306", "from": "PCB_17", "to": "D_RATE_1", "points": [[1025, 220], [1025, 250]], "label": "ANALOG_VOLT", "type": "signal"}, {"id": "W307", "from": "D_RATE_1", "to": "TP_DOSE1", "points": [[1095, 280], [1115, 280]], "label": "DOSE_RATE", "type": "signal"}, {"id": "W308", "from": "PCB_17", "to": "ITEM_327", "points": [[955, 200], [840, 200], [840, 250]], "label": "PRESET_REACHED", "type": "signal"}, {"id": "W309", "from": "ION_CHAMBER", "to": "PREAMP_CH2", "points": [[500, 235], [500, 415], [765, 415]], "label": "CH2_pA", "type": "signal"}, {"id": "W310", "from": "PREAMP_CH2", "to": "PCB_18", "points": [[920, 415], [955, 415]], "label": "CH2_FREQ", "type": "signal"}, {"id": "W311", "from": "PCB_18", "to": "D_RATE_2", "points": [[1025, 460], [1025, 490]], "label": "ANALOG_VOLT", "type": "signal"}, {"id": "W312", "from": "D_RATE_2", "to": "TP_DOSE2", "points": [[1095, 520], [1115, 520]], "label": "DOSE_RATE", "type": "signal"}, {"id": "W313", "from": "PCB_18", "to": "ITEM_332", "points": [[955, 440], [840, 440], [840, 485]], "label": "BACKUP_TRIP", "type": "safety"}, {"id": "W314", "from": "PCB_17", "to": "INTLK_66", "points": [[955, 150], [600, 150], [600, 380]], "label": "CH1_COMP", "type": "signal"}, {"id": "W315", "from": "PCB_18", "to": "INTLK_66", "points": [[955, 390], [650, 390]], "label": "CH2_COMP", "type": "signal"}, {"id": "W316", "from": "INTLK_66", "to": "BEAM_TERMINATE", "points": [[480, 415], [430, 415]], "label": "FAULT_TRIGGER", "type": "safety"}, {"id": "W317", "from": "BEAM_TERMINATE", "to": "CABLE_W16", "points": [[250, 415], [205, 415]], "label": "CUTOFF_CMD", "type": "safety"}]}, "gantry_collimator": {"id": "gantry_collimator", "name": "Accionamiento de Gantry y Colimador (Gantry & Collimator Motion)", "short_name": "Gantry y Colimador", "badge": "Servocontrol / 360°", "icon": "🔄", "description": "Lazo cerrado de velocidad y posición: PCB 25, servoamplificador PWM, servomotor M3, taquimétrica, freno electromagnético K5, potenciómetro y encoder óptico con límites de carrera.", "manual_references": ["movement (Pág 35)", "diagrams (Pág 58)", "planned (Pág 42)"], "viewBox": "0 0 1200 680", "nodes": [{"id": "PCB_25", "code": "PCB 25", "name": "Placa Control Movimiento", "type": "pcb", "x": 50, "y": 140, "width": 200, "height": 95, "spec": "Motion DSP Axis Controller & Servo Loop", "manual": "movement", "page": 35, "role": "Generación de perfiles de aceleración y regulación PID"}, {"id": "ITEM_215", "code": "ITEM 215", "name": "Permisivo Movimiento", "type": "signal", "x": 280, "y": 150, "width": 150, "height": 75, "spec": "ITEM 215 / Habilitación de etapa de potencia de motores", "manual": "movement", "page": 38, "role": "Señal lógica de autorización de rotación"}, {"id": "SERVO_AMP_G", "code": "SERVO AMP", "name": "Servoamplificador Gantry", "type": "source", "x": 470, "y": 140, "width": 180, "height": 90, "spec": "Puente H PWM 90V DC / Corriente pico 25A", "manual": "movement", "page": 42, "role": "Etapa de potencia para accionamiento del motor de gantry"}, {"id": "MOTOR_M3", "code": "MOTOR M3", "name": "Servomotor Gantry M3", "type": "load", "x": 700, "y": 135, "width": 170, "height": 95, "spec": "Motor DC de Imán Permanente 1.5 kW con reductora epicicloidal", "manual": "movement", "page": 46, "role": "Tracción directa del anillo de rotación de gantry"}, {"id": "TACHO_TG1", "code": "DINAMO TG1", "name": "Taquimétrica Gantry", "type": "sensor", "x": 910, "y": 145, "width": 140, "height": 75, "spec": "Generador taquimétrico analógico 20V / 1000 RPM", "manual": "movement", "page": 48, "role": "Lazo interno analógico de realimentación de velocidad"}, {"id": "TP_SPEED", "code": "TP_SPEED", "name": "Punto de Prueba TP_SPEED", "type": "test_point", "x": 1080, "y": 160, "width": 75, "height": 42, "spec": "±10.0V DC proporcional a RPM de gantry", "manual": "movement", "page": 50, "role": "Monitoreo del lazo de velocidad taquimétrica"}, {"id": "BRAKE_K5", "code": "BRAKE K5", "name": "Relé Freno Gantry K5", "type": "relay", "x": 700, "y": 280, "width": 170, "height": 75, "spec": "Bobina 24V DC / Freno por pérdida de corriente (Seguridad)", "manual": "movement", "page": 52, "role": "Desbloqueo de frenos mecánicos durante el movimiento"}, {"id": "POT_GANTRY", "code": "POT GANTRY", "name": "Potenciómetro Ángulo", "type": "sensor", "x": 910, "y": 280, "width": 160, "height": 75, "spec": "Potenciómetro multivuelta 10 kOhm bobinado clase 0.1%", "manual": "movement", "page": 54, "role": "Lectura analógica de posición angular para visualización"}, {"id": "ENCODER_G", "code": "ENCODER G", "name": "Encoder Absoluto Gantry", "type": "sensor", "x": 910, "y": 400, "width": 160, "height": 80, "spec": "Encoder óptico absoluto 16-bit comunicación serie SSI", "manual": "movement", "page": 56, "role": "Medida digital precisa para control de ángulo por ordenador CCP"}, {"id": "TP_POS", "code": "TP_POS", "name": "Punto de Prueba TP_POS", "type": "test_point", "x": 1090, "y": 420, "width": 65, "height": 42, "spec": "0-10V DC correspondiente exactamente a 0° - 360°", "manual": "movement", "page": 57, "role": "Comprobación de linealidad del ángulo de gantry"}, {"id": "LIMIT_CW", "code": "LIMIT CW 185°", "name": "Fin Carrera Horario", "type": "switch", "x": 690, "y": 400, "width": 160, "height": 75, "spec": "Microswitch NC de ruptura positiva a +185°", "manual": "movement", "page": 60, "role": "Detención brusca por límite de giro en sentido horario"}, {"id": "LIMIT_CCW", "code": "LIMIT CCW 185°", "name": "Fin Carrera Antihorario", "type": "switch", "x": 480, "y": 400, "width": 160, "height": 75, "spec": "Microswitch NC de ruptura positiva a -185°", "manual": "movement", "page": 60, "role": "Detención brusca por límite de giro antihorario"}, {"id": "COLL_DRIVE_M4", "code": "MOTOR M4 COLL", "name": "Motor Rotación Colimador", "type": "load", "x": 270, "y": 400, "width": 160, "height": 80, "spec": "Motor DC de imán permanente para cabezal de colimador", "manual": "diagrams", "page": 58, "role": "Rotación de la cabeza del colimador multiláminas (MLC)"}, {"id": "POT_COLL", "code": "POT COLL ROT", "name": "Potenciómetro Colimador", "type": "sensor", "x": 70, "y": 400, "width": 160, "height": 80, "spec": "Potenciómetro de realimentación angular ±185°", "manual": "diagrams", "page": 58, "role": "Medida de posición de rotación de colimador"}, {"id": "CABLE_W30", "code": "CABLE W30", "name": "Potencia Motores W30", "type": "cable", "x": 480, "y": 530, "width": 160, "height": 65, "spec": "Cable 4x2.5mm² blindado para alimentación de inducido", "manual": "movement", "page": 65, "role": "Conducción de corriente PWM hacia motores de gantry"}, {"id": "CABLE_W32", "code": "CABLE W32", "name": "Señales Encoders W32", "type": "cable", "x": 700, "y": 530, "width": 160, "height": 65, "spec": "Cable multiconductor apantallado por pares trenzados", "manual": "movement", "page": 66, "role": "Transmisión inmune al ruido de encoders y finales de carrera"}], "wires": [{"id": "W401", "from": "PCB_25", "to": "ITEM_215", "points": [[250, 185], [280, 185]], "label": "EN_CMD", "type": "signal"}, {"id": "W402", "from": "ITEM_215", "to": "SERVO_AMP_G", "points": [[430, 185], [470, 185]], "label": "PWM_GATE", "type": "signal"}, {"id": "W403", "from": "SERVO_AMP_G", "to": "MOTOR_M3", "points": [[650, 185], [700, 185]], "label": "MOTOR_DRIVE", "type": "power"}, {"id": "W404", "from": "MOTOR_M3", "to": "TACHO_TG1", "points": [[870, 185], [910, 185]], "label": "SHAFT_RPM", "type": "feedback"}, {"id": "W405", "from": "TACHO_TG1", "to": "TP_SPEED", "points": [[1050, 185], [1080, 185]], "label": "SPEED_V", "type": "signal"}, {"id": "W406", "from": "SERVO_AMP_G", "to": "BRAKE_K5", "points": [[560, 230], [560, 315], [700, 315]], "label": "BRAKE_RELEASE", "type": "power"}, {"id": "W407", "from": "MOTOR_M3", "to": "POT_GANTRY", "points": [[840, 230], [840, 315], [910, 315]], "label": "GEAR_LINK", "type": "feedback"}, {"id": "W408", "from": "POT_GANTRY", "to": "TP_POS", "points": [[1070, 315], [1120, 315], [1120, 420]], "label": "ANALOG_POS", "type": "signal"}, {"id": "W409", "from": "MOTOR_M3", "to": "ENCODER_G", "points": [[800, 230], [800, 440], [910, 440]], "label": "ENC_SHAFT", "type": "feedback"}, {"id": "W410", "from": "ENCODER_G", "to": "PCB_25", "points": [[910, 460], [150, 460], [150, 235]], "label": "SSI_DATA", "type": "signal"}, {"id": "W411", "from": "LIMIT_CW", "to": "SERVO_AMP_G", "points": [[690, 437], [630, 437], [630, 230]], "label": "CW_STOP", "type": "safety"}, {"id": "W412", "from": "LIMIT_CCW", "to": "SERVO_AMP_G", "points": [[560, 400], [560, 230]], "label": "CCW_STOP", "type": "safety"}, {"id": "W413", "from": "PCB_25", "to": "COLL_DRIVE_M4", "points": [[150, 235], [150, 370], [350, 370], [350, 400]], "label": "COLL_PWM", "type": "power"}, {"id": "W414", "from": "COLL_DRIVE_M4", "to": "POT_COLL", "points": [[270, 440], [230, 440]], "label": "COLL_POS", "type": "feedback"}, {"id": "W415", "from": "SERVO_AMP_G", "to": "CABLE_W30", "points": [[500, 230], [500, 530]], "label": "W30_LINE", "type": "cable"}, {"id": "W416", "from": "ENCODER_G", "to": "CABLE_W32", "points": [[960, 480], [960, 560], [860, 560]], "label": "W32_LINE", "type": "cable"}]}, "vacuum_gun": {"id": "vacuum_gun", "name": "Control de Vacío y Cañón de Electrones (Vacuum & Gun System)", "short_name": "Vacío y Cañón", "badge": "< 10^-8 Torr / Cañón Triodo", "icon": "🔬", "description": "Ultra-alto vacío y emisión termoiónica: bombas iónicas VacIon de 5kV, monitor de corriente PCB 14, interlock de presión ITEM 112, PCB 12 de cañón, fuente filamento y pulsador de rejilla.", "manual_references": ["vacuum (Pág 12)", "ht_rf (Pág 50)", "diagrams (Pág 34)"], "viewBox": "0 0 1200 680", "nodes": [{"id": "ION_PUMP_1", "code": "ION PUMP 1", "name": "Bomba VacIon Guía RF", "type": "load", "x": 50, "y": 140, "width": 170, "height": 85, "spec": "Bomba iónica VacIon 25 L/s polarizada a 5kV DC", "manual": "vacuum", "page": 12, "role": "Mantenimiento de vacío en la guía de onda aceleradora"}, {"id": "ION_PUMP_2", "code": "ION PUMP 2", "name": "Bomba VacIon Cañón", "type": "load", "x": 260, "y": 140, "width": 170, "height": 85, "spec": "Bomba iónica VacIon 8 L/s polarizada a 5kV DC", "manual": "vacuum", "page": 14, "role": "Evacuación continua de gases residuales en la cámara del cañón"}, {"id": "PCB_14", "code": "PCB 14", "name": "Tarjeta Monitor Vacío", "type": "pcb", "x": 480, "y": 130, "width": 200, "height": 100, "spec": "Medidor de corriente iónica con escala logarítmica (pA a mA)", "manual": "vacuum", "page": 18, "role": "Conversión de corriente de bomba iónica a señal de presión"}, {"id": "TP_VAC", "code": "TP_VAC", "name": "Punto de Prueba TP_VAC", "type": "test_point", "x": 710, "y": 155, "width": 65, "height": 42, "spec": "1V DC por década (ej: 2.0V = 1.0x10^-8 Torr)", "manual": "vacuum", "page": 20, "role": "Monitor analógico directo de presión de vacío de acelerador"}, {"id": "ITEM_112", "code": "ITEM 112", "name": "Alarma Presión Vacío", "type": "interlock", "x": 810, "y": 140, "width": 150, "height": 75, "spec": "ITEM 112 / Disparo de alarma si P > 5.0x10^-7 Torr", "manual": "vacuum", "page": 22, "role": "Corte de protección contra degradación del filamento por gas"}, {"id": "VAC_RELAY_K7", "code": "VAC RELAY K7", "name": "Relé Permisivo Vacío K7", "type": "relay", "x": 1000, "y": 140, "width": 160, "height": 75, "spec": "Relé de enclavamiento físico de habilitación de filamento", "manual": "vacuum", "page": 24, "role": "Inhibe físicamente la fuente de filamento si no hay vacío óptimo"}, {"id": "PCB_12", "code": "PCB 12", "name": "Control Cañón Electrones", "type": "pcb", "x": 50, "y": 350, "width": 210, "height": 100, "spec": "Gun Filament Regulator & Grid Bias Pulse Board", "manual": "ht_rf", "page": 50, "role": "Controlador de corriente termoiónica y disparo de inyección"}, {"id": "GUN_FILAMENT", "code": "FILAMENT SUPPLY", "name": "Fuente Filamento Cañón", "type": "source", "x": 300, "y": 350, "width": 170, "height": 85, "spec": "6.3V AC/DC, 1.8A corriente constante estabilizada", "manual": "ht_rf", "page": 52, "role": "Caldeo del cátodo dispensador a 1050°C"}, {"id": "TP_GUN", "code": "TP_GUN", "name": "Punto de Prueba TP_GUN", "type": "test_point", "x": 500, "y": 375, "width": 65, "height": 42, "spec": "1.8V DC (1V medido = 1.0A de corriente de filamento)", "manual": "ht_rf", "page": 54, "role": "Comprobación de la corriente exacta de caldeo del cátodo"}, {"id": "GRID_PULSER", "code": "GRID PULSER", "name": "Modulador Rejilla Triodo", "type": "source", "x": 600, "y": 350, "width": 160, "height": 85, "spec": "Pulso rápido de inyección de 0V a -150V de corte", "manual": "ht_rf", "page": 56, "role": "Gating de inyección de paquetes de electrones al Linac"}, {"id": "TP7", "code": "TP7", "name": "Punto de Prueba TP7", "type": "test_point", "x": 790, "y": 375, "width": 60, "height": 42, "spec": "Pulso de inyección en rejilla conmutada", "manual": "ht_rf", "page": 57, "role": "Verificación del tiempo de subida de inyección de haz"}, {"id": "CATHODE_GUN", "code": "GUN CATHODE", "name": "Cátodo Cañón Linac", "type": "load", "x": 890, "y": 340, "width": 180, "height": 105, "spec": "Cátodo dispensador de tungsteno/óxido de bario (BaO/W)", "manual": "ht_rf", "page": 60, "role": "Emisión termoiónica del haz primario de electrones (300mA pico)"}, {"id": "ITEM_118", "code": "ITEM 118", "name": "Permisivo Gun Ready", "type": "signal", "x": 1000, "y": 480, "width": 160, "height": 70, "spec": "ITEM 118 / Retardo de caldeo de 3 minutos completado", "manual": "catalogue", "page": 42, "role": "Confirmación de equilibrio térmico del cátodo antes de emitir"}, {"id": "CABLE_W05", "code": "CABLE W05", "name": "Alta Tensión Cañón W05", "type": "cable", "x": 50, "y": 520, "width": 160, "height": 65, "spec": "Mazo con aislamiento de silicona 25kV para cátodo y filamento", "manual": "diagrams", "page": 34, "role": "Línea de alimentación de muy alta tensión para el cañón"}, {"id": "CABLE_W08", "code": "CABLE W08", "name": "Línea VacIon W08", "type": "cable", "x": 260, "y": 520, "width": 160, "height": 65, "spec": "Cable coaxial blindado 5kV para bombas iónicas", "manual": "diagrams", "page": 34, "role": "Conducción de corriente de ionización sin interferencias"}], "wires": [{"id": "W501", "from": "ION_PUMP_1", "to": "PCB_14", "points": [[220, 180], [480, 180]], "label": "PUMP1_pA", "type": "high_voltage"}, {"id": "W502", "from": "ION_PUMP_2", "to": "PCB_14", "points": [[430, 180], [480, 180]], "label": "PUMP2_pA", "type": "high_voltage"}, {"id": "W503", "from": "PCB_14", "to": "TP_VAC", "points": [[680, 180], [710, 180]], "label": "LOG_PRESS", "type": "signal"}, {"id": "W504", "from": "TP_VAC", "to": "ITEM_112", "points": [[775, 180], [810, 180]], "label": "COMP_IN", "type": "signal"}, {"id": "W505", "from": "ITEM_112", "to": "VAC_RELAY_K7", "points": [[960, 180], [1000, 180]], "label": "PERM_EN", "type": "safety"}, {"id": "W506", "from": "VAC_RELAY_K7", "to": "GUN_FILAMENT", "points": [[1080, 215], [1080, 300], [385, 300], [385, 350]], "label": "INTERLOCK_LOOP", "type": "safety"}, {"id": "W507", "from": "PCB_12", "to": "GUN_FILAMENT", "points": [[260, 392], [300, 392]], "label": "FIL_DRV", "type": "power"}, {"id": "W508", "from": "GUN_FILAMENT", "to": "TP_GUN", "points": [[470, 392], [500, 392]], "label": "IFIL_SENSE", "type": "signal"}, {"id": "W509", "from": "TP_GUN", "to": "GRID_PULSER", "points": [[565, 392], [600, 392]], "label": "GRID_EN", "type": "signal"}, {"id": "W510", "from": "GRID_PULSER", "to": "TP7", "points": [[760, 392], [790, 392]], "label": "PULSE_OUT", "type": "signal"}, {"id": "W511", "from": "TP7", "to": "CATHODE_GUN", "points": [[850, 392], [890, 392]], "label": "BEAM_EMIT", "type": "high_voltage"}, {"id": "W512", "from": "PCB_12", "to": "ITEM_118", "points": [[155, 450], [155, 500], [1000, 500]], "label": "READY_STATUS", "type": "signal"}, {"id": "W513", "from": "PCB_12", "to": "CABLE_W05", "points": [[130, 450], [130, 520]], "label": "W05_HV", "type": "cable"}, {"id": "W514", "from": "ION_PUMP_1", "to": "CABLE_W08", "points": [[135, 225], [135, 270], [340, 270], [340, 520]], "label": "W08_ION", "type": "cable"}]}};
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
                        if (p.length >= 3 && (p === normC || new RegExp("\\b" + p + "\\b", "i").test(String(c)))) return true;
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
