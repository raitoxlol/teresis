import {useState, type FormEvent} from 'react';

const ENDPOINT = (import.meta.env.VITE_WAITLIST_ENDPOINT as string | undefined) || '/teresis/api/waitlist';

type State = 'idle' | 'sending' | 'done' | 'error';

export function Waitlist({id, compact = false}: {id: string; compact?: boolean}) {
  const [state, setState] = useState<State>('idle');
  const [message, setMessage] = useState('');

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const email = String(new FormData(event.currentTarget).get('email') ?? '').trim();
    setState('sending');
    try {
      const res = await fetch(ENDPOINT, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({email}),
      });
      if (!res.ok) {
        const data = (await res.json().catch(() => null)) as {error?: string} | null;
        setState('error');
        setMessage(res.status === 400 && data?.error ? data.error : 'That did not go through. Try again in a moment.');
        return;
      }
      setState('done');
      setMessage("You're on the list.");
    } catch {
      setState('error');
      setMessage('That did not go through. Try again in a moment.');
    }
  }

  if (state === 'done') {
    return (
      <p className={`wait-done${compact ? ' compact' : ''}`} role="status">
        {message}
      </p>
    );
  }

  return (
    <form className={`wait${compact ? ' compact' : ''}`} onSubmit={submit}>
      <label className="sr-only" htmlFor={id}>
        Email address
      </label>
      <input id={id} name="email" type="email" required autoComplete="email" placeholder="you@studio.dev" />
      <button type="submit" disabled={state === 'sending'}>
        {state === 'sending' ? 'Joining…' : 'Get updates'}
      </button>
      {state === 'error' && (
        <p className="wait-msg" role="alert">
          {message}
        </p>
      )}
    </form>
  );
}
