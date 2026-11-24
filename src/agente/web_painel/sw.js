// Service worker mínimo: deixa o painel ser instalado como app no celular.
// Não guarda nada em cache (documentos de clientes não ficam no aparelho). Sem conexão
// com o PC (quase sempre o Tailscale desligado no celular), mostra o pedido para ligar.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

const PAGINA_SEM_PC = `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Agente Local</title>
<style>
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0e0f14;color:#e8eaed;
font:16px/1.5 system-ui,-apple-system,Roboto,sans-serif;padding:16px;box-sizing:border-box}
main{width:min(380px,100%);text-align:center}h1{font-size:21px;margin:12px 0 6px}p{color:#a3abb7;margin:0 0 16px}
a,button{display:block;width:100%;box-sizing:border-box;padding:14px;border-radius:12px;border:0;margin-top:10px;
font:600 17px system-ui,sans-serif;text-decoration:none;cursor:pointer}
.ligar{background:linear-gradient(135deg,#8b5cf6,#22c55e);color:#fff}.de-novo{background:#1d2127;color:#e8eaed}
</style></head><body><main>
<h1>Ligue o Tailscale</h1>
<p>O app conversa com o seu PC pelo Tailscale. Ligue o Tailscale no celular (e confira se o PC está ligado) e toque em Tentar de novo.</p>
<a class="ligar" id="abrir" href="intent://#Intent;package=com.tailscale.ipn;end">Abrir o Tailscale</a>
<button class="de-novo" onclick="location.reload()">Tentar de novo</button>
</main><script>
// iPhone não abre outro app por link: lá o botão só lembra onde ligar
if (/iPhone|iPad|iPod/.test(navigator.userAgent)) {
  const a = document.getElementById("abrir");
  a.removeAttribute("href");
  a.textContent = "Abra o app Tailscale e ligue a chave";
}
</script></body></html>`;

self.addEventListener("fetch", (e) => {
  if (e.request.mode !== "navigate") return;
  e.respondWith(
    fetch(e.request).catch(() => new Response(PAGINA_SEM_PC, {
      headers: { "Content-Type": "text/html; charset=utf-8" },
    }))
  );
});
