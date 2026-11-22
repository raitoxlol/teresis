declare const process: {env: Record<string, string | undefined>};

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function json(body: Record<string, unknown>, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
    },
  });
}

export async function POST(request: Request): Promise<Response> {
  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return json({error: 'Invalid JSON body.'}, 400);
  }

  const raw =
    typeof payload === 'object' && payload !== null && 'email' in payload && typeof (payload as {email?: unknown}).email === 'string'
      ? (payload as {email: string}).email
      : '';
  const email = raw.trim().toLowerCase();

  if (!email || email.length > 320 || /[\r\n]/.test(email) || !EMAIL_RE.test(email)) {
    return json({error: 'Enter a valid email address.'}, 400);
  }

  const apiKey = process.env.RESEND_API_KEY;
  if (!apiKey) {
    return json({error: 'Waitlist is not configured yet.'}, 503);
  }

  const segmentId = process.env.RESEND_WAITLIST_SEGMENT_ID;
  const body: Record<string, unknown> = {email, unsubscribed: false};
  if (segmentId) body.segments = [{id: segmentId}];

  let upstream: Response;
  try {
    upstream = await fetch('https://api.resend.com/contacts', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });
  } catch {
    return json({error: 'Could not reach the waitlist service.'}, 502);
  }

  if (!upstream.ok) {
    return json({error: 'Could not save your email right now.'}, 502);
  }

  const data = (await upstream.json().catch(() => ({}))) as {id?: string};
  return json({ok: true, id: data.id ?? null}, 201);
}
