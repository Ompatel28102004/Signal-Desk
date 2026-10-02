import { useEffect, useState } from 'react';

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';
const sourceNames = ['hacker_news', 'rss', 'youtube'];
const sentiments = ['Positive', 'Neutral', 'Negative'];
const topics = ['Product', 'Pricing', 'Customer Service', 'Quality', 'Competitors', 'Complaints', 'Features', 'Other'];
const sourceLabels = { hacker_news: 'Hacker News', rss: 'RSS feeds', youtube: 'YouTube' };
const initialFilters = { source: '', sentiment: '', topic: '', from: '', to: '', search: '' };

async function apiRequest(path, options = {}) {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options.headers },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (${response.status})`);
  return body;
}

export default function App() {
  const [keyword, setKeyword] = useState('');
  const [selectedSources, setSelectedSources] = useState(['hacker_news']);
  const [sourceStatuses, setSourceStatuses] = useState([]);
  const [filters, setFilters] = useState(initialFilters);
  const [savedMentions, setSavedMentions] = useState([]);
  const [previewMentions, setPreviewMentions] = useState(null);
  const [pagination, setPagination] = useState({ page: 1, page_size: 20, total: 0, pages: 0 });
  const [analytics, setAnalytics] = useState(null);
  const [insights, setInsights] = useState(null);
  const [loadingSources, setLoadingSources] = useState(true);
  const [loadingData, setLoadingData] = useState(true);
  const [searching, setSearching] = useState(false);
  const [collecting, setCollecting] = useState(false);
  const [apiError, setApiError] = useState('');
  const [actionMessage, setActionMessage] = useState('');

  async function loadSources() {
    setLoadingSources(true);
    try {
      const response = await apiRequest('/api/sources');
      setSourceStatuses(response.sources);
      setSelectedSources(response.sources.filter((source) => source.enabled).map((source) => source.name));
    } catch {
      setSourceStatuses(sourceNames.map((name) => ({ name, enabled: false, status: 'unavailable' })));
    } finally {
      setLoadingSources(false);
    }
  }

  async function loadStoredData(page = 1, currentFilters = filters, currentKeyword = keyword.trim()) {
    setLoadingData(true);
    setApiError('');
    const params = new URLSearchParams({ page: String(page), page_size: '20' });
    if (currentKeyword) params.set('keyword', currentKeyword);
    if (currentFilters.source) params.set('source', currentFilters.source);
    if (currentFilters.sentiment) params.set('sentiment', currentFilters.sentiment);
    if (currentFilters.topic) params.set('topic', currentFilters.topic);
    if (currentFilters.search.trim()) params.set('search', currentFilters.search.trim());
    if (currentFilters.from) params.set('published_after', new Date(`${currentFilters.from}T00:00:00Z`).toISOString());
    if (currentFilters.to) params.set('published_before', new Date(`${currentFilters.to}T23:59:59Z`).toISOString());
    const analyticsParams = new URLSearchParams({ days: '30' });
    if (currentKeyword) analyticsParams.set('keyword', currentKeyword);
    const [mentionsResult, analyticsResult] = await Promise.allSettled([
      apiRequest(`/api/mentions?${params.toString()}`),
      apiRequest(`/api/analytics?${analyticsParams.toString()}`),
    ]);
    if (mentionsResult.status === 'fulfilled') {
      setSavedMentions(mentionsResult.value.items);
      setPagination(mentionsResult.value.pagination);
    } else {
      setApiError(`Saved mentions are unavailable: ${mentionsResult.reason.message}`);
    }
    if (analyticsResult.status === 'fulfilled') setAnalytics(analyticsResult.value);
    else if (mentionsResult.status === 'fulfilled') setApiError(`Analytics are unavailable: ${analyticsResult.reason.message}`);
    setLoadingData(false);
  }

  useEffect(() => {
    loadSources();
    loadStoredData(1, initialFilters, '');
  }, []);

  async function handleSearch(event) {
    event.preventDefault();
    const query = keyword.trim();
    if (!query) {
      setActionMessage('Enter a keyword to search.');
      return;
    }
    setSearching(true);
    setActionMessage('');
    setApiError('');
    setInsights(null);
    try {
      const response = await apiRequest('/api/search', {
        method: 'POST',
        body: JSON.stringify({ keyword: query, sources: selectedSources.length ? selectedSources : undefined, limit: 50 }),
      });
      setPreviewMentions(response.mentions);
      setPagination({ page: 1, page_size: 50, total: response.total, pages: 1 });
      if (response.partial_success) {
        const unavailable = [
          ...response.disabled_sources,
          ...response.source_failures.map((failure) => sourceLabels[failure.source] ?? failure.source),
        ];
        setActionMessage(`Partial results. Unavailable: ${unavailable.join(', ') || 'some sources'}.`);
      } else setActionMessage(`Found ${response.total} relevant mentions.`);
      apiRequest(`/api/insights?keyword=${encodeURIComponent(query)}`)
        .then(setInsights)
        .catch(() => {});
    } catch (error) {
      setApiError(`Search failed: ${error.message}`);
    } finally {
      setSearching(false);
    }
  }

  async function handleCollect() {
    const query = keyword.trim();
    if (!query) {
      setActionMessage('Enter a keyword before collecting.');
      return;
    }
    setCollecting(true);
    setApiError('');
    setActionMessage('');
    try {
      const response = await apiRequest('/api/collect', {
        method: 'POST',
        body: JSON.stringify({ keyword: query, limit: 50 }),
      });
      setPreviewMentions(response.mentions);
      setInsights(response.insights);
      setPagination({ page: 1, page_size: 50, total: response.collected, pages: 1 });
      setActionMessage(`Collected ${response.collected}; saved ${response.inserted} new mentions.`);
      await loadStoredData(1, filters, query);
    } catch (error) {
      setApiError(`Collection failed: ${error.message}`);
    } finally {
      setCollecting(false);
    }
  }

  function handleFilterSubmit(event) {
    event.preventDefault();
    if (previewMentions === null) loadStoredData(1, filters, keyword.trim());
  }

  function changePage(nextPage) {
    if (previewMentions === null) loadStoredData(nextPage, filters, keyword.trim());
  }

  function updateFilter(name, value) {
    setFilters((current) => ({ ...current, [name]: value }));
  }

  function toggleSource(name) {
    setSelectedSources((current) => current.includes(name)
      ? current.filter((item) => item !== name)
      : [...current, name]);
  }

  const visibleMentions = previewMentions === null ? savedMentions : filterPreviewMentions(previewMentions, filters);
  const overview = buildOverview(previewMentions === null ? analytics : null, previewMentions);

  return (
    <main className="dashboard-shell">
      <header className="app-header">
        <a className="brand" href="#top" aria-label="Signal Desk home">
          <span className="brand-mark" aria-hidden="true">S</span>
          <span className="brand-copy"><strong>Signal Desk</strong><small>Social listening</small></span>
        </a>
        <div className="header-meta"><span className="header-pulse" aria-hidden="true" />Workspace overview</div>
      </header>

      <section className="query-panel" aria-labelledby="query-title" id="top">
        <div className="query-copy">
          <p className="eyebrow">MONITORING WORKSPACE</p>
          <h1 id="query-title">Listen for what matters.</h1>
          <p>Search public conversations, then collect and classify the useful ones.</p>
        </div>
        <form className="query-form" onSubmit={handleSearch}>
          <label className="sr-only" htmlFor="keyword-query">Keyword</label>
          <input id="keyword-query" maxLength={255} onChange={(event) => setKeyword(event.target.value)} placeholder="Try: product launch, customer support" value={keyword} />
          <button className="button button-secondary" disabled={searching || collecting} type="submit">{searching ? <Spinner /> : null}Search</button>
          <button className="button button-primary" disabled={searching || collecting} onClick={handleCollect} type="button">{collecting ? <Spinner /> : null}Collect</button>
        </form>
        <div className="source-pickers" aria-label="Search sources">
          {sourceStatuses.map((source) => (
            <label className="source-check" key={source.name} title={source.detail}>
              <input checked={selectedSources.includes(source.name)} disabled={!source.enabled} onChange={() => toggleSource(source.name)} type="checkbox" />
              {sourceLabels[source.name] ?? source.name}
            </label>
          ))}
          {loadingSources ? <span className="quiet-text">Checking sources…</span> : null}
        </div>
      </section>

      {apiError ? (
        <div className="alert alert-error" role="alert">
          <strong>API issue</strong><span>{apiError}</span>
          <button className="text-button" onClick={() => loadStoredData(1)} type="button">Retry saved data</button>
        </div>
      ) : null}
      {actionMessage ? <p className="action-message" role="status">{actionMessage}</p> : null}

      <section className="overview-section" aria-labelledby="overview-heading">
        <div className="section-heading">
          <div><p className="eyebrow">CURRENT PICTURE</p><h2 id="overview-heading">Mention overview</h2></div>
          <span className="range-note">{previewMentions === null ? 'Last 30 days' : 'Search results'}</span>
        </div>
        <div className="metric-grid">
          <MetricCard label="Total mentions" value={overview.total} loading={loadingData && !analytics} tone="ink" />
          <MetricCard label="Positive" value={overview.sentiment.Positive} tone="positive" />
          <MetricCard label="Neutral" value={overview.sentiment.Neutral} tone="neutral" />
          <MetricCard label="Negative" value={overview.sentiment.Negative} tone="negative" />
        </div>
      </section>

      <section className="chart-grid" aria-label="Mention charts">
        <section className="panel chart-panel" aria-labelledby="sentiment-heading">
          <PanelHeading eyebrow="TONE" title="Sentiment distribution" id="sentiment-heading" />
          <SentimentChart distribution={overview.sentiment} total={overview.total} />
        </section>
        <section className="panel chart-panel" aria-labelledby="topics-heading">
          <PanelHeading eyebrow="SUBJECTS" title="Topic distribution" id="topics-heading" />
          <TopicChart topics={overview.topics} />
        </section>
        <section className="panel time-panel" aria-labelledby="timeline-heading">
          <PanelHeading eyebrow="VOLUME" title="Mentions over time" id="timeline-heading" />
          <TimeSeriesChart points={overview.timeSeries} />
        </section>
      </section>

      <section className="workspace-grid">
        <section className="panel mentions-panel" aria-labelledby="mentions-heading">
          <div className="section-heading table-heading">
            <div><p className="eyebrow">CONVERSATIONS</p><h2 id="mentions-heading">Mentions</h2></div>
            {previewMentions !== null ? (
              <button className="text-button" onClick={() => { setPreviewMentions(null); loadStoredData(1, filters, keyword.trim()); }} type="button">View saved mentions</button>
            ) : <span className="range-note">{pagination.total.toLocaleString()} records</span>}
          </div>
          <form className="filter-bar" onSubmit={handleFilterSubmit}>
            <label><span>Source</span><select onChange={(event) => updateFilter('source', event.target.value)} value={filters.source}><option value="">All sources</option>{sourceNames.map((name) => <option key={name} value={name}>{sourceLabels[name]}</option>)}</select></label>
            <label><span>Sentiment</span><select onChange={(event) => updateFilter('sentiment', event.target.value)} value={filters.sentiment}><option value="">All sentiment</option>{sentiments.map((sentiment) => <option key={sentiment}>{sentiment}</option>)}</select></label>
            <label><span>Topic</span><select onChange={(event) => updateFilter('topic', event.target.value)} value={filters.topic}><option value="">All topics</option>{topics.map((topic) => <option key={topic}>{topic}</option>)}</select></label>
            <label><span>From</span><input onChange={(event) => updateFilter('from', event.target.value)} type="date" value={filters.from} /></label>
            <label><span>To</span><input onChange={(event) => updateFilter('to', event.target.value)} type="date" value={filters.to} /></label>
            <label className="filter-search"><span>Text search</span><input onChange={(event) => updateFilter('search', event.target.value)} placeholder="Search titles and text" type="search" value={filters.search} /></label>
            <button className="button button-small" type="submit">Apply</button>
          </form>

          {loadingData && previewMentions === null ? <div className="table-loading"><Spinner />Loading mentions…</div> : visibleMentions.length ? (
            <>
              <div className="table-wrap"><table>
                <thead><tr><th>Source</th><th>Date</th><th>Title / text</th><th>Topic</th><th>Sentiment</th><th><span className="sr-only">Link</span></th></tr></thead>
                <tbody>{visibleMentions.map((mention) => <MentionRow key={`${mention.source}:${mention.external_id}`} mention={mention} />)}</tbody>
              </table></div>
              {previewMentions === null ? <div className="pagination-controls"><span>Page {pagination.page} of {Math.max(pagination.pages, 1)}</span><div><button className="button button-small" disabled={pagination.page <= 1} onClick={() => changePage(pagination.page - 1)} type="button">Previous</button><button className="button button-small" disabled={pagination.page >= pagination.pages} onClick={() => changePage(pagination.page + 1)} type="button">Next</button></div></div> : null}
            </>
          ) : <EmptyState title={previewMentions === null && apiError ? 'Saved mentions unavailable' : 'No mentions yet'}>{previewMentions === null && apiError ? 'Search can still retrieve fresh public results; collecting requires a configured database.' : 'Try a keyword search or adjust your filters.'}</EmptyState>}
        </section>

        <aside className="side-column">
          <section className="panel insights-panel" aria-labelledby="insights-heading">
            <PanelHeading eyebrow="AI INSIGHTS" title="Discussion summary" id="insights-heading" />
            {insights ? <InsightsContent insights={insights} /> : <EmptyState title="No summary available">Run collection to generate an insight summary from the aggregate conversation.</EmptyState>}
          </section>
          <section className="panel source-panel" aria-labelledby="sources-heading">
            <PanelHeading eyebrow="CONNECTORS" title="Source status" id="sources-heading" />
            <div className="source-status-list">{sourceNames.map((name) => {
              const source = sourceStatuses.find((item) => item.name === name);
              const available = Boolean(source?.enabled);
              return <div className="source-status-row" key={name} title={source?.detail}><span className={`source-dot ${available ? 'is-online' : 'is-offline'}`} aria-hidden="true" /><span>{sourceLabels[name]}</span><strong className={available ? 'status-online' : 'status-offline'}>{loadingSources ? 'Checking' : available ? 'Available' : 'Unavailable'}</strong></div>;
            })}</div>
          </section>
        </aside>
      </section>

      <footer className="app-footer"><span>Signal Desk</span><span>Public-source monitoring · {apiBaseUrl.replace(/^https?:\/\//, '')}</span></footer>
    </main>
  );
}

function MetricCard({ label, value, tone, loading = false }) {
  return <article className={`metric-card metric-${tone}`}><span>{label}</span><strong>{loading ? <span className="metric-placeholder">—</span> : Number(value || 0).toLocaleString()}</strong></article>;
}

function PanelHeading({ eyebrow, title, id }) {
  return <div className="panel-title"><p className="eyebrow">{eyebrow}</p><h2 id={id}>{title}</h2></div>;
}

function SentimentChart({ distribution, total }) {
  const colors = { Positive: 'var(--positive)', Neutral: 'var(--neutral)', Negative: 'var(--negative)' };
  return <div className="sentiment-chart"><div className="sentiment-track" aria-label={`Sentiment distribution across ${total} mentions`}>{sentiments.map((sentiment) => <span key={sentiment} style={{ width: `${total ? ((distribution[sentiment] || 0) / total) * 100 : 0}%`, background: colors[sentiment] }} />)}</div><div className="chart-legend">{sentiments.map((sentiment) => <div className="legend-item" key={sentiment}><span className="legend-swatch" style={{ background: colors[sentiment] }} /><span>{sentiment}</span><strong>{distribution[sentiment] || 0}</strong></div>)}</div>{!total ? <p className="chart-empty">No sentiment data for this period.</p> : null}</div>;
}

function TopicChart({ topics: topicCounts }) {
  const entries = topicCounts.slice(0, 6);
  const max = Math.max(...entries.map((item) => item.count), 1);
  if (!entries.length) return <p className="chart-empty">No topic data for this period.</p>;
  return <div className="topic-chart">{entries.map((item) => <div className="topic-row" key={item.name}><span>{item.name}</span><div className="topic-track"><span style={{ width: `${(item.count / max) * 100}%` }} /></div><strong>{item.count}</strong></div>)}</div>;
}

function TimeSeriesChart({ points }) {
  if (!points.length) return <p className="chart-empty">No activity recorded in this period.</p>;
  const width = 520;
  const height = 144;
  const padding = { top: 12, right: 12, bottom: 24, left: 28 };
  const max = Math.max(...points.map((point) => point.count), 1);
  const coordinates = points.map((point, index) => ({
    x: padding.left + (points.length === 1 ? 0 : index * ((width - padding.left - padding.right) / (points.length - 1))),
    y: padding.top + (height - padding.top - padding.bottom) * (1 - point.count / max),
  }));
  const line = coordinates.map((point, index) => `${index ? 'L' : 'M'} ${point.x} ${point.y}`).join(' ');
  return <div className="time-chart"><svg aria-label="Mentions by day" className="chart-svg" role="img" viewBox={`0 0 ${width} ${height}`}>{[0, 1, 2].map((index) => { const y = padding.top + index * ((height - padding.top - padding.bottom) / 2); return <line className="grid-line" key={index} x1={padding.left} x2={width - padding.right} y1={y} y2={y} />; })}<path className="time-line" d={line} />{coordinates.map((point, index) => <circle className="time-dot" cx={point.x} cy={point.y} key={index} r="3.5" />)}</svg><div className="time-labels"><span>{formatDate(points[0].bucket)}</span><span>{formatDate(points[points.length - 1].bucket)}</span></div></div>;
}

function MentionRow({ mention }) {
  const title = mention.title?.trim();
  const text = mention.content?.trim();
  const url = safeHttpUrl(mention.url);
  return <tr><td><span className="source-label">{sourceLabels[mention.source] ?? mention.source}</span></td><td className="date-cell">{formatDate(mention.published_at ?? mention.collected_at)}</td><td className="mention-text-cell"><strong>{title || 'Untitled mention'}</strong>{text && text !== title ? <span>{truncate(text, 160)}</span> : null}</td><td>{mention.topic ? <span className="topic-pill">{mention.topic}</span> : <span className="muted-cell">—</span>}</td><td>{mention.sentiment ? <SentimentPill sentiment={mention.sentiment} /> : <span className="muted-cell">—</span>}</td><td>{url ? <a className="open-link" href={url} rel="noopener noreferrer" target="_blank" aria-label={`Open original mention: ${title || mention.external_id}`}>Open</a> : <span className="muted-cell">—</span>}</td></tr>;
}

function SentimentPill({ sentiment }) {
  return <span className={`sentiment-pill pill-${sentiment.toLowerCase()}`}>{sentiment}</span>;
}

function InsightsContent({ insights }) {
  const summary = insights.insights ?? insights;
  const sections = [['Positive themes', summary.positive_themes], ['Negative themes', summary.negative_themes], ['Common complaints', summary.common_complaints], ['Feature requests & mentions', summary.frequently_discussed_features], ['Opportunities', summary.opportunities]];
  return <div className="insight-content"><p className="insight-summary">{summary.overall_discussion}</p>{sections.map(([title, items]) => <div className="insight-section" key={title}><h3>{title}</h3>{items?.length ? <ul>{items.map((item) => <li key={item}>{item}</li>)}</ul> : <p className="quiet-text">No recurring signals</p>}</div>)}<span className="provider-note">Summary via {summary.provider ?? 'AI insights'}</span></div>;
}

function EmptyState({ title, children }) {
  return <div className="empty-state"><strong>{title}</strong><p>{children}</p></div>;
}

function Spinner() {
  return <span className="spinner" aria-hidden="true" />;
}

function buildOverview(analyticsData, preview) {
  if (preview !== null) {
    const sentiment = Object.fromEntries(sentiments.map((key) => [key, 0]));
    const topicCounts = new Map();
    const days = new Map();
    preview.forEach((mention) => {
      if (sentiment[mention.sentiment] !== undefined) sentiment[mention.sentiment] += 1;
      const topic = mention.topic || 'Other';
      topicCounts.set(topic, (topicCounts.get(topic) || 0) + 1);
      const date = mention.published_at || mention.collected_at;
      if (date) { const day = new Date(date).toISOString().slice(0, 10); days.set(day, (days.get(day) || 0) + 1); }
    });
    return { total: preview.length, sentiment, topics: [...topicCounts].map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count), timeSeries: [...days].sort(([a], [b]) => a.localeCompare(b)).map(([bucket, count]) => ({ bucket, count })) };
  }
  return { total: analyticsData?.total ?? 0, sentiment: Object.fromEntries(sentiments.map((key) => [key, analyticsData?.sentiment_distribution?.[key] ?? 0])), topics: (analyticsData?.topics ?? []).map((item) => ({ name: item.name, count: item.count })), timeSeries: analyticsData?.time_series ?? [] };
}

function filterPreviewMentions(mentions, filters) {
  const query = filters.search.trim().toLocaleLowerCase();
  return mentions.filter((mention) => {
    if (filters.source && mention.source !== filters.source) return false;
    if (filters.sentiment && mention.sentiment !== filters.sentiment) return false;
    if (filters.topic && mention.topic !== filters.topic) return false;
    const date = mention.published_at || mention.collected_at;
    if (filters.from && (!date || new Date(date) < new Date(`${filters.from}T00:00:00Z`))) return false;
    if (filters.to && (!date || new Date(date) > new Date(`${filters.to}T23:59:59Z`))) return false;
    if (query && !`${mention.title ?? ''} ${mention.content ?? ''}`.toLocaleLowerCase().includes(query)) return false;
    return true;
  });
}

function safeHttpUrl(value) {
  if (!value) return null;
  try { const url = new URL(value); return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null; }
  catch { return null; }
}

function formatDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? '—' : new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' }).format(date);
}

function truncate(value, limit) {
  return value.length > limit ? `${value.slice(0, limit).trimEnd()}…` : value;
}