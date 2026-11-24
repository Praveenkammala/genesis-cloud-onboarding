import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity, AlertTriangle, ArrowDownToLine, ArrowRight, BadgeCheck, Boxes,
  Braces, Check, CheckCircle2, ChevronDown, ChevronRight, CircleHelp,
  Cloud, CloudCog, Code2, Database, Download, FileCode2, FileJson2, FileText,
  GitBranch, HardDrive, KeyRound, Layers3, ListFilter, LockKeyhole, Menu,
  Network, PackageCheck, Play, RefreshCw, Search, Server, Shield, ShieldAlert,
  ShieldCheck, Sparkles, Upload, X,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

type Resource = {
  id: string
  type: string
  name: string
  provider: string
  region: string
  resource_group?: string
  tags: Record<string, string>
  properties: Record<string, any>
  module?: string
  terraform_label?: string
  terraform_writer?: { status: 'validated' | 'unverified'; provenance: string; terraform_type: string; validation: string }
}
type ClientWorkspace = { id: string; name: string }

type Edge = { source: string; target: string; relation: string }
type Finding = { id: string; severity: string; title: string; resource: string; detail: string }
type Module = { id: string; label: string; count: number; resource_ids: string[] }
type ToolCall = { tool: string; arguments?: Record<string, unknown>; result: string }
type Investigation = {
  mode: string; summary: string
  workloads: Array<{ name: string; purpose: string; resource_ids: string[] }>
  risks: Array<{ severity: string; title: string; description: string; resource_ids: string[]; finding_ids: string[] }>
  open_questions: string[]; tool_calls: ToolCall[]; model_note?: string
}
type AgentReview = {
  mode: string
  status: string
  model_deployment: string | null
  summary: string
  recommendations: Array<{ priority: string; action: string; evidence: string; resource_ids: string[]; finding_ids: string[] }>
  tool_calls: ToolCall[]
  model_note: string
  citation_checks: { cited_items: number; valid_citations: number; rejected_claims: number }
  human_approval_required: boolean
  write_actions_available: boolean
}
type RunResult = {
  run_id: string
  environment: { name: string; client_id?: string; client_name?: string; provider: string; region: string; resources: Resource[]; relationships: Edge[] }
  summary: { resources: number; relationships: number; modules: number; terraform_resources: number; coverage_before_writer: number; coverage: number; findings: number; critical_findings: number; skipped: number; analysis_seconds: number }
  modules: Module[]
  nodes: Resource[]
  edges: Edge[]
  findings: Finding[]
  skipped: Array<{ id: string; name: string; type: string; reason: string }>
  investigation: Investigation
  terraform_drafts: Array<{ resource_id: string; name: string; source_type: string; terraform_type: string; status: 'validated' | 'unverified'; provenance: string; attempts: number; validation: string; errors: string[]; hcl: string }>
  agent_review: AgentReview
  logs: Array<{ agent: string; status: string; message: string }>
  files: Record<string, string>
  approval: { approved: boolean; approved_at: string | null }
}

type CopilotCitation = { evidence_id: string; kind: string; ref: string; label: string; excerpt: string }
type CopilotMessage = { role: 'user' | 'assistant'; content: string; citations?: CopilotCitation[]; tool_calls?: ToolCall[]; mode?: string; notice?: string }
type ModelCheck = { status: string; message: string; deployment?: string | null }
type View = 'Overview' | 'Inventory' | 'Copilot' | 'Dependency graph' | 'IaC package' | 'Guardrails'

const navigation: Array<{ label: View; icon: LucideIcon; hint: string }> = [
  { label: 'Overview', icon: Activity, hint: 'Run status and summary' },
  { label: 'Inventory', icon: Boxes, hint: 'Imported cloud resources' },
  { label: 'Copilot', icon: Sparkles, hint: 'Ask questions about this estate' },
  { label: 'Dependency graph', icon: Network, hint: 'Resource relationships' },
  { label: 'IaC package', icon: FileCode2, hint: 'Generated Terraform files' },
  { label: 'Guardrails', icon: ShieldCheck, hint: 'Policy and review findings' },
]

const moduleColor: Record<string, string> = {
  network: '#77b7c8', application: '#8a8bf3', data: '#72b99b', identity: '#e3aa72', supporting: '#8d9bad',
}

function displayType(type: string) {
  if (type.toLowerCase().startsWith('microsoft.')) {
    const typeParts = type.split('/')
    const resourceName = typeParts[typeParts.length - 1] ?? type
    return resourceName.replace(/([a-z0-9])([A-Z])/g, '$1 $2').replaceAll('_', ' ').toLowerCase()
  }
  return type.replace(/^aws_/, '').replace(/^azurerm_/, '').replaceAll('_', ' ')
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!response.ok) {
    let message = `Request failed (${response.status})`
    try {
      const data = await response.json()
      message = data.detail || message
    } catch { /* use status text */ }
    throw new Error(message)
  }
  return response.json() as Promise<T>
}

function App() {
  const [view, setView] = useState<View>('Overview')
  const [modelConfigured, setModelConfigured] = useState(false)
  const [modelCheck, setModelCheck] = useState<ModelCheck | null>(null)
  const [checkingModel, setCheckingModel] = useState(false)
  const [clientWorkspaces, setClientWorkspaces] = useState<ClientWorkspace[]>([])
  const [clientId, setClientId] = useState('demo')
  const [inventory, setInventory] = useState<any>(null)
  const [run, setRun] = useState<RunResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<{ type: 'success' | 'error' | 'info'; text: string } | null>(null)
  const [selectedNode, setSelectedNode] = useState<Resource | null>(null)
  const [selectedFile, setSelectedFile] = useState('modules/Network/main.tf')
  const [search, setSearch] = useState('')
  const [severityFilter, setSeverityFilter] = useState('all')
  const [region, setRegion] = useState('us-east-1')
  const [profile, setProfile] = useState('')
  const [subscriptionId, setSubscriptionId] = useState('')
  const [resourceGroupFilter, setResourceGroupFilter] = useState('')
  const [cloudProvider, setCloudProvider] = useState<'azure' | 'aws'>('azure')
  const [showCloud, setShowCloud] = useState(false)
  const [mobileNav, setMobileNav] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    api<ClientWorkspace[]>('/api/clients').then(async (workspaces) => {
      setClientWorkspaces(workspaces)
      const first = workspaces[0]
      if (!first) throw new Error('No client workspace is assigned to this account.')
      setClientId(first.id)
      if (first.id === 'demo') setInventory(await api<any>('/api/demo'))
      else setInventory(null)
    }).catch((error) => {
      setNotice({ type: 'error', text: error instanceof Error ? error.message : 'The API is unavailable. Start the project with npm run dev.' })
    })
  }, [])

  useEffect(() => {
    api<{ azure_openai_configured: boolean }>('/api/health').then((health) => setModelConfigured(health.azure_openai_configured)).catch(() => setModelConfigured(false))
  }, [])

  async function checkModel() {
    setCheckingModel(true)
    try {
      const result = await api<ModelCheck>('/api/model/check', { method: 'POST', body: '{}' })
      setModelCheck(result)
    } catch (error) {
      setModelCheck({ status: 'request_failed', message: error instanceof Error ? error.message : 'The model connection check failed.' })
    } finally {
      setCheckingModel(false)
    }
  }

  const resources = run?.nodes ?? []
  const visibleResources = useMemo(() => resources.filter((resource) => {
    const query = search.toLowerCase().trim()
    return !query || [resource.name, resource.id, resource.type, resource.region, ...Object.values(resource.tags ?? {})].join(' ').toLowerCase().includes(query)
  }), [resources, search])
  const visibleFindings = useMemo(() => (run?.findings ?? []).filter((finding) => severityFilter === 'all' || finding.severity === severityFilter), [run, severityFilter])
  const fileNames = Object.keys(run?.files ?? {}).sort((a, b) => {
    const order = (path: string) => path.endsWith('.tf') ? 0 : path.endsWith('.json') ? 1 : 2
    return order(a) - order(b) || a.localeCompare(b)
  })

  async function runDiscovery(source = inventory) {
    if (!source) return
    setBusy(true)
    setNotice(null)
    setSelectedNode(null)
    try {
      const result = await api<RunResult>('/api/analyze', { method: 'POST', body: JSON.stringify({ ...source, client_id: clientId }) })
      setRun(result)
      setSelectedFile(Object.keys(result.files).find((file) => file.endsWith('/main.tf')) ?? 'main.tf')
      setView('Overview')
      setNotice({ type: 'success', text: `Discovery complete. ${result.summary.resources} resources are ready for review.` })
    } catch (error) {
      setNotice({ type: 'error', text: error instanceof Error ? error.message : 'Discovery could not complete.' })
    } finally {
      setBusy(false)
    }
  }

  async function importInventory(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (!file) return
    setBusy(true)
    setNotice(null)
    try {
      const parsed = JSON.parse(await file.text())
      setInventory(parsed)
      setRun(null)
      setNotice({ type: 'success', text: `${file.name} loaded. Start discovery to validate and map the inventory.` })
    } catch (error) {
      setNotice({ type: 'error', text: error instanceof Error && error.name === 'SyntaxError' ? 'This file is not valid JSON.' : 'Could not read the inventory file.' })
    } finally {
      setBusy(false)
      event.target.value = ''
    }
  }

  async function discoverAws() {
    setBusy(true)
    setNotice(null)
    try {
      const result = await api<any>('/api/providers/aws/discover', {
        method: 'POST',
        body: JSON.stringify({ client_id: clientId, region, profile: profile.trim() || undefined }),
      })
      setInventory(result)
      setRun(null)
      setShowCloud(false)
      setCloudProvider('aws')
      setNotice({ type: 'success', text: `Read ${result.resources.length} resources from ${region}. Start discovery to analyze them.` })
    } catch (error) {
      setNotice({ type: 'error', text: error instanceof Error ? error.message : 'AWS discovery failed.' })
    } finally {
      setBusy(false)
    }
  }

  async function discoverAzure() {
    setBusy(true)
    setNotice(null)
    try {
      const result = await api<any>('/api/providers/azure/discover', {
        method: 'POST',
        body: JSON.stringify({ client_id: clientId, subscription_id: subscriptionId.trim(), resource_group: resourceGroupFilter.trim() || undefined }),
      })
      setInventory(result)
      setRun(null)
      setShowCloud(false)
      setCloudProvider('azure')
      setNotice({ type: 'success', text: `Read ${result.resources.length} resources from Azure subscription ${subscriptionId.trim()}. Start discovery to analyze them.` })
    } catch (error) {
      setNotice({ type: 'error', text: error instanceof Error ? error.message : 'Azure discovery failed.' })
    } finally {
      setBusy(false)
    }
  }

  async function approvePackage() {
    if (!run) return
    setBusy(true)
    try {
      const result = await api<{ approval: RunResult['approval'] }>(`/api/runs/${run.run_id}/approve`, { method: 'POST', body: JSON.stringify({ reviewed: true }) })
      setRun({ ...run, approval: result.approval })
      setNotice({ type: 'success', text: 'Architect approval recorded for this demo run.' })
    } catch (error) {
      setNotice({ type: 'error', text: error instanceof Error ? error.message : 'Approval could not be recorded.' })
    } finally {
      setBusy(false)
    }
  }

  async function downloadPackage() {
    if (!run) return
    try {
      const response = await fetch(`/api/runs/${run.run_id}/package`)
      if (!response.ok) {
        const data = await response.json()
        throw new Error(data.detail || 'Package export failed.')
      }
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${run.environment.name.toLowerCase().replace(/[^a-z0-9]+/g, '-')}-genesis-iac.zip`
      link.click()
      URL.revokeObjectURL(url)
      setNotice({ type: 'success', text: 'The reviewed package downloaded to your device.' })
    } catch (error) {
      setNotice({ type: 'error', text: error instanceof Error ? error.message : 'Package export failed.' })
    }
  }

  const switchView = (next: View) => {
    setView(next)
    setMobileNav(false)
  }

  async function switchClient(nextClientId: string) {
    if (nextClientId === clientId) return
    setClientId(nextClientId)
    setRun(null)
    setSelectedNode(null)
    setSelectedFile('')
    setSearch('')
    const selected = clientWorkspaces.find((item) => item.id === nextClientId)
    if (selected?.id === 'demo') {
      try { setInventory(await api<any>('/api/demo')) }
      catch { setInventory(null) }
    } else {
      setInventory(null)
    }
  }

  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileNav ? 'sidebar-open' : ''}`}>
        <div className="brand-lockup">
          <div className="brand-mark"><span /><span /><span /></div>
          <div><div className="brand-name">GENESIS</div><div className="brand-sub">CLOUD BLUEPRINT STUDIO</div></div>
          <button className="icon-button sidebar-close" onClick={() => setMobileNav(false)} aria-label="Close navigation"><X size={17} /></button>
        </div>

        <label className="environment-picker">
          <div className="environment-icon"><Cloud size={17} /></div>
          <div className="environment-copy"><span>CLIENT WORKSPACE</span><select aria-label="Client workspace" value={clientId} onChange={(event) => void switchClient(event.target.value)} disabled={!clientWorkspaces.length}>{clientWorkspaces.map((workspace) => <option value={workspace.id} key={workspace.id}>{workspace.name}</option>)}</select></div>
          <ChevronDown size={14} className="muted-icon" />
        </label>

        <div className="sidebar-label">WORKSPACE</div>
        <nav className="main-navigation" aria-label="Main navigation">
          {navigation.map(({ label, icon: Icon, hint }) => (
            <button key={label} className={`nav-item ${view === label ? 'nav-active' : ''}`} onClick={() => switchView(label)} title={hint}>
              <Icon size={18} strokeWidth={1.8} /><span>{label}</span>
              {label === 'Guardrails' && run?.summary.critical_findings ? <span className="nav-alert">{run.summary.critical_findings}</span> : null}
            </button>
          ))}
        </nav>

        <div className="sidebar-label source-label">DATA SOURCE</div>
        <div className="source-summary">
          <span className="source-dot" /><div><strong>{inventory?.provider?.toUpperCase() ?? 'AZURE'} inventory</strong><small>{inventory?.region ?? 'multiple'} · read only</small></div>
          <button className="source-edit" onClick={() => { setCloudProvider('azure'); setShowCloud(true) }} aria-label="Configure cloud source"><ChevronRight size={15} /></button>
        </div>

        <div className="sidebar-bottom">
          <div className="safety-note"><Shield size={16} /><span><strong>Protected workflow</strong><small>Discovery only · no apply</small></span></div>
          <div className="user-mini"><div className="avatar">NS</div><div><strong>Cloud architect</strong><small>Demo workspace</small></div><CircleHelp size={16} className="muted-icon" /></div>
        </div>
      </aside>

      <div className="main-area">
        <header className="topbar">
          <button className="icon-button mobile-menu" onClick={() => setMobileNav(true)} aria-label="Open navigation"><Menu size={20} /></button>
          <div className="breadcrumbs"><span>GENESIS</span><ChevronRight size={14} /><strong>{view}</strong></div>
          <div className="topbar-right">
            <span className="readonly-chip"><LockKeyhole size={13} /> READ ONLY MODE</span>
            <div className="topbar-divider" />
            <button className="help-button" title="Help and project notes"><CircleHelp size={18} /></button>
            <div className="avatar top-avatar">NS</div>
          </div>
        </header>

        <main className="content-area">
          {notice ? <div className={`notice notice-${notice.type}`} role="status"><span>{notice.text}</span><button className="icon-button" onClick={() => setNotice(null)} aria-label="Dismiss message"><X size={15} /></button></div> : null}

          {view === 'Overview' && <Overview
            run={run} inventory={inventory} busy={busy} onRun={() => runDiscovery()} onImport={() => fileInput.current?.click()}
            onConnect={() => { setCloudProvider('azure'); setShowCloud(true) }} onNavigate={switchView} onNode={setSelectedNode}
            modelConfigured={modelConfigured} modelCheck={modelCheck} checkingModel={checkingModel} onCheckModel={checkModel}
          />}

          {view === 'Inventory' && <InventoryPage run={run} resources={visibleResources} search={search} setSearch={setSearch} onImport={() => fileInput.current?.click()} onRun={() => runDiscovery()} busy={busy} />}

          {view === 'Copilot' && <CopilotPage run={run} onRun={() => runDiscovery()} busy={busy} />}

          {view === 'Dependency graph' && <GraphPage run={run} selectedNode={selectedNode} setSelectedNode={setSelectedNode} onRun={() => runDiscovery()} busy={busy} />}

          {view === 'IaC package' && <PackagePage
            run={run} fileNames={fileNames} selectedFile={selectedFile} setSelectedFile={setSelectedFile}
            onApprove={approvePackage} onDownload={downloadPackage} onRun={() => runDiscovery()} busy={busy} />}

          {view === 'Guardrails' && <GuardrailsPage run={run} findings={visibleFindings} severityFilter={severityFilter} setSeverityFilter={setSeverityFilter} onRun={() => runDiscovery()} busy={busy} />}
        </main>
      </div>

      <input ref={fileInput} className="hidden-input" type="file" accept="application/json,.json" onChange={importInventory} />
      {showCloud && <CloudDialog provider={cloudProvider} setProvider={setCloudProvider} region={region} setRegion={setRegion} profile={profile} setProfile={setProfile} subscriptionId={subscriptionId} setSubscriptionId={setSubscriptionId} resourceGroup={resourceGroupFilter} setResourceGroup={setResourceGroupFilter} onClose={() => setShowCloud(false)} onDiscoverAzure={discoverAzure} onDiscoverAws={discoverAws} busy={busy} />}
      {mobileNav && <button className="nav-scrim" onClick={() => setMobileNav(false)} aria-label="Close navigation" />}
    </div>
  )
}

function PageHeading({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: React.ReactNode }) {
  return <div className="page-heading"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{description}</p></div>{action}</div>
}

function ModelConnectionPanel({ configured, check, checking, onCheck }: { configured: boolean; check: ModelCheck | null; checking: boolean; onCheck: () => void }) {
  const ready = check?.status === 'ready'
  const failed = Boolean(check && check.status !== 'ready' && check.status !== 'not_configured')
  const text = checking ? 'Checking Azure OpenAI identity, endpoint, deployment, and regional capacity…'
    : check?.message ?? (configured ? 'Azure OpenAI is configured. Run a live connection check before the first investigation.' : 'Local read-only tools are active. Set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_CHAT_DEPLOYMENT to enable Azure OpenAI.')
  return <section className={`model-connection ${ready ? 'model-connection-ready' : failed ? 'model-connection-failed' : ''}`}>
    <div className="model-connection-icon"><Sparkles size={15} /></div>
    <div className="model-connection-copy"><div><strong>{ready ? 'AZURE OPENAI · READY' : configured ? 'AZURE OPENAI · CONFIGURED' : 'LOCAL TOOL MODE'}</strong>{check?.deployment ? <small>{check.deployment}</small> : null}</div><p>{text}</p></div>
    <button className="button button-secondary" onClick={onCheck} disabled={checking || !configured}><RefreshCw size={13} className={checking ? 'spin' : ''} />{checking ? 'Checking…' : 'Check connection'}</button>
  </section>
}

function CopilotPage({ run, onRun, busy }: { run: RunResult | null; onRun: () => void; busy: boolean }) {
  const [messages, setMessages] = useState<CopilotMessage[]>([])
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [error, setError] = useState('')
  const transcriptRef = useRef<HTMLDivElement>(null)

  useEffect(() => { setMessages([]); setError('') }, [run?.run_id])
  useEffect(() => { transcriptRef.current?.scrollTo({ top: transcriptRef.current.scrollHeight, behavior: 'smooth' }) }, [messages, asking])

  async function submitQuestion(value = question) {
    const prompt = value.trim()
    if (!run || !prompt || asking) return
    setQuestion('')
    setError('')
    setMessages((current) => [...current, { role: 'user', content: prompt }])
    setAsking(true)
    try {
      const response = await api<{ answer: string; mode: string; notice: string; citations: CopilotCitation[]; tool_calls: ToolCall[] }>(`/api/runs/${run.run_id}/ask`, {
        method: 'POST', body: JSON.stringify({ question: prompt }),
      })
      setMessages((current) => [...current, { role: 'assistant', content: response.answer, citations: response.citations, tool_calls: response.tool_calls, mode: response.mode, notice: response.notice }])
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'The estate assistant could not answer.')
      setMessages((current) => [...current, { role: 'assistant', content: 'I could not complete that answer. You can retry or ask about a resource name, finding, relationship, or Terraform mapping.' }])
    } finally {
      setAsking(false)
    }
  }

  if (!run) return <EmptyPage icon={Sparkles} title="Ask GENESIS about a discovered estate" copy="Run discovery first. Copilot answers from one analyzed inventory and cites the records it used." action={<button className="button button-primary" onClick={onRun} disabled={busy}><Play size={15} />{busy ? 'Analyzing…' : 'Analyze sample inventory'}</button>} />

  const impactTarget = run.nodes.find((node) => run.edges.some((edge) => edge.target === node.id)) ?? run.nodes[0]
  const suggestions = ['Summarize this environment', 'What risks should I review?', `What breaks if I remove ${impactTarget?.name ?? 'a resource'}?`, 'How are network resources connected?']
  const modelUsed = messages.some((item) => item.mode === 'azure_openai_tool_calling')
  return <>
    <PageHeading eyebrow="EVIDENCE-LED ASSISTANT" title="Ask about this estate" description={`Answers are scoped to ${run.environment.name} and cite evidence from this discovery run.`} action={<span className={`agent-mode-badge ${modelUsed ? 'agent-mode-azure' : ''}`}><Sparkles size={13} />{modelUsed ? 'AZURE OPENAI · GROUNDED' : 'LOCAL EVIDENCE'}</span>} />
    <section className="panel copilot-panel">
      <div className="copilot-boundary"><ShieldCheck size={16} /><div><strong>Read-only answers, tied to this run</strong><span>Copilot has no cloud, Terraform, approval, or export tools. It will say when the inventory does not contain enough evidence.</span></div></div>
      <div className="copilot-transcript" ref={transcriptRef} aria-live="polite" aria-label="Conversation">
        {!messages.length ? <div className="copilot-welcome"><div className="copilot-welcome-icon"><Sparkles size={20} /></div><h2>What would you like to understand?</h2><p>Ask about resources, connections, findings, coverage, or items that need manual mapping.</p><div className="copilot-suggestions">{suggestions.map((suggestion) => <button key={suggestion} onClick={() => void submitQuestion(suggestion)} disabled={asking}>{suggestion}<ArrowRight size={13} /></button>)}</div></div> : null}
        {messages.map((message, index) => <article className={`copilot-message copilot-${message.role}`} key={`${index}-${message.role}`}><div className="copilot-message-avatar">{message.role === 'assistant' ? <Sparkles size={14} /> : 'You'}</div><div className="copilot-message-body"><div className="copilot-message-role">{message.role === 'assistant' ? `GENESIS COPILOT · ${message.mode === 'azure_openai_tool_calling' ? 'AZURE OPENAI' : 'LOCAL TOOLS'}` : 'YOU'}</div><p>{message.content}</p>{message.notice ? <small className="copilot-notice">{message.notice}</small> : null}{message.citations?.length ? <div className="copilot-citations"><span>Evidence used</span>{message.citations.map((citation) => <details key={citation.evidence_id}><summary>{citation.label}</summary><p>{citation.excerpt}</p></details>)}</div> : null}{message.tool_calls?.length ? <div className="copilot-trace"><div className="copilot-trace-title">TOOLS CALLED · {message.tool_calls.length}</div><AgentTrace calls={message.tool_calls} /></div> : null}</div></article>)}
        {asking ? <article className="copilot-message copilot-assistant"><div className="copilot-message-avatar"><Sparkles size={14} /></div><div className="copilot-message-body"><div className="copilot-message-role">GENESIS COPILOT</div><p className="copilot-thinking">Checking run evidence…</p></div></article> : null}
      </div>
      <form className="copilot-composer" onSubmit={(event) => { event.preventDefault(); void submitQuestion() }}>
        <label htmlFor="copilot-question">Ask a question about this inventory</label>
        <div><textarea id="copilot-question" value={question} onChange={(event) => setQuestion(event.target.value)} maxLength={1000} rows={2} placeholder="For example: Which public-facing resources have security findings?" disabled={asking} /><button className="button button-primary" type="submit" disabled={!question.trim() || asking}><ArrowRight size={15} />{asking ? 'Thinking…' : 'Ask'}</button></div>
        <small>{error || 'Azure OpenAI receives selected evidence only when separately enabled by an administrator.'}<span>{question.length}/1000</span></small>
      </form>
    </section>
  </>
}

function Overview({ run, inventory, busy, onRun, onImport, onConnect, onNavigate, onNode, modelConfigured, modelCheck, checkingModel, onCheckModel }: {
  run: RunResult | null; inventory: any; busy: boolean; onRun: () => void; onImport: () => void; onConnect: () => void; onNavigate: (view: View) => void; onNode: (node: Resource) => void
  modelConfigured: boolean; modelCheck: ModelCheck | null; checkingModel: boolean; onCheckModel: () => void
}) {
  if (!run) {
    return <>
      <PageHeading eyebrow="DISCOVERY WORKSPACE" title="Cloud estate, understood." description="Map inherited infrastructure, organize the relationships, and prepare a Terraform package for architect review." />
      <ModelConnectionPanel configured={modelConfigured} check={modelCheck} checking={checkingModel} onCheck={onCheckModel} />
      <section className="welcome-layout">
        <div className="welcome-main">
          <div className="welcome-orbit"><div className="orbit-ring orbit-one" /><div className="orbit-ring orbit-two" /><div className="orbit-core"><CloudCog size={30} /></div><span className="orbit-node node-a"><Network size={15} /></span><span className="orbit-node node-b"><Braces size={15} /></span><span className="orbit-node node-c"><ShieldCheck size={15} /></span></div>
          <div className="welcome-copy"><span className="overline"><Sparkles size={13} /> AGENTIC REVERSE ENGINEERING</span><h2>From click-ops<br />to clear blueprints.</h2><p>GENESIS maps resources and dependencies, groups them into modules, then prepares import-aware Terraform for a human-led review.</p>
            <div className="welcome-actions"><button className="button button-primary" onClick={onRun} disabled={busy}><Play size={16} fill="currentColor" />{busy ? 'Running discovery…' : 'Run discovery'}<ArrowRight size={15} /></button><button className="button button-secondary" onClick={onImport}><Upload size={16} />Import inventory</button></div>
            <div className="micro-note"><ShieldCheck size={14} /> No-key sample mode; Azure OpenAI is optional. No cloud changes are made.</div>
          </div>
        </div>
        <div className="welcome-side">
          <div className="source-card-head"><div><div className="eyebrow">CURRENT SOURCE</div><strong>{inventory?.name ?? 'Loading sample inventory'}</strong></div><span className="connection-state"><span className="source-dot" /> READY</span></div>
          <div className="source-details"><div><Cloud size={15} /><span>{(inventory?.provider ?? 'azure').toUpperCase()}</span></div><div><Network size={15} /><span>{inventory?.region ?? 'multiple'}</span></div><div><Boxes size={15} /><span>{inventory?.resources?.length ?? '—'} sample resources</span></div></div>
          <button className="text-action" onClick={onConnect}>Configure a read-only Azure scan <ArrowRight size={14} /></button>
          <div className="side-rule" />
          <div className="three-step"><div className="step-number">01</div><div><strong>Discover</strong><small>Read resource inventory</small></div><div className="step-number">02</div><div><strong>Structure</strong><small>Build dependency modules</small></div><div className="step-number">03</div><div><strong>Review</strong><small>Approve the generated package</small></div></div>
        </div>
      </section>
      <section className="brief-note"><div className="brief-note-icon"><CircleHelp size={17} /></div><p><strong>Outcome scenario from the hackathon brief</strong><span>Assuming 20 work days per month, 2–3 months to 3–4 days implies 90–95% less elapsed time (36–57 work days). This is a target calculation, not a measured demo result.</span></p><span className="target-pill">90–95% · target</span></section>
      <section className="workflow-preview"><div className="section-title"><div><div className="eyebrow">AGENT WORKFLOW</div><h2>Tool calls, one human gate</h2></div><span className="workflow-mode"><span /> TOOL-ROUTED · HUMAN-GATED</span></div><div className="preview-stages">
        {[
          ['Inventory', 'Sample or live read', Cloud], ['Investigator', 'Explores with tools', Sparkles], ['Terraform writer', 'Drafts skipped types', Code2], ['Reviewer', 'Rejects weak citations', ShieldCheck], ['Copilot', 'Same tools, Q&A', Search], ['Architect gate', 'Reviews and downloads', BadgeCheck],
        ].map(([name, caption, Icon], index) => { const AgentIcon = Icon as LucideIcon; return <div className="preview-stage" key={name as string}><div className="preview-stage-icon"><AgentIcon size={17} /></div><span className="preview-stage-index">0{index + 1}</span><strong>{name as string}</strong><small>{caption as string}</small>{index < 5 && <ArrowRight className="stage-arrow" size={15} />}</div> })}
      </div></section>
    </>
  }

  const summary = run.summary
  const modules = run.modules
  return <>
    <PageHeading eyebrow="DISCOVERY WORKSPACE" title={run.environment.name} description={`Inventory analysis · ${run.environment.provider.toUpperCase()} · ${run.environment.region}`} action={<button className="button button-primary" onClick={onRun} disabled={busy}><RefreshCw size={15} className={busy ? 'spin' : ''} />{busy ? 'Analyzing…' : 'Re-run discovery'}</button>} />
    <ModelConnectionPanel configured={modelConfigured} check={modelCheck} checking={checkingModel} onCheck={onCheckModel} />
    <section className="metric-grid">
      <Metric icon={Boxes} label="Resources mapped" value={summary.resources} note="From imported inventory" tint="blue" />
      <Metric icon={GitBranch} label="Relationships" value={summary.relationships} note="Resolved dependency links" tint="lavender" />
      <Metric icon={Layers3} label="Suggested modules" value={summary.modules} note="Grouped from resource types" tint="green" />
      <Metric icon={ShieldAlert} label="Review findings" value={summary.findings} note={summary.critical_findings ? `${summary.critical_findings} critical` : 'No critical findings'} tint={summary.critical_findings ? 'amber' : 'green'} />
    </section>

    <div className="overview-grid">
      <section className="panel agent-panel"><div className="panel-heading"><div><div className="eyebrow">AGENT RUN</div><h2>Discovery pipeline</h2></div><span className="complete-badge"><CheckCircle2 size={14} /> COMPLETE</span></div>
        <div className="agent-list">{run.logs.map((log, index) => <div className="agent-row" key={log.agent}><div className={`agent-icon agent-${log.agent.toLowerCase()}`}>{log.status === 'review' ? <AlertTriangle size={16} /> : log.status === 'fallback' ? <RefreshCw size={15} /> : <Check size={16} />}</div><div className="agent-copy"><div><strong>{log.agent}</strong><span className={`agent-state state-${log.status}`}>{log.status === 'review' ? 'REVIEW' : log.status === 'fallback' ? 'FALLBACK' : 'COMPLETE'}</span></div><p>{log.message}</p></div><span className="agent-index">0{index + 1}</span></div>)}</div>
        <div className="validation-callout"><Shield size={16} /><span><strong>Terraform CLI validation was not run.</strong> Local checks cover inventory shape and policy signals only.</span><button className="icon-button" onClick={() => onNavigate('Guardrails')} aria-label="View guardrails"><ArrowRight size={16} /></button></div>
      </section>
      <section className="panel outcome-panel"><div className="panel-heading"><div><div className="eyebrow">PACKAGE READINESS</div><h2>Review before adoption</h2></div><div className="readiness-ring" style={{ '--coverage': `${summary.coverage}%` } as React.CSSProperties}><span>{summary.coverage}%</span></div></div>
        <p className="readiness-intro">Resource-block coverage in this generated package. Unsupported or incomplete resources stay in the review manifest.</p>
        <div className="readiness-line"><span>Terraform resource blocks</span><strong>{summary.terraform_resources} / {summary.resources}</strong></div>
        <div className="progress-track"><span style={{ width: `${summary.coverage}%` }} /></div>
        <div className="outcome-list"><div><span className="outcome-check"><Check size={12} /></span><span>Dependency graph assembled</span><strong>{summary.relationships}</strong></div><div><span className={summary.skipped ? 'outcome-warn' : 'outcome-check'}>{summary.skipped ? <AlertTriangle size={12} /> : <Check size={12} />}</span><span>Resources need manual mapping</span><strong>{summary.skipped}</strong></div><div><span className={summary.findings ? 'outcome-warn' : 'outcome-check'}>{summary.findings ? <AlertTriangle size={12} /> : <Check size={12} />}</span><span>Policy findings</span><strong>{summary.findings}</strong></div><div><span className="outcome-check"><Activity size={11} /></span><span>Analysis runtime</span><strong>{summary.analysis_seconds}s</strong></div></div>
        <button className="button button-dark full-width" onClick={() => onNavigate('IaC package')}>Review IaC package <ArrowRight size={15} /></button>
      </section>
    </div>

    <InvestigatorPanel investigation={run.investigation} resources={run.nodes} />
    <AgentReviewPanel review={run.agent_review} resources={run.nodes} />

    <div className="lower-grid">
      <section className="panel module-panel"><div className="panel-heading"><div><div className="eyebrow">PROPOSED STRUCTURE</div><h2>Terraform modules</h2></div><button className="inline-link" onClick={() => onNavigate('IaC package')}>View package <ArrowRight size={13} /></button></div>
        <div className="module-list">{modules.map((module) => <div className="module-row" key={module.id}><div className="module-folder" style={{ color: moduleColor[module.id] }}><Layers3 size={17} /></div><div className="module-description"><strong>{module.label}</strong><small>modules/{module.label.toLowerCase()}</small></div><span className="module-count">{module.count} {module.count === 1 ? 'resource' : 'resources'}</span><ChevronRight size={15} className="muted-icon" /></div>)}</div>
      </section>
      <section className="panel preview-graph-panel"><div className="panel-heading"><div><div className="eyebrow">DEPENDENCY MAP</div><h2>Resource topology</h2></div><button className="icon-button" onClick={() => onNavigate('Dependency graph')} aria-label="Open dependency graph"><ArrowRight size={16} /></button></div><MiniGraph run={run} onNode={onNode} onOpen={() => onNavigate('Dependency graph')} /></section>
    </div>
  </>
}

function AgentTrace({ calls }: { calls: ToolCall[] }) {
  return <div className="agent-tool-list">{calls.map((item, index) => <details className="agent-tool-row" key={`${item.tool}-${index}`}>
    <summary><Code2 size={14} /><span><strong>{item.tool.replaceAll('_', ' ')}</strong><small>{item.result}</small></span><ChevronDown size={13} /></summary>
    {item.arguments && Object.keys(item.arguments).length ? <pre>{JSON.stringify(item.arguments, null, 2)}</pre> : null}
  </details>)}</div>
}

function InvestigatorPanel({ investigation, resources }: { investigation: Investigation; resources: Resource[] }) {
  const names = new Map(resources.map((resource) => [resource.id, resource.name]))
  const local = investigation.mode !== 'azure_openai_tool_calling'
  return <section className="panel investigation-panel">
    <div className="panel-heading"><div><div className="eyebrow">INVESTIGATOR · TOOL-DRIVEN EXPLORATION</div><h2>Workloads, risks, and open questions</h2></div><span className={`agent-mode-badge ${local ? '' : 'agent-mode-azure'}`}><Sparkles size={13} />{local ? 'LOCAL TOOL FALLBACK' : 'AZURE OPENAI · INVESTIGATOR'}</span></div>
    <p className="agentic-summary">{investigation.summary}</p>
    {investigation.model_note ? <div className="agent-fallback-note">{investigation.model_note}</div> : null}
    <div className="investigation-grid">
      <div><div className="agentic-subheading">INFERRED WORKLOADS <span>{investigation.workloads.length}</span></div><div className="investigation-list">{investigation.workloads.map((workload) => <article className="investigation-card" key={workload.name}><strong>{workload.name}</strong><p>{workload.purpose}</p><div className="evidence-resource-list">{workload.resource_ids.slice(0, 8).map((id) => <span key={id} title={id}>{names.get(id) ?? id}</span>)}</div></article>)}</div></div>
      <div><div className="agentic-subheading">CITED RISKS <span>{investigation.risks.length}</span></div><div className="investigation-list">{investigation.risks.slice(0, 8).map((risk, index) => <article className="investigation-card investigation-risk" key={`${risk.title}-${index}`}><div><span className={`agentic-priority priority-${risk.severity}`}>{risk.severity}</span><strong>{risk.title}</strong></div><p>{risk.description}</p><div className="evidence-resource-list">{risk.resource_ids.map((id) => <span key={id} title={id}>{names.get(id) ?? id}</span>)}</div></article>)}{!investigation.risks.length ? <div className="agentic-empty">No risk claim passed resource-ID validation.</div> : null}</div></div>
    </div>
    <div className="investigation-questions"><strong>OPEN QUESTIONS</strong>{investigation.open_questions.length ? <ul>{investigation.open_questions.map((question, index) => <li key={index}>{question}</li>)}</ul> : <span>No additional questions were produced from the available inventory.</span>}</div>
    <div className="investigation-trace"><div className="agentic-subheading">READ-ONLY TOOL TRACE <span>{investigation.tool_calls.length} calls · limit 12</span></div><AgentTrace calls={investigation.tool_calls} /></div>
    <div className="agentic-boundary"><ShieldCheck size={15} /><span>Every displayed risk cites resource IDs present in the active inventory. Tool calls cannot write to Azure or approve Terraform.</span></div>
  </section>
}

function AgentReviewPanel({ review, resources }: { review: AgentReview; resources: Resource[] }) {
  const modeLabel = review.mode === 'azure_openai_tool_calling'
    ? `AZURE OPENAI · ${review.model_deployment ?? 'TOOL CALLING'}`
    : review.mode === 'deterministic_fallback'
      ? 'LOCAL FALLBACK · MODEL UNAVAILABLE'
      : 'LOCAL TOOL REVIEW'
  const names = new Map(resources.map((resource) => [resource.id, resource.name]))
  const isAzure = review.mode === 'azure_openai_tool_calling'
  return <section className="panel agentic-review-panel">
    <div className="panel-heading"><div><div className="eyebrow">REVIEWER · CITATION GATE</div><h2>Evidence-checked actions</h2></div><span className={`agent-mode-badge ${isAzure ? 'agent-mode-azure' : ''}`}><Sparkles size={13} />{modeLabel}</span></div>
    <p className="agentic-summary">{review.summary}</p>
    {review.model_note ? <div className="agent-fallback-note">{review.model_note}</div> : null}
    <div className="agentic-review-grid">
      <div><div className="agentic-subheading">RECOMMENDED REVIEW ACTIONS</div>
        {review.recommendations.length ? <div className="agentic-action-list">{review.recommendations.map((item, index) => <article className="agentic-action" key={`${item.priority}-${index}`}><span className={`agentic-priority priority-${item.priority}`}>{item.priority}</span><div><strong>{item.action}</strong><p>{item.evidence}</p><div className="evidence-resource-list">{item.resource_ids.map((id) => <span key={id} title={id}>{names.get(id) ?? id}</span>)}</div></div></article>)}</div> : <div className="agentic-empty">No recommendation with a valid resource citation passed review.</div>}
        <div className="citation-checkline">{review.citation_checks.valid_citations}/{review.citation_checks.cited_items} citations checked · {review.citation_checks.rejected_claims} unsupported claims rejected</div>
      </div>
      <div><div className="agentic-subheading">READ-ONLY TOOL TRACE <span>{review.tool_calls.length} calls · limit 4</span></div><AgentTrace calls={review.tool_calls} /></div>
    </div>
    <div className="agentic-boundary"><ShieldCheck size={15} /><span>Reviewer claims without a real inventory resource citation are dropped. Human approval remains required; this role has no cloud write tools.</span></div>
  </section>
}

function Metric({ icon: Icon, label, value, note, tint }: { icon: LucideIcon; label: string; value: React.ReactNode; note: string; tint: string }) {
  return <div className="metric-card"><div className={`metric-icon tint-${tint}`}><Icon size={17} /></div><div className="metric-label">{label}</div><div className="metric-value">{value}</div><div className="metric-note">{note}</div></div>
}

function InventoryPage({ run, resources, search, setSearch, onImport, onRun, busy }: { run: RunResult | null; resources: Resource[]; search: string; setSearch: (value: string) => void; onImport: () => void; onRun: () => void; busy: boolean }) {
  if (!run) return <EmptyPage icon={Boxes} title="No inventory analyzed" copy="Load an inventory JSON file or use the included sample, then run discovery to inspect individual resources." action={<button className="button button-primary" onClick={onRun} disabled={busy}><Play size={15} />{busy ? 'Analyzing…' : 'Analyze sample inventory'}</button>} />
  return <>
    <PageHeading eyebrow="SOURCE INVENTORY" title="Resources" description={`${run.summary.resources} records · ${run.environment.provider.toUpperCase()} · ${run.environment.region}`} action={<button className="button button-secondary" onClick={onImport}><Upload size={15} />Import JSON</button>} />
    <div className="table-toolbar"><div className="search-box"><Search size={16} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search name, id, type, or tag" /></div><span className="table-count">Showing {resources.length} of {run.summary.resources}</span><button className="filter-control"><ListFilter size={15} />All resources<ChevronDown size={13} /></button></div>
    <div className="panel inventory-table-wrap"><table className="inventory-table"><thead><tr><th>RESOURCE</th><th>TYPE</th><th>REGION</th><th>PROPOSED MODULE</th><th>IaC STATUS</th></tr></thead><tbody>
      {resources.map((resource) => { const mapped = !run.skipped.some((item) => item.id === resource.id); const writer = resource.terraform_writer; return <tr key={resource.id}><td><div className="resource-name-cell"><div className={`resource-type-icon icon-${resource.module ?? 'supporting'}`}><ResourceIcon type={resource.type} size={16} /></div><div><strong>{resource.name}</strong><small>{resource.id}</small></div></div></td><td><span className="type-label">{displayType(resource.type)}</span></td><td>{resource.region}</td><td><span className="module-tag"><span style={{ backgroundColor: moduleColor[resource.module ?? 'supporting'] }} />{MODULES_LABEL(resource.module)}</span></td><td><span className={`iac-status ${mapped ? 'iac-mapped' : 'iac-review'}`}>{mapped ? <>{writer?.status === 'validated' ? <BadgeCheck size={13} /> : <CheckCircle2 size={13} />}{writer ? `Writer · ${writer.status}` : 'Mapped'}</> : <><AlertTriangle size={13} />Needs review</>}</span></td></tr> })}
    </tbody></table>{resources.length === 0 && <div className="table-empty">No resources match “{search}”.</div>}</div>
  </>
}

const MODULES_LABEL = (key?: string) => (({ network: 'Network', application: 'Application', data: 'Data', identity: 'Identity', supporting: 'Supporting' } as Record<string, string>)[key ?? 'supporting'] ?? 'Supporting')

function ResourceIcon({ type, size = 16 }: { type: string; size?: number }) {
  const value = type.toLowerCase()
  if (value.includes('vpc') || value.includes('subnet') || value.includes('security_group') || value.includes('network')) return <Network size={size} />
  if (value.includes('rds') || value.includes('db') || value.includes('bucket') || value.includes('storage')) return <Database size={size} />
  if (value.includes('iam') || value.includes('role') || value.includes('policy')) return <KeyRound size={size} />
  if (value.includes('lb') || value.includes('load_balancer')) return <GitBranch size={size} />
  if (value.includes('instance') || value.includes('vm')) return <Server size={size} />
  return <HardDrive size={size} />
}

function EmptyPage({ icon: Icon, title, copy, action }: { icon: LucideIcon; title: string; copy: string; action: React.ReactNode }) {
  return <div className="empty-state-page"><div className="empty-icon"><Icon size={23} /></div><h2>{title}</h2><p>{copy}</p>{action}</div>
}

function GraphPage({ run, selectedNode, setSelectedNode, onRun, busy }: { run: RunResult | null; selectedNode: Resource | null; setSelectedNode: (node: Resource | null) => void; onRun: () => void; busy: boolean }) {
  if (!run) return <EmptyPage icon={Network} title="The graph is waiting for inventory" copy="Run discovery to connect resources by their VPC, subnet, security group, and other references." action={<button className="button button-primary" onClick={onRun} disabled={busy}><Play size={15} />{busy ? 'Analyzing…' : 'Analyze sample inventory'}</button>} />
  return <>
    <PageHeading eyebrow="RESOURCE RELATIONSHIPS" title="Dependency graph" description="Each line represents a relationship found in the imported inventory. Select a resource to inspect its source record." action={<div className="graph-total"><Network size={15} />{run.summary.relationships} links</div>} />
    <div className="panel graph-panel"><Graph run={run} selectedNode={selectedNode} onNode={setSelectedNode} /></div>
    <div className="graph-detail-grid"><section className="panel graph-legend"><div className="eyebrow">MODULE LEGEND</div><div className="legend-items">{run.modules.map((module) => <span key={module.id}><i style={{ backgroundColor: moduleColor[module.id] }} />{module.label}<small>{module.count}</small></span>)}</div></section>
      <section className="panel graph-inspector"><div className="eyebrow">RESOURCE INSPECTOR</div>{selectedNode ? <div className="inspector-row"><div className={`resource-type-icon icon-${selectedNode.module ?? 'supporting'}`}><ResourceIcon type={selectedNode.type} /></div><div><strong>{selectedNode.name}</strong><small>{selectedNode.id} · {displayType(selectedNode.type)} · {selectedNode.region}</small></div><button className="icon-button" onClick={() => setSelectedNode(null)} aria-label="Clear resource selection"><X size={15} /></button></div> : <div className="inspector-empty">Select any node in the graph to see its inventory details.</div>}</section></div>
  </>
}

function Graph({ run, selectedNode, onNode, compact = false }: { run: RunResult; selectedNode: Resource | null; onNode: (node: Resource) => void; compact?: boolean }) {
  const categoryOrder = ['network', 'application', 'data', 'identity', 'supporting']
  const categoryNames = { network: 'NETWORK', application: 'APPLICATION', data: 'DATA', identity: 'IDENTITY', supporting: 'SUPPORTING' } as Record<string, string>
  const layout: Record<string, number> = { network: 140, application: 390, data: 640, identity: 860, supporting: 1010 }
  const grouped = categoryOrder.map((category) => ({ category, nodes: run.nodes.filter((node) => (node.module ?? 'supporting') === category) })).filter((group) => group.nodes.length)
  const maxRows = Math.max(1, ...grouped.map((group) => group.nodes.length))
  const height = compact ? 300 : Math.max(510, maxRows * 91 + 100)
  const nodePosition = new Map<string, { x: number; y: number }>()
  grouped.forEach(({ category, nodes }) => nodes.forEach((node, index) => nodePosition.set(node.id, { x: layout[category], y: 74 + index * 88 })))
  const edgePositions = run.edges.map((edge) => ({ edge, source: nodePosition.get(edge.source), target: nodePosition.get(edge.target) })).filter((item) => item.source && item.target)
  return <div className={`graph-scroll ${compact ? 'graph-scroll-compact' : ''}`}><svg className="topology-svg" viewBox={`0 0 1150 ${height}`} role="img" aria-label="Cloud resource dependency graph">
    <defs><marker id={compact ? 'arrow-mini' : 'arrow-main'} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#9ba7b5" /></marker></defs>
    {grouped.map(({ category }) => <g key={category}><rect x={layout[category] - 86} y="19" width="174" height={height - 40} rx="15" fill={category === 'network' ? '#eef5f8' : category === 'application' ? '#f2f1fc' : category === 'data' ? '#eef7f1' : '#f5f2ed'} stroke="#e6eaf0" strokeDasharray="4 5" /><text x={layout[category]} y="45" className="svg-group-label" textAnchor="middle">{categoryNames[category]}</text></g>)}
    {edgePositions.map(({ edge, source, target }, index) => { const sx = source!.x, sy = source!.y, tx = target!.x, ty = target!.y; const startX = sx + (sx < tx ? 76 : -76); const endX = tx + (sx < tx ? -76 : 76); const bend = (startX + endX) / 2; return <g key={`${edge.source}-${edge.target}-${index}`}><path d={`M ${startX} ${sy} C ${bend} ${sy}, ${bend} ${ty}, ${endX} ${ty}`} fill="none" stroke="#a5b0bd" strokeWidth="1.4" markerEnd={`url(#${compact ? 'arrow-mini' : 'arrow-main'})`} /><title>{edge.relation.replaceAll('_', ' ')}</title></g> })}
    {grouped.flatMap(({ category, nodes }) => nodes.map((node) => { const pos = nodePosition.get(node.id)!; const selected = selectedNode?.id === node.id; const title = node.name.length > 19 ? `${node.name.slice(0, 17)}…` : node.name; return <g key={node.id} className={`graph-node ${selected ? 'graph-node-selected' : ''}`} onClick={() => onNode(node)} role="button" tabIndex={0} onKeyDown={(event) => event.key === 'Enter' && onNode(node)}><rect x={pos.x - 76} y={pos.y - 25} width="152" height="50" rx="10" fill={selected ? '#f1f1fe' : '#fff'} stroke={selected ? '#7778e7' : '#dce3eb'} strokeWidth={selected ? '1.6' : '1'} /><rect x={pos.x - 76} y={pos.y - 25} width="4" height="50" rx="2" fill={moduleColor[category]} /><foreignObject x={pos.x - 63} y={pos.y - 14} width="24" height="24"><div className="svg-resource-icon" style={{ color: moduleColor[category] }}><ResourceIcon type={node.type} size={15} /></div></foreignObject><text x={pos.x - 34} y={pos.y - 2} className="svg-node-name">{title}</text><text x={pos.x - 34} y={pos.y + 13} className="svg-node-type">{displayType(node.type).slice(0, 19)}</text></g> }))}
  </svg></div>
}

function MiniGraph({ run, onNode, onOpen }: { run: RunResult; onNode: (node: Resource) => void; onOpen: () => void }) {
  return <><Graph run={run} onNode={onNode} selectedNode={null} compact /><div className="mini-graph-footer"><span><i className="legend-dot" />{run.summary.resources} resources</span><span><i className="legend-line" />{run.summary.relationships} relationships</span><button onClick={onOpen}>Inspect graph <ArrowRight size={12} /></button></div></>
}

function PackagePage({ run, fileNames, selectedFile, setSelectedFile, onApprove, onDownload, onRun, busy }: { run: RunResult | null; fileNames: string[]; selectedFile: string; setSelectedFile: (file: string) => void; onApprove: () => void; onDownload: () => void; onRun: () => void; busy: boolean }) {
  const [acknowledged, setAcknowledged] = useState(false)
  if (!run) return <EmptyPage icon={FileCode2} title="No package generated yet" copy="Run discovery to group resources and generate import-aware Terraform files for review." action={<button className="button button-primary" onClick={onRun} disabled={busy}><Play size={15} />{busy ? 'Analyzing…' : 'Analyze sample inventory'}</button>} />
  return <>
    <PageHeading eyebrow="GENERATED ARTIFACTS" title="IaC package" description="Review the generated modules, import manifest, skipped resources, and policy report before export." action={run.approval.approved ? <button className="button button-primary" onClick={onDownload}><Download size={15} />Download reviewed package</button> : <span className="approval-pending"><LockKeyhole size={14} />Approval required to export</span>} />
    <div className="package-summary-grid"><div className="package-stat"><span>Terraform resources</span><strong>{run.summary.terraform_resources}<small> / {run.summary.resources}</small></strong></div><div className="package-stat"><span>Module folders</span><strong>{run.summary.modules}</strong></div><div className="package-stat"><span>Resource block coverage</span><strong>{run.summary.coverage}<small>% · from {run.summary.coverage_before_writer}%</small></strong></div><div className="package-stat"><span>Needs manual mapping</span><strong>{run.summary.skipped}</strong></div></div>
    {run.terraform_drafts.length ? <section className="panel terraform-writer-panel"><div className="panel-heading"><div><div className="eyebrow">BOUNDED TERRAFORM WRITER</div><h2>Skipped types drafted for review</h2></div><span className="filter-count">{run.terraform_drafts.filter((item) => item.status === 'validated').length} validated · {run.terraform_drafts.filter((item) => item.status === 'unverified').length} unverified</span></div><div className="terraform-draft-list">{run.terraform_drafts.map((draft) => <article className="terraform-draft-row" key={draft.resource_id}><div><strong>{draft.name}</strong><small>{draft.source_type} → {draft.terraform_type} · {draft.provenance.replaceAll('_', ' ')} · {draft.attempts} attempt(s)</small></div><span className={`draft-status draft-${draft.status}`}>{draft.status.toUpperCase()}</span><p>{draft.status === 'validated' ? 'Passed local HCL delimiter and required-argument checks. Terraform CLI validation was not run.' : draft.errors.join(' ') || 'Needs architect review.'}</p></article>)}</div><div className="agentic-boundary"><ShieldCheck size={15} /><span>Generated HCL is a draft only. GENESIS never runs terraform apply.</span></div></section> : null}
    <div className="package-workspace"><section className="panel file-explorer"><div className="file-explorer-head"><span>PACKAGE FILES</span><span>{fileNames.length} files</span></div><div className="file-tree">{fileNames.map((file) => <button key={file} className={`file-row ${selectedFile === file ? 'file-selected' : ''}`} onClick={() => setSelectedFile(file)}><FileIcon path={file} /><span>{file}</span></button>)}</div><div className="file-explorer-note"><Shield size={14} />No credentials are included.</div></section>
      <section className="panel code-viewer"><div className="code-header"><div><FileIcon path={selectedFile} /><strong>{selectedFile || 'Select a file'}</strong></div><span>READ ONLY PREVIEW</span></div><div className="code-content"><pre>{run.files[selectedFile] ?? 'Select a file from the package tree.'}</pre></div></section></div>
    <div className="package-bottom-grid"><section className="panel review-summary"><div className="panel-heading"><div><div className="eyebrow">ARCHITECT REVIEW</div><h2>Approval gate</h2></div>{run.approval.approved ? <span className="complete-badge"><BadgeCheck size={14} /> APPROVED</span> : <span className="pending-badge"><LockKeyhole size={13} /> PENDING</span>}</div>
        <p>Approve only after reviewing the generated files, policy findings, and any unmapped resources. This in-memory demo acknowledgement unlocks the package ZIP for download.</p>
        <div className="review-checklist"><div><span className="checklist-icon"><Check size={12} /></span><span>Confirm resource names and relationships</span></div><div><span className="checklist-icon"><Check size={12} /></span><span>Review security findings and skipped mappings</span></div><div><span className="checklist-icon"><Check size={12} /></span><span>Plan Terraform validation in a controlled workspace</span></div></div>
        {!run.approval.approved ? <><label className="acknowledge"><input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} /><span>I reviewed the inventory and understand the generated package needs Terraform CLI and cloud-state review before use.</span></label><button className="button button-dark" disabled={!acknowledged || busy} onClick={onApprove}><BadgeCheck size={15} />{busy ? 'Recording approval…' : 'Approve package download'}</button></> : <div className="approved-banner"><CheckCircle2 size={16} /><span>Approved for download. This does not apply infrastructure changes.</span></div>}
      </section>
      <section className="panel package-warning"><div className="warning-icon"><AlertTriangle size={18} /></div><div><div className="eyebrow">VALIDATION LIMIT</div><h3>Static review only</h3><p>GENESIS did not run <code>terraform validate</code>, connect to remote state, or execute a plan. Terraform can propose updates after import, even with destroy protection.</p><button className="inline-link" onClick={() => setSelectedFile('README.md')}>Read package instructions <ArrowRight size={13} /></button></div></section></div>
  </>
}

function FileIcon({ path }: { path: string }) {
  if (path.endsWith('.tf')) return <FileCode2 size={15} />
  if (path.endsWith('.json')) return <FileJson2 size={15} />
  return <FileText size={15} />
}

function GuardrailsPage({ run, findings, severityFilter, setSeverityFilter, onRun, busy }: { run: RunResult | null; findings: Finding[]; severityFilter: string; setSeverityFilter: (value: string) => void; onRun: () => void; busy: boolean }) {
  if (!run) return <EmptyPage icon={ShieldCheck} title="Guardrails are waiting for an inventory" copy="GENESIS checks imported metadata for public access, missing Terraform mappings, and unresolved references." action={<button className="button button-primary" onClick={onRun} disabled={busy}><Play size={15} />{busy ? 'Analyzing…' : 'Analyze sample inventory'}</button>} />
  return <>
    <PageHeading eyebrow="POLICY REVIEW" title="Guardrails" description="Findings come from supplied inventory fields. A missing finding does not prove the cloud configuration is safe." action={<button className="filter-control" onClick={() => setSeverityFilter(severityFilter === 'all' ? 'critical' : 'all')}><ListFilter size={15} />{severityFilter === 'all' ? 'All severities' : 'Critical only'}<ChevronDown size={13} /></button>} />
    <div className="guardrail-score-row"><div className="guardrail-score"><div className={run.summary.critical_findings ? 'score-alert' : 'score-good'}>{run.summary.critical_findings ? <AlertTriangle size={22} /> : <ShieldCheck size={22} />}</div><div><span>REVIEW STATUS</span><strong>{run.summary.critical_findings ? 'Action required' : run.summary.findings ? 'Review recommended' : 'No findings returned'}</strong></div></div><div className="score-separator" /><div className="score-number"><span>CRITICAL</span><strong>{run.findings.filter((item) => item.severity === 'critical').length}</strong></div><div className="score-number"><span>HIGH</span><strong>{run.findings.filter((item) => item.severity === 'high').length}</strong></div><div className="score-number"><span>MEDIUM</span><strong>{run.findings.filter((item) => item.severity === 'medium').length}</strong></div><div className="score-footnote">Rule checks only · not a compliance certification</div></div>
    <section className="panel findings-panel"><div className="panel-heading"><div><div className="eyebrow">INVENTORY SIGNALS</div><h2>{findings.length} findings to review</h2></div><span className="filter-count">{severityFilter === 'all' ? 'All' : 'Critical'} severities</span></div>
      {findings.length ? <div className="finding-list">{findings.map((finding) => <article className="finding-row" key={finding.id}><div className={`severity-icon severity-${finding.severity}`}><AlertTriangle size={16} /></div><div className="finding-copy"><div><strong>{finding.title}</strong><span className={`severity-tag severity-tag-${finding.severity}`}>{finding.severity}</span></div><small>{finding.resource}</small><p>{finding.detail}</p></div><button className="icon-button" title="Inspect in inventory"><ArrowRight size={16} /></button></article>)}</div> : <div className="findings-empty"><ShieldCheck size={25} /><strong>{severityFilter === 'all' ? 'No findings were returned from this inventory.' : 'No critical findings.'}</strong><span>GENESIS only checks fields available in the imported inventory.</span></div>}
    </section>
    <div className="guardrail-footnote"><LockKeyhole size={15} /><span>Credentials, private keys, and cloud state are never included in generated files. This prototype does not run Terraform or modify cloud resources.</span></div>
  </>
}

function CloudDialog({ provider, setProvider, region, setRegion, profile, setProfile, subscriptionId, setSubscriptionId, resourceGroup, setResourceGroup, onClose, onDiscoverAzure, onDiscoverAws, busy }: {
  provider: 'azure' | 'aws'; setProvider: (value: 'azure' | 'aws') => void
  region: string; setRegion: (value: string) => void; profile: string; setProfile: (value: string) => void
  subscriptionId: string; setSubscriptionId: (value: string) => void; resourceGroup: string; setResourceGroup: (value: string) => void
  onClose: () => void; onDiscoverAzure: () => void; onDiscoverAws: () => void; busy: boolean
}) {
  const isAzure = provider === 'azure'
  const onDiscover = isAzure ? onDiscoverAzure : onDiscoverAws
  return <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><section className="aws-dialog" role="dialog" aria-modal="true" aria-labelledby="cloud-dialog-title">
    <div className="dialog-head"><div className="dialog-icon"><CloudCog size={20} /></div><button className="icon-button" onClick={onClose} aria-label="Close dialog"><X size={17} /></button></div>
    <div className="eyebrow">READ-ONLY CLOUD CONNECTOR</div><h2 id="cloud-dialog-title">Connect a cloud inventory</h2>
    <div className="provider-tabs" role="tablist" aria-label="Cloud provider">
      <button role="tab" aria-selected={isAzure} className={isAzure ? 'provider-tab provider-tab-active' : 'provider-tab'} onClick={() => setProvider('azure')}>Microsoft Azure <span>PRIMARY</span></button>
      <button role="tab" aria-selected={!isAzure} className={!isAzure ? 'provider-tab provider-tab-active' : 'provider-tab'} onClick={() => setProvider('aws')}>AWS <span>OPTIONAL</span></button>
    </div>
    {isAzure ? <>
      <p>Uses Azure Resource Graph. Locally, the API uses your Azure CLI sign-in; in App Service, it uses the configured managed identity. No client secret is collected.</p>
      <label className="field-label">AZURE SUBSCRIPTION ID<input value={subscriptionId} onChange={(event) => setSubscriptionId(event.target.value)} placeholder="00000000-0000-0000-0000-000000000000" /></label>
      <label className="field-label">RESOURCE GROUP <span>OPTIONAL SCOPE FILTER</span><input value={resourceGroup} onChange={(event) => setResourceGroup(event.target.value)} placeholder="rg-example" /></label>
      <div className="dialog-safety"><ShieldCheck size={16} /><span>Read-only inventory query. Assign Reader on the subscription. The scan does not create, update, or delete Azure resources.</span></div>
    </> : <>
      <p>Uses the local AWS SDK credential chain and read APIs for EC2, load balancers, and RDS. GENESIS never accepts access keys here.</p>
      <label className="field-label">AWS REGION<input value={region} onChange={(event) => setRegion(event.target.value)} placeholder="us-east-1" /></label>
      <label className="field-label">AWS PROFILE <span>OPTIONAL</span><input value={profile} onChange={(event) => setProfile(event.target.value)} placeholder="default" /></label>
      <div className="dialog-safety"><ShieldCheck size={16} /><span>Only describe/list calls are made. No credentials are stored in this app.</span></div>
    </>}
    <div className="dialog-actions"><button className="button button-secondary" onClick={onClose}>Cancel</button><button className="button button-primary" onClick={onDiscover} disabled={busy || (isAzure && !subscriptionId.trim())}><Cloud size={15} />{busy ? 'Reading inventory…' : 'Run read-only scan'}</button></div>
  </section></div>
}

export default App
