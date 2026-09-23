/* Flujo funcional real: DOM, Service Worker, modo offline y módulos vigentes. */
import assert from "node:assert/strict";
import path from "node:path";
import { pathToFileURL } from "node:url";

const baseURL = process.env.SOLVI_BASE_URL || "http://127.0.0.1:5000";
const playwrightRoot = process.env.SOLVI_PLAYWRIGHT_ROOT || path.join(process.cwd(), "node_modules", "playwright");
const { chromium } = await import(pathToFileURL(path.join(playwrightRoot, "index.mjs")).href);

async function poll(predicate, timeoutMs = 10000, intervalMs = 100) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
        if (await predicate()) return;
        await new Promise(resolve => setTimeout(resolve, intervalMs));
    }
    throw new Error("Condición no alcanzada dentro del timeout del navegador");
}

const browser = await chromium.launch({ headless: true, executablePath: chromium.executablePath() });
const context = await browser.newContext({ serviceWorkers: "allow" });
const page = await context.newPage();
const failures = [];
page.on("pageerror", error => failures.push(error.message));

try {
    await page.goto(baseURL, { waitUntil: "networkidle", timeout: 30000 });
    await page.waitForSelector("#q", { state: "visible" });
    assert.match(await page.title(), /SOLVI/i);
    assert.equal(await page.locator("#navC").count(), 0, "Esquemas aún se expone en la navegación");
    assert.equal(await page.locator("#navM").count(), 0, "Multímetro aún se expone en la navegación");
    assert.equal(await page.locator("#navR").count(), 1, "Informes debe estar disponible");

    const welcome = page.locator("#modalBienvenida");
    if (await welcome.count()) {
        await welcome.getByRole("button", { name: /ok|entendido|continuar/i }).click();
        await welcome.waitFor({ state: "detached" }).catch(() => {});
    }

    // Buscar: escribir no consulta; Enter inicia una búsqueda efectiva.
    let searchRequests = 0;
    const countSearchRequest = request => {
        if (new URL(request.url()).pathname === "/search") searchRequests += 1;
    };
    page.on("request", countSearchRequest);
    await page.locator("#q").fill("ITEM 409");
    await page.waitForTimeout(350);
    assert.equal(searchRequests, 0, "la búsqueda se disparó mientras el usuario escribía");
    await page.locator("#q").press("Enter");
    await poll(async () => {
        const metaVisible = await page.locator("#metaBar").evaluate(el => getComputedStyle(el).display !== "none").catch(() => false);
        const cardCount = await page.locator("#resultsList .result-card").count().catch(() => 0);
        return searchRequests >= 1 && metaVisible && cardCount > 0;
    }, 15000);
    page.off("request", countSearchRequest);
    assert.ok(searchRequests >= 1, "la búsqueda no generó peticiones al servidor");
    assert.notEqual(await page.locator("#metaBar").evaluate(el => getComputedStyle(el).display), "none", "la búsqueda no actualizó su estado visible");
    assert.ok((await page.locator("#resultsList .result-card").count()) > 0, "la búsqueda no renderizó resultados");

    // Diagnóstico documental y causal: ambos flujos dan una salida visible.
    await page.locator("#navD").click();
    await page.locator(".symptom-input").first().fill("Interlock 283");
    await page.locator("#btnDiagnose").click();
    await poll(async () => await page.locator("#diagResults .diagnostic-card, #diagEmpty").count() > 0, 15000);
    assert.ok((await page.locator("#diagResults, #diagEmpty").allInnerTexts()).join(" ").length > 0, "el diagnóstico documental no produjo salida");
    await page.locator("#btnDiagnoseAi").click();
    await poll(async () => {
        const loading = await page.locator("#diagResults .diag-ai-loading").count();
        const busy = await page.locator("#btnDiagnoseAi").isDisabled();
        const text = await page.locator("#diagResults").innerText().then(t => t.trim()).catch(() => "");
        return loading === 0 && !busy && text.length > 0;
    }, 25000);
    assert.doesNotMatch(await page.locator("#diagResults").innerText(), /Error al procesar el diagnóstico causal: 503/i, "se filtró un error remoto crudo al usuario");

    // Registros: análisis local de texto y resultado renderizado.
    await page.locator("#navL").click();
    await page.locator("#logPasteArea").fill("2026-09-15 10:55:58 ERROR ITEM 112 failed\n2026-09-15 10:55:59 FATAL INTERLOCK 283 tripped cascade");
    await page.getByRole("button", { name: "Analizar Texto" }).click();
    await poll(async () => await page.locator("#logResults").innerText().then(text => text.trim().length > 0));
    assert.match(await page.locator("#logResults").innerText(), /ITEM 112|INTERLOCK 283/i);

    // Informes: campos editables, adjuntos y tabla dinámica de repuestos.
    await page.locator("#navR").click();
    await page.locator("#reportClient").fill("Hospital de prueba");
    await page.locator("#reportIncident").fill("Interlock 283 durante la preparación.");
    assert.equal(await page.locator("#reportImages").getAttribute("multiple"), "");
    const partsBefore = await page.locator("#reportParts input[aria-label='P/N']").count();
    await page.getByRole("button", { name: "+ Repuesto" }).click();
    assert.equal(await page.locator("#reportParts input[aria-label='P/N']").count(), partsBefore + 1, "no se agregó un repuesto editable");

    // Las rutas retiradas no pueden servir módulos obsoletos.
    for (const legacyPath of ["/diagnose/graph", "/circuits/subsystems", "/multimeter/test-points"]) {
        const response = await page.request.get(baseURL + legacyPath);
        assert.equal(response.status(), 404, `${legacyPath} debe responder 404`);
    }

    // Service Worker real y shell disponible sin red tras precache.
    await page.evaluate(() => navigator.serviceWorker.ready);
    await poll(async () => await page.evaluate(() => Boolean(navigator.serviceWorker.controller)));
    const cacheInfo = await page.evaluate(async () => {
        const names = await caches.keys();
        const solvi = names.filter(name => /^solvi-v\d+$/.test(name));
        const keys = solvi.length ? await (await caches.open(solvi.at(-1))).keys() : [];
        return { names: solvi, urls: keys.map(request => request.url) };
    });
    assert.ok(cacheInfo.names.length > 0, "cache SOLVI ausente");
    assert.ok(cacheInfo.urls.some(url => url.endsWith("/static/app.js")), "app.js no está en caché");
    assert.ok(cacheInfo.urls.some(url => url.endsWith("/data/search/catalog.json")), "catálogo documental no está en caché");
    assert.ok(!cacheInfo.urls.some(url => /circuit-visualizer|linac_graph|verified_signal_paths|verified_measurement_catalog|multimeter/i.test(url)), "el caché conserva un módulo retirado");

    await context.setOffline(true);
    await page.reload({ waitUntil: "domcontentloaded", timeout: 15000 });
    await page.waitForSelector("#q", { state: "visible" });
    assert.equal(await page.locator("#navR").count(), 1, "el shell no se restauró en modo offline");
    await context.setOffline(false);

    if (failures.length) throw new Error(`Errores de página: ${failures.join(" | ")}`);
    console.log(JSON.stringify({ ok: true, baseURL, search: true, diagnosis: true, logs: true, reports: true, serviceWorker: true, offline: true }));
} finally {
    await browser.close();
}
