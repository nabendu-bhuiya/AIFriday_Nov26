let token = sessionStorage.getItem('tl_token') || ''

export const setToken = (t) => { token = t || ''; t ? sessionStorage.setItem('tl_token', t) : sessionStorage.removeItem('tl_token') }
export const hasToken = () => !!token

export async function api(path, { method = 'GET', body, form } = {}) {
  const headers = token ? { Authorization: `Bearer ${token}` } : {}
  let payload
  if (form) payload = form
  else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body) }
  const res = await fetch(`/api${path}`, { method, headers, body: payload })
  if (res.status === 401 && path !== '/login') { setToken(''); window.dispatchEvent(new Event('tl-logout')) }
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`)
  return data
}

export const qs = (o) => '?' + new URLSearchParams(Object.entries(o).filter(([, v]) => v)).toString()
