const PRODUCT_NAME = 'DeepHarness'
const UPSTREAM_PRODUCT_NAME = 'DeepSeek Harness'
const WORDMARK_MARKER = 'data-deepharness-wordmark'
const FISH_MARKER = 'data-deepharness-mark'

const BRAND_STYLE = `
[${WORDMARK_MARKER}] > svg { display: none !important; }
[${WORDMARK_MARKER}]::after {
  content: "${PRODUCT_NAME}";
  color: currentColor;
  font: 700 19px/24px ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  letter-spacing: -0.35px;
  white-space: nowrap;
}
[${FISH_MARKER}] > svg[viewBox="0 0 23.16 17.04"] { display: none !important; }
[${FISH_MARKER}]::after {
  content: "DH";
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 24px;
  border: 1px solid currentColor;
  border-radius: 7px;
  color: currentColor;
  font: 700 11px/1 ui-sans-serif, system-ui, sans-serif;
  letter-spacing: -0.2px;
  box-sizing: border-box;
}
`

const ICON_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="16" fill="#4f6ee8"/><text x="32" y="40" text-anchor="middle" font-family="Arial,sans-serif" font-size="25" font-weight="700" fill="white">DH</text></svg>'
const ICON_DATA_URL = `data:image/svg+xml,${encodeURIComponent(ICON_SVG)}`
const MANIFEST_DATA_URL = `data:application/manifest+json,${encodeURIComponent(JSON.stringify({
  id: '/', name: PRODUCT_NAME, short_name: 'DH', start_url: '/', scope: '/', display: 'fullscreen',
  icons: [{ src: ICON_DATA_URL, sizes: 'any', type: 'image/svg+xml', purpose: 'any' }],
}))}`

interface LinkSnapshot {
  element: HTMLLinkElement
  href: string | null
}

function replaceProductName(value: string): string {
  return value.replaceAll(UPSTREAM_PRODUCT_NAME, PRODUCT_NAME)
}

function markBrandNodes(doc: Document): void {
  for (const svg of doc.querySelectorAll('svg')) {
    if (svg.querySelector('#dsh-wordmark-whale-clip') !== null) {
      svg.parentElement?.setAttribute(WORDMARK_MARKER, '')
      continue
    }
    if (svg.getAttribute('viewBox') === '0 0 23.16 17.04') {
      svg.parentElement?.setAttribute(FISH_MARKER, '')
    }
  }
}

/** Install the reversible DOM projection owned by the branding plugin. */
export function installDeepHarnessBranding(doc: Document): () => void {
  const initialTitle = doc.title
  const style = doc.createElement('style')
  style.dataset.deepharnessBrand = 'true'
  style.textContent = BRAND_STYLE
  doc.head.append(style)

  const links: LinkSnapshot[] = []
  for (const element of doc.querySelectorAll<HTMLLinkElement>('link[rel="icon"], link[rel="manifest"]')) {
    links.push({ element, href: element.getAttribute('href') })
    element.href = element.rel === 'manifest' ? MANIFEST_DATA_URL : ICON_DATA_URL
  }

  const project = (): void => {
    const nextTitle = replaceProductName(doc.title)
    if (nextTitle !== doc.title) doc.title = nextTitle
    markBrandNodes(doc)
  }
  project()

  const observer = new MutationObserver(project)
  observer.observe(doc.documentElement, { childList: true, subtree: true, characterData: true })

  return () => {
    observer.disconnect()
    style.remove()
    doc.title = initialTitle
    for (const { element, href } of links) {
      if (href === null) element.removeAttribute('href')
      else element.setAttribute('href', href)
    }
    for (const element of doc.querySelectorAll(`[${WORDMARK_MARKER}], [${FISH_MARKER}]`)) {
      element.removeAttribute(WORDMARK_MARKER)
      element.removeAttribute(FISH_MARKER)
    }
  }
}
