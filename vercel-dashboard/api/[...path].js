const BACKEND_BASE_URL =
  process.env.KIBOT_BACKEND_BASE_URL ||
  process.env.BACKEND_BASE_URL ||
  "https://mom-sorry-disclaimers-fool.trycloudflare.com";

function joinUrl(base, pathname, search) {
  const cleanBase = String(base || "").replace(/\/+$/, "");
  const cleanPath = String(pathname || "").replace(/^\/+/, "");
  const query = search ? `?${search.replace(/^\?/, "")}` : "";
  return `${cleanBase}/${cleanPath}${query}`;
}

async function readBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  return Buffer.concat(chunks);
}

export default async function handler(req, res) {
  const path = Array.isArray(req.query.path) ? req.query.path.join("/") : String(req.query.path || "");
  const targetUrl = joinUrl(BACKEND_BASE_URL, path, req.url.split("?")[1] || "");

  const headers = { ...req.headers };
  delete headers.host;
  delete headers.connection;
  delete headers["content-length"];

  try {
    const init = {
      method: req.method,
      headers,
      redirect: "manual",
    };
    if (!["GET", "HEAD"].includes(req.method || "")) {
      init.body = await readBody(req);
    }

    const upstream = await fetch(targetUrl, init);

    res.status(upstream.status);
    upstream.headers.forEach((value, key) => {
      if (["content-encoding", "transfer-encoding", "connection"].includes(key.toLowerCase())) return;
      res.setHeader(key, value);
    });

    if (req.method === "HEAD") {
      return res.end();
    }

    const arrayBuffer = await upstream.arrayBuffer();
    return res.end(Buffer.from(arrayBuffer));
  } catch (error) {
    res.status(502).json({
      ok: false,
      error: "proxy_failed",
      message: error instanceof Error ? error.message : String(error),
      backend: BACKEND_BASE_URL,
      path,
    });
  }
}
