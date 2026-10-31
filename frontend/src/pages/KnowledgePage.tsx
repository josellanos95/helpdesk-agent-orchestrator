import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Plus, Search, Trash2 } from 'lucide-react'
import { Empty, ErrorBox, Loading } from '../components/StateViews'
import { useI18n } from '../i18n'
import { request } from '../lib/api'
import { tenantKey, useArticle, useArticles } from '../lib/queries'
import { useRequiredSession } from '../lib/session'
import { ago, shortDate } from '../lib/time'
import type { Article, Hit } from '../lib/types'

function SearchTester() {
  const { t } = useI18n()
  const { tenantId } = useRequiredSession()
  const [query, setQuery] = useState('')
  const search = useMutation({
    mutationFn: (text: string) =>
      request<Hit[]>('/kb/search?detail=short', { method: 'POST', tenantId, body: { query: text, top_k: 4 } }),
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (query.trim().length >= 3) search.mutate(query.trim())
  }

  return (
    <section aria-labelledby="kb-test">
      <h2 className="section-title" id="kb-test">{t('kb.testTitle')}</h2>
      <p className="muted small">{t('kb.testHint')}</p>
      <form className="mt-3 flex gap-2" onSubmit={submit}>
        <label htmlFor="kb-query" className="sr-only">{t('kb.testTitle')}</label>
        <input
          id="kb-query"
          className="field"
          type="search"
          enterKeyHint="search"
          placeholder={t('kb.testPlaceholder')}
          value={query}
          minLength={3}
          maxLength={300}
          onChange={(event) => setQuery(event.target.value)}
        />
        <button type="submit" className="btn" disabled={search.isPending || query.trim().length < 3}>
          <Search size={18} aria-hidden /> <span>{t('kb.search')}</span>
        </button>
      </form>

      {search.isPending && <Loading rows={2} />}
      {search.isError && (
        <div className="mt-3">
          <ErrorBox error={search.error} />
        </div>
      )}
      {search.isSuccess &&
        (search.data.length === 0 ? (
          <p className="notice mt-3">{t('kb.noHits')}</p>
        ) : (
          <ul className="ruled banded mt-3" aria-live="polite">
            {search.data.map((hit, i) => (
              <li key={`${hit.article_id}-${i}`}>
                <Link to={`/knowledge/${hit.article_id}`} className="item">
                  <span className="item-head">
                    <span className="item-title">{hit.article}</span>
                    {hit.similarity !== null && (
                      <span className="sim mono num">
                        <span className="bar" aria-hidden style={{ '--s': hit.similarity } as React.CSSProperties}>
                          <i />
                        </span>
                        {t('kb.byMeaning', { pct: Math.round(hit.similarity * 100) })}
                      </span>
                    )}
                    {hit.keyword_match && <span className="stamp stamp-plain">{t('kb.byWords')}</span>}
                  </span>
                  <span className="item-sub block">{hit.passage}</span>
                </Link>
              </li>
            ))}
          </ul>
        ))}
    </section>
  )
}

export function KnowledgeListPage() {
  const { t, locale } = useI18n()
  const { tenantId, role } = useRequiredSession()
  const articles = useArticles(tenantId)

  return (
    <div className="page">
      <div className="spread">
        <h1 className="page-title">{t('kb.title')}</h1>
        {role === 'support' && (
          <Link to="/knowledge/new" className="btn btn-sm btn-primary">
            <Plus size={18} aria-hidden /> {t('kb.new')}
          </Link>
        )}
      </div>

      <SearchTester />

      <h2 className="section-title">{t('kb.articles')}</h2>
      {articles.isPending && <Loading />}
      {articles.isError && <ErrorBox error={articles.error} onRetry={() => articles.refetch()} />}
      {articles.isSuccess &&
        (articles.data.length === 0 ? (
          <Empty>{t('kb.empty')}</Empty>
        ) : (
          <ul className="ruled banded">
            {articles.data.map((article) => (
              <li key={article.id}>
                <Link to={`/knowledge/${article.id}`} className="item">
                  <span className="item-title">{article.title}</span>
                  <span className="item-meta block">
                    {t(article.passages === 1 ? 'kb.passage' : 'kb.passages', { n: article.passages })} · {t('kb.updated', { when: ago(article.updated_at, locale) })}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        ))}
    </div>
  )
}

function Editor({ article }: { article?: Article }) {
  const { t } = useI18n()
  const { tenantId, personId } = useRequiredSession()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [title, setTitle] = useState(article?.title ?? '')
  const [body, setBody] = useState(article?.body ?? '')
  const [confirm, setConfirm] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  const refresh = () => queryClient.invalidateQueries({ queryKey: tenantKey(tenantId) })
  const save = useMutation({
    mutationFn: async () => {
      const payload = { title: title.trim(), body: body.trim(), author_id: personId }
      if (article) {
        const result = await request<{ article: Article; changed: boolean }>(`/kb/articles/${article.id}`, {
          method: 'PUT',
          tenantId,
          body: payload,
        })
        return { id: result.article.id, changed: result.changed }
      }
      const created = await request<Article>('/kb/articles', { method: 'POST', tenantId, body: payload })
      return { id: created.id, changed: true }
    },
    onSuccess: async (result) => {
      await refresh()
      if (!article) navigate(`/knowledge/${result.id}`, { replace: true })
      else setNotice(t(result.changed ? 'kb.saved' : 'kb.unchanged'))
    },
  })
  const remove = useMutation({
    mutationFn: () => request(`/kb/articles/${article!.id}?actor_id=${personId}`, { method: 'DELETE', tenantId }),
    onSuccess: async () => {
      await refresh()
      navigate('/knowledge', { replace: true })
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setNotice(null)
    save.mutate()
  }

  return (
    <form onSubmit={submit} className="mt-4 max-w-2xl space-y-4">
      <div>
        <label className="label" htmlFor="kb-title">{t('kb.titleField')}</label>
        <input id="kb-title" className="field" required minLength={3} maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} />
      </div>
      <div>
        <label className="label" htmlFor="kb-body">{t('kb.bodyField')}</label>
        <textarea id="kb-body" className="field" required minLength={20} rows={14} value={body} onChange={(e) => setBody(e.target.value)} />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button type="submit" className="btn btn-primary" disabled={save.isPending}>
          {article ? t('kb.save') : t('kb.create')}
        </button>
        {article && !confirm && (
          <button type="button" className="btn btn-danger" onClick={() => setConfirm(true)}>
            <Trash2 size={18} aria-hidden /> {t('kb.delete')}
          </button>
        )}
      </div>

      {confirm && (
        <div className="notice error-box" role="alertdialog" aria-label={t('kb.confirmDelete')}>
          <div className="flex-1">
            <p>{t('kb.confirmDelete')}</p>
            <div className="mt-2 flex gap-2">
              <button type="button" className="btn btn-sm btn-danger" disabled={remove.isPending} onClick={() => remove.mutate()}>
                {t('kb.confirmYes')}
              </button>
              <button type="button" className="btn btn-sm" onClick={() => setConfirm(false)}>
                {t('common.cancel')}
              </button>
            </div>
          </div>
        </div>
      )}

      {notice && <p className="notice" role="status">{notice}</p>}
      {save.isError && <ErrorBox error={save.error} />}
      {remove.isError && <ErrorBox error={remove.error} />}
    </form>
  )
}

export function ArticlePage({ create }: { create?: boolean }) {
  const { id } = useParams()
  const { t, locale } = useI18n()
  const { tenantId, role } = useRequiredSession()
  const article = useArticle(tenantId, create ? undefined : id)
  const editable = role === 'support'

  return (
    <div className="page">
      <Link to="/knowledge" className="btn btn-sm btn-quiet -ml-3">
        <ArrowLeft size={18} aria-hidden /> {t('kb.back')}
      </Link>

      {create && editable && (
        <>
          <h1 className="page-title mt-2">{t('kb.new')}</h1>
          <Editor />
        </>
      )}
      {create && !editable && <p className="notice mt-4">{t('kb.readOnly')}</p>}

      {!create && article.isPending && <Loading />}
      {!create && article.isError && <ErrorBox error={article.error} onRetry={() => article.refetch()} />}
      {!create && article.data && (
        <>
          <h1 className="page-title mt-2">{article.data.title}</h1>
          <p className="item-meta mt-1">
            {t(article.data.passages === 1 ? 'kb.passage' : 'kb.passages', { n: article.data.passages })} · {t('kb.updated', { when: shortDate(article.data.updated_at, locale) })}
          </p>
          {editable ? (
            <Editor key={article.data.updated_at} article={article.data} />
          ) : (
            <>
              <p className="notice mt-4">{t('kb.readOnly')}</p>
              <div className="prose mt-4 max-w-[68ch]" style={{ whiteSpace: 'pre-wrap' }}>
                {article.data.body}
              </div>
            </>
          )}
        </>
      )}
    </div>
  )
}
