/*
 * Navegador real (Playwright + Chromium): DOM, Service Worker y flujo de
 * simulación. Ejecutar con SOLVI_BASE_URL y SOLVI_PLAYWRIGHT_ROOT.
 */
import assert from "node:assert/strict";
import path from "node:path";
import { pathToFileURL } from "node:url";

const baseURL = process.env.SOLVI_BASE_URL || "http://127.0.0.1:5000";
const playwrightRoot = process.env.SOLVI_PLAYWRIGHT_ROOT || path.join(process.cwd(), "node_modules", "playwright");
const { chromium } = await import(pathToFileURL(path.join(playwrightRoot, "index.mjs")).href);

async function poll(predicate, timeoutMs = 5000, intervalMs = 100) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
        if (await predicate()) return;
        await new Promise(resolve => setTimeout(resolve, intervalMs));
    }
    throw new Error("Condición no alcanzada dentro del timeout del navegador");
}

// El runtime corporativo trae Chromium completo, pero no siempre el paquete
// separado headless-shell; fijar la ruta hace la prueba reproducible localmente.
const browser = await chromium.launch({ headless: true, executablePath: chromium.executablePath() });
const context = await browser.newContext({ serviceWorkers: "allow" });
const page = await context.newPage();
const failures = [];
page.on("pageerror", error => failures.push(error.message));

try {
    await page.goto(baseURL, { waitUntil: "networkidle", timeout: 30000 });
    await page.waitForSelector("#q", { state: "visible" });
    assert.match(await page.title(), /SOLVI/i);
    assert.equal(await page.locator("#navM").getAttribute("aria-label"), "Abrir multímetro");
    const welcome = page.locator("#modalBienvenida");
    if (await welcome.count()) await welcome.getByRole("button", { name: "OK" }).click();

    // DOM/navigation real: abrir la pantalla y cambiar al banco simulado.
    await page.locator("#navM").click();
    await page.locator("#dmmTab_simulation").click();
    await poll(async () => await page.locator("#dmmPanel_simulation").isVisible());
    await page.getByRole("button", { name: /Normal \(Dentro de rango\)/ }).click();
    await poll(async () => await page.locator("#dmmResultBox").isVisible());
    assert.notEqual((await page.locator("#dmmResultBox").innerText()).trim(), "");

    // Service Worker real: se registra, toma control y mantiene el cache versionado.
    await page.evaluate(() => navigator.serviceWorker.ready);
    assert.equal(await page.evaluate(() => Boolean(navigator.serviceWorker.controller)), true);
    const cacheInfo = await page.evaluate(async () => {
        const names = await caches.keys();
        const solvi = names.filter(name => /^solvi-v\d+$/.test(name));
        const keys = solvi.length ? await (await caches.open(solvi.at(-1))).keys() : [];
        return { names, urls: keys.map(request => request.url) };
    });
    assert.ok(cacheInfo.names.some(name => /^solvi-v\d+$/.test(name)), "cache SOLVI ausente");
    assert.ok(cacheInfo.urls.some(url => url.endsWith("/static/app.js")), "app.js no está en cache");
    assert.ok(!cacheInfo.urls.some(url => /data\/search\/chunk-/.test(url)), "no debe precachear todos los chunks");

    // El shell se puede reabrir offline después de haber sido cacheado.
    await context.setOffline(true);
    await page.reload({ waitUntil: "domcontentloaded", timeout: 15000 });
    await page.waitForSelector("#q", { state: "visible" });
    assert.ok((await page.locator("#q").getAttribute("aria-label")));
    await context.setOffline(false);

    if (failures.length) throw new Error(`Errores de página: ${failures.join(" | ")}`);
    console.log(JSON.stringify({ ok: true, baseURL, serviceWorker: true, simulation: true, dom: true }));
} finally {
    await browser.close();
}
