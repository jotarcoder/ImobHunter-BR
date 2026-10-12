const UPSTREAM = "https://imobhunter-license.imobhunterbr.workers.dev/api/license/activate";

export async function onRequest({ request }) {
  if (request.method !== "POST") {
    return Response.json(
      { ok: false, authorized: false, code: "METHOD_NOT_ALLOWED", error: "Use POST para ativar a licença." },
      { status: 405, headers: { "Allow": "POST", "Cache-Control": "no-store" } }
    );
  }

  const contentType = request.headers.get("Content-Type") || "";
  if (!contentType.toLowerCase().includes("application/json")) {
    return Response.json(
      { ok: false, authorized: false, code: "INVALID_CONTENT_TYPE", error: "A ativação exige application/json." },
      { status: 415, headers: { "Cache-Control": "no-store" } }
    );
  }

  let payload;
  try {
    payload = await request.json();
  } catch {
    return Response.json(
      { ok: false, authorized: false, code: "INVALID_JSON", error: "O pedido de ativação contém JSON inválido." },
      { status: 400, headers: { "Cache-Control": "no-store" } }
    );
  }

  try {
    const upstream = await fetch(UPSTREAM, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json"
      },
      body: JSON.stringify(payload),
      redirect: "manual"
    });
    const body = await upstream.arrayBuffer();
    const headers = new Headers({
      "Content-Type": upstream.headers.get("Content-Type") || "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      "X-ImobHunter-Activation-Proxy": "pages"
    });
    const ray = upstream.headers.get("CF-Ray");
    if (ray) headers.set("X-Upstream-CF-Ray", ray);
    return new Response(body, { status: upstream.status, headers });
  } catch {
    return Response.json(
      { ok: false, authorized: false, code: "LICENSE_UPSTREAM_UNAVAILABLE", error: "Não foi possível alcançar o serviço de licenças. Tente novamente em instantes." },
      { status: 502, headers: { "Cache-Control": "no-store" } }
    );
  }
}
