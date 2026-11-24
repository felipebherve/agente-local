// Service worker mínimo: deixa o painel ser instalado como app no celular.
// Não guarda nada em cache (documentos de clientes não ficam no aparelho); sem rede,
// mostra um aviso curto.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (e) => {
  if (e.request.mode !== "navigate") return;
  e.respondWith(
    fetch(e.request).catch(() => new Response(
      '<meta charset="utf-8"><meta name="viewport" content="width=device-width"><body style="font:16px system-ui;padding:24px;background:#0e0f14;color:#e8eaed">' +
      "<h2>Sem conexão com o PC</h2><p>Confira se o computador está ligado e se o Tailscale está ativo no celular.</p></body>",
      { headers: { "Content-Type": "text/html; charset=utf-8" } }
    ))
  );
});
