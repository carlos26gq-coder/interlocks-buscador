console.log("✅ app.js cargado correctamente");

/* =============================
   REFERENCIAS DOM REALES
============================= */

const inputQ = document.getElementById("q");
const inputManual = document.getElementById("manual");
const res = document.getElementById("res");
const btnBuscar = document.getElementById("btnBuscar");

/* =============================
   DATA OFFLINE
============================= */

let manualsData = null;

/* =============================
   GARANTIZAR INTERACCIÓN
============================= */

window.addEventListener("load", () => {

    if (inputQ) inputQ.disabled = false;
    if (inputManual) inputManual.disabled = false;

    // Android fix: forzar foco
    setTimeout(() => {
        inputQ?.focus();
    }, 300);

});

/* =============================
   EVENTOS
============================= */

btnBuscar?.addEventListener("click", iniciarBusqueda);

[inputQ, inputManual].forEach(input => {
    input?.addEventListener("keydown", e => {
        if (e.key === "Enter") {
            e.preventDefault();
            iniciarBusqueda();
        }
    });
});

/* =============================
   CARGAR MANUALES OFFLINE
============================= */

async function cargarManuales() {

    if (manualsData) return manualsData;

    const r = await fetch("/data/all_manuals.json");
    manualsData = await r.json();

    console.log("📚 Base offline cargada:", manualsData.length);

    return manualsData;
}

/* =============================
   CONTROL PRINCIPAL
============================= */

async function iniciarBusqueda() {

    const q = inputQ.value.trim().toLowerCase();
    const m = inputManual.value.trim().toLowerCase();

    if (!q) {
        res.textContent = "⚠️ Ingresa una palabra para buscar.";
        return;
    }

    res.textContent = "🔎 Buscando...";

    try {

        const data = await cargarManuales();

        const results = [];

        data.forEach(page => {

            if (m && page.manual.toLowerCase() !== m) return;

            const textLower = page.text.toLowerCase();

            if (textLower.includes(q)) {

                const pos = textLower.indexOf(q);

                const start = Math.max(0, pos - 60);
                const end = Math.min(page.text.length, pos + 60);

                const context = page.text
                    .substring(start, end)
                    .replace(/\n/g, " ");

                results.push({
                    manual: page.manual,
                    page: page.page,
                    context: context,
                    action: "Revisar sección completa del manual"
                });

            }

        });

        renderResultados({ results });

    } catch (e) {

        res.textContent = "❌ Error cargando los manuales.";
        console.error(e);

    }

}

/* =============================
   RENDER
============================= */

function renderResultados(d) {

    res.innerHTML = "";

    if (!d.results || d.results.length === 0) {

        res.textContent = "❌ No se encontraron resultados.";
        return;

    }

    d.results.forEach(r => {

        res.innerHTML += `
📘 Manual: ${r.manual}
📄 Página: ${r.page}
🧠 Contexto: ${r.context}
🛠 Acción: ${r.action}

-------------------------
`;

    });

}