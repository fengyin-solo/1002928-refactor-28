/** 统一请求封装：拼后端地址、抛网络错误、给页脚留一句可读的说明。 */
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

/** 可重试的瞬时错误：网络没送达、对端 5xx、429 限流；4xx 是参数问题，不重试。 */
function isRetryable(response: Response | null, error: unknown): boolean {
  if (response) {
    return response.status === 429 || response.status >= 500
  }
  // fetch 只有网络层失败才会 reject，重试有意义。
  return error !== undefined
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

export function request(path: string, init?: RequestInit): Promise<Response> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`
  return fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  }).catch((error: unknown) => {
    const detail = error instanceof Error ? error.message : '请求未送达'
    throw new Error(`接口请求失败：${detail}`)
  })
}

/**
 * 带重试的取数：默认对网络错误 / 5xx / 429 重试 2 次，指数退避。
 * 4xx（除 429）直接抛出，交由页面提示，不做无意义的重试。
 */
export async function fetchJson<T>(
  path: string,
  init?: RequestInit,
  retries = 2,
): Promise<T> {
  let lastError = new Error('取数失败，请稍后重试')
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      const response = await request(path, init)
      if (response.ok) {
        return (await response.json()) as T
      }
      lastError = new Error(`接口返回 ${response.status}，数据未更新`)
      if (!isRetryable(response, undefined) || attempt === retries) {
        throw lastError
      }
    } catch (error) {
      // request 内部已把网络错误转成可读 Error；最后一次仍失败则抛出。
      if (attempt === retries) {
        throw error instanceof Error ? error : lastError
      }
      lastError = error instanceof Error ? error : lastError
    }
    await delay(300 * 2 ** attempt)
  }
  throw lastError
}

export async function postJson<T>(path: string, body: unknown, retries = 2): Promise<T> {
  return fetchJson<T>(path, { method: 'POST', body: JSON.stringify(body) }, retries)
}
