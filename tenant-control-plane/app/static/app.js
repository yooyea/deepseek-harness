const $ = (selector) => document.querySelector(selector)
const toast = (message) => {
  const element = $('#toast')
  element.textContent = message
  element.classList.add('visible')
  setTimeout(() => element.classList.remove('visible'), 3200)
}

const api = async (path, options = {}) => {
  const headers = { ...(options.headers || {}) }
  if (options.body) headers['Content-Type'] = 'application/json'
  if (options.method && options.method !== 'GET') headers['X-Control-Plane-CSRF'] = '1'
  const response = await fetch(path, { ...options, headers })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.detail || `请求失败 (${response.status})`)
  return data
}

const metric = (label, value, detail) => `
  <article class="metric"><span>${label}</span><strong>${value}</strong><p>${detail}</p></article>`

const statusName = { running: '运行中', stopped: '已停止', creating: '创建中', error: '异常' }

const render = (data) => {
  const host = data.host
  $('#metrics').innerHTML = [
    metric('CPU 使用率', `${host.cpu_percent}%`, `${host.cpu_count} 核 · Load ${host.load_1m.toFixed(2)}`),
    metric('可用内存', `${host.memory_available_mb} MB`, `总计 ${host.memory_total_mb} MB`),
    metric('剩余磁盘', `${host.disk_free_gb} GB`, `剩余 ${host.disk_free_percent}%`),
    metric('租户实例', data.tenants.length, `默认 ${data.defaults.cpu_limit} CPU / ${data.defaults.memory_mb} MB`),
  ].join('')

  const badge = $('#capacity-badge')
  badge.className = `badge ${data.capacity.allowed && data.docker_available ? 'good' : 'bad'}`
  badge.textContent = !data.docker_available
    ? 'Docker 不可用'
    : data.capacity.allowed ? '当前允许创建租户' : data.capacity.reasons.join('；')

  $('#tenant-summary').textContent = `${data.tenants.filter((item) => item.runtime.running).length} 个运行中，共 ${data.tenants.length} 个实例`
  $('#tenants').innerHTML = data.tenants.length ? data.tenants.map((tenant) => {
    const runtime = tenant.runtime
    const action = runtime.running ? 'stop' : 'start'
    const actionLabel = runtime.running ? '停止' : '启动'
    return `<tr>
      <td><strong>${escapeHtml(tenant.name)}</strong><small>${escapeHtml(tenant.slug)} · ${escapeHtml(tenant.access_username)}</small></td>
      <td><span class="status ${escapeHtml(tenant.status)}">${statusName[tenant.status] || escapeHtml(tenant.status)}</span><small>${escapeHtml(runtime.health)}</small></td>
      <td><a href="${escapeHtml(tenant.url)}" target="_blank" rel="noopener">${escapeHtml(tenant.url)}</a></td>
      <td>${tenant.cpu_limit} CPU<br><small>${tenant.memory_mb} MB · ${tenant.plugins.length} 个插件</small></td>
      <td>${runtime.cpu_percent}% CPU<br><small>${runtime.memory_mb} MB (${runtime.memory_percent}%)</small></td>
      <td><div class="actions">
        <button class="secondary" data-action="${action}" data-id="${tenant.id}">${actionLabel}</button>
        <button class="secondary" data-action="restart" data-id="${tenant.id}" ${runtime.running ? '' : 'disabled'}>重启</button>
        <button class="secondary" data-action="rebuild" data-id="${tenant.id}">重建</button>
        <button class="secondary" data-action="recover" data-id="${tenant.id}">安全恢复</button>
        <button class="secondary danger" data-action="remove" data-id="${tenant.id}">移除</button>
      </div></td>
    </tr>`
  }).join('') : '<tr><td colspan="6"><p>还没有租户实例</p></td></tr>'

  $('#logs').innerHTML = data.logs.length ? data.logs.map((log) => `<div class="log">
    <span>${new Date(log.created_at).toLocaleString()}</span>
    <strong>${escapeHtml(log.tenant_name || '系统')}</strong>
    <span>${escapeHtml(log.action)} · ${escapeHtml(log.status)}</span>
    <span>${escapeHtml(log.detail || '')}</span>
  </div>`).join('') : '<p>暂无操作记录</p>'
}

const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (character) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
})[character])

const load = async () => {
  try { render(await api('/api/dashboard')) }
  catch (error) { toast(error.message) }
}

$('#create-form').addEventListener('submit', async (event) => {
  event.preventDefault()
  const button = event.submitter
  button.disabled = true
  const values = Object.fromEntries(new FormData(event.currentTarget))
  try {
    const tenant = await api('/api/tenants', { method: 'POST', body: JSON.stringify(values) })
    $('#initial-password').textContent = tenant.initial_password
    $('#tenant-link').href = tenant.url
    $('#secret-dialog').showModal()
    event.currentTarget.reset()
    event.currentTarget.elements.access_username.value = 'admin'
    await load()
  } catch (error) { toast(error.message) }
  finally { button.disabled = false }
})

$('#tenants').addEventListener('click', async (event) => {
  const button = event.target.closest('button[data-action]')
  if (!button) return
  const action = button.dataset.action
  const tenantId = button.dataset.id
  if (action === 'remove' && !confirm('确定移除这个实例吗？PostgreSQL 与 OSS 记录会保留。')) return
  if (action === 'rebuild' && !confirm('确定删除当前容器并从 PostgreSQL 与 OSS 重建吗？')) return
  button.disabled = true
  try {
    if (action === 'remove') await api(`/api/tenants/${tenantId}`, { method: 'DELETE' })
    else await api(`/api/tenants/${tenantId}/actions`, { method: 'POST', body: JSON.stringify({ action }) })
    toast('操作已完成')
    await load()
  } catch (error) { toast(error.message) }
  finally { button.disabled = false }
})

$('#refresh').addEventListener('click', load)
$('#close-dialog').addEventListener('click', () => $('#secret-dialog').close())
$('#copy-password').addEventListener('click', async () => {
  await navigator.clipboard.writeText($('#initial-password').textContent)
  toast('密码已复制')
})

load()
setInterval(load, 15000)
