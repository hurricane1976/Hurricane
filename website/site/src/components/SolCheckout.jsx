import { useState } from 'react'
import { Coin } from './Icons.jsx'

// Alongside-Gumroad SOL checkout for one product. Talks directly to
// /api/sol/* (see api/sol_fulfillment.py + api/server.py). Three states:
// closed -> order form -> awaiting payment/verify. The download link itself
// is only ever emailed (never returned by the API), matching the backend's
// single-use-token design -- this widget never sees or stores the token.
export default function SolCheckout({ productId, title }) {
  const [open, setOpen] = useState(false)
  const [email, setEmail] = useState('')
  const [order, setOrder] = useState(null)
  const [signature, setSignature] = useState('')
  const [status, setStatus] = useState(null) // {kind: 'error'|'info'|'ok', text}
  const [busy, setBusy] = useState(false)

  async function createOrder(e) {
    e.preventDefault()
    setBusy(true); setStatus(null)
    try {
      const res = await fetch('/api/sol/orders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ product: productId, email }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error || 'could not create order')
      setOrder(data)
      setStatus({ kind: 'info', text: `Send exactly ${data.amount_sol} SOL using the link below, then paste the transaction signature to verify.` })
    } catch (err) {
      setStatus({ kind: 'error', text: err.message })
    } finally {
      setBusy(false)
    }
  }

  async function verify(e) {
    e.preventDefault()
    setBusy(true); setStatus(null)
    try {
      const res = await fetch(`/api/sol/orders/${order.order_id}/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ signature }),
      })
      const data = await res.json()
      if (data.status === 'fulfilled' || data.status === 'paid_pending_email') {
        setStatus({ kind: 'ok', text: 'Payment verified — check your email for the one-time download link.' })
      } else {
        setStatus({ kind: 'error', text: data.detail || 'Payment could not be verified yet.' })
      }
    } catch (err) {
      setStatus({ kind: 'error', text: err.message })
    } finally {
      setBusy(false)
    }
  }

  if (!open) {
    return (
      <button type="button" className="btn btn-sol-toggle" onClick={() => setOpen(true)}>
        <Coin />Or pay with SOL
      </button>
    )
  }

  return (
    <div className="sol-checkout">
      {!order ? (
        <form onSubmit={createOrder}>
          <label className="sol-label" htmlFor={`sol-email-${productId}`}>Email (for the download link)</label>
          <input
            id={`sol-email-${productId}`}
            type="email" required value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
          />
          <button type="submit" className="btn btn-buy" disabled={busy}>
            <Coin />{busy ? 'Creating order…' : `Create SOL order — ${title}`}
          </button>
        </form>
      ) : (
        <form onSubmit={verify}>
          <p className="sol-uri">
            <a href={order.payment_uri}>{order.amount_sol} SOL to {order.recipient}</a>
          </p>
          <label className="sol-label" htmlFor={`sol-sig-${productId}`}>Transaction signature</label>
          <input
            id={`sol-sig-${productId}`}
            type="text" required value={signature}
            onChange={(e) => setSignature(e.target.value)}
            placeholder="paste the signature after sending"
          />
          <button type="submit" className="btn btn-buy" disabled={busy}>
            <Coin />{busy ? 'Verifying…' : 'Verify payment'}
          </button>
        </form>
      )}
      {status && <p className={`sol-status sol-status-${status.kind}`}>{status.text}</p>}
    </div>
  )
}
