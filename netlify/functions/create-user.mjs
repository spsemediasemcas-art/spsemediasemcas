const SUPABASE_URL = "https://cqcvbrgrstdrcqhakcvc.supabase.co";
const PUBLISHABLE_KEY = "sb_publishable_fR6nS5GOjrISTwNQjTuhUQ_e9zThR05";

const json = (statusCode, body) => ({
  statusCode,
  headers: {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
  },
  body: JSON.stringify(body),
});

async function request(path, { method = "GET", token, key, body } = {}) {
  const apiKey = key || PUBLISHABLE_KEY;
  const response = await fetch(`${SUPABASE_URL}${path}`, {
    method,
    headers: {
      apikey: apiKey,
      Authorization: `Bearer ${token || apiKey}`,
      "Content-Type": "application/json",
      "User-Agent": "semcas-netlify-function/1.0",
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

export async function handler(event) {
  if (event.httpMethod === "OPTIONS") return json(204, {});
  if (event.httpMethod !== "POST") return json(405, { message: "Método não permitido" });

  const secret = process.env.SUPABASE_SECRET_KEY;
  if (!secret) return json(500, { message: "A variável SUPABASE_SECRET_KEY não foi configurada no Netlify." });

  const authorization = event.headers.authorization || event.headers.Authorization || "";
  const callerToken = authorization.replace(/^Bearer\s+/i, "").trim();
  if (!callerToken) return json(401, { message: "Sessão não informada." });

  let createdUserId = null;
  try {
    const caller = await request("/auth/v1/user", { token: callerToken });
    const profiles = await request(
      `/rest/v1/user_profiles?select=user_id,role,active&user_id=eq.${encodeURIComponent(caller.id)}`,
      { key: secret }
    );
    const profile = profiles?.[0];
    if (!profile?.active || profile.role !== "superintendente") {
      return json(403, { message: "Somente a Superintendente pode cadastrar usuários." });
    }

    const payload = JSON.parse(event.body || "{}");
    const email = String(payload.email || "").trim().toLowerCase();
    const displayName = String(payload.display_name || "").trim();
    const password = String(payload.password || "");
    if (!displayName || !email || !/^\S+@\S+\.\S+$/.test(email)) {
      return json(400, { message: "Informe o nome e um e-mail válido." });
    }
    if (password.length < 8) {
      return json(400, { message: "A senha inicial deve ter pelo menos 8 caracteres." });
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

    return json(201, {
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
    return json(duplicate ? 409 : (error.status || 500), {
      message: duplicate ? "Já existe um usuário com esse e-mail." : error.message,
    });
  }
}
