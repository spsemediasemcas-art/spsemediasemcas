const SUPABASE_URL = "https://cqcvbrgrstdrcqhakcvc.supabase.co";
const PUBLISHABLE_KEY = "sb_publishable_fR6nS5GOjrISTwNQjTuhUQ_e9zThR05";

async function request(path, { method = "GET", token, key, body } = {}) {
  const apiKey = key || PUBLISHABLE_KEY;
  const response = await fetch(`${SUPABASE_URL}${path}`, {
    method,
    headers: {
      apikey: apiKey,
      Authorization: `Bearer ${token || apiKey}`,
      "Content-Type": "application/json",
      "User-Agent": "spsemc-vercel-function/1.0",
      Prefer: "return=representation",
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!response.ok) {
    const message = data?.message || data?.msg || data?.error_description || "Falha no Supabase";
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return data;
}

function send(res, status, body) {
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  return res.status(status).json(body);
}

export default async function handler(req, res) {
  if (req.method === "OPTIONS") {
    res.setHeader("Cache-Control", "no-store");
    return res.status(204).end();
  }
  if (req.method !== "POST") return send(res, 405, { message: "Método não permitido" });

  const secret = process.env.SUPABASE_SECRET_KEY;
  if (!secret) return send(res, 500, { message: "A variável SUPABASE_SECRET_KEY não foi configurada no Vercel." });

  const authorization = req.headers.authorization || "";
  const callerToken = authorization.replace(/^Bearer\s+/i, "").trim();
  if (!callerToken) return send(res, 401, { message: "Sessão não informada." });

  let createdUserId = null;
  try {
    const caller = await request("/auth/v1/user", { token: callerToken });
    const profiles = await request(
      `/rest/v1/user_profiles?select=user_id,role,active&user_id=eq.${encodeURIComponent(caller.id)}`,
      { key: secret }
    );
    const profile = profiles?.[0];
    if (!profile?.active || profile.role !== "superintendente") {
      return send(res, 403, { message: "Somente a Superintendente pode cadastrar usuários." });
    }

    const rawBody = typeof req.body === "string" ? JSON.parse(req.body || "{}") : (req.body || {});
    const email = String(rawBody.email || "").trim().toLowerCase();
    const displayName = String(rawBody.display_name || "").trim();
    const password = String(rawBody.password || "");
    if (rawBody.role && String(rawBody.role) !== "administrativo") {
      return send(res, 400, { message: "Este cadastro só adiciona o perfil Administrativo." });
    }
    if (!displayName || !email || !/^\S+@\S+\.\S+$/.test(email)) {
      return send(res, 400, { message: "Informe o nome e um e-mail válido." });
    }
    if (password.length < 8) {
      return send(res, 400, { message: "A senha inicial deve ter pelo menos 8 caracteres." });
    }

    const created = await request("/auth/v1/admin/users", {
      method: "POST",
      key: secret,
      body: {
        email,
        password,
        email_confirm: true,
        user_metadata: { display_name: displayName },
      },
    });
    createdUserId = created.id;

    await request("/rest/v1/user_profiles?on_conflict=user_id", {
      method: "POST",
      key: secret,
      body: [{
        user_id: created.id,
        email,
        display_name: displayName,
        role: "administrativo",
        active: true,
      }],
    });

    return send(res, 201, {
      user_id: created.id,
      email,
      display_name: displayName,
      role: "administrativo",
    });
  } catch (error) {
    if (createdUserId && secret) {
      try {
        await request(`/auth/v1/admin/users/${createdUserId}`, { method: "DELETE", key: secret });
      } catch {}
    }
    const duplicate = /already|registered|exists/i.test(error.message || "");
    return send(res, duplicate ? 409 : (error.status || 500), {
      message: duplicate ? "Já existe um usuário com esse e-mail." : error.message,
    });
  }
}

