import { useEffect, useMemo, useState } from 'react'
import Button from '@/components/ui/Button'
import {
  QueryResponse,
  QueryTrace,
  buildDocumentFileUrl,
  fetchDocumentFileBlob
} from '@/api/retriqs'
import { FileText, Link2, Loader2, Network, Puzzle, ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'

type EvidencePanelProps = {
  trace?: QueryTrace | null
  references?: QueryResponse['references']
  storageId?: number
  className?: string
}

const fileExt = (path: string) => {
  const idx = path.lastIndexOf('.')
  return idx >= 0 ? path.slice(idx + 1).toLowerCase() : ''
}

type SectionKey = 'documents' | 'chunks' | 'relations' | 'entities'

export default function EvidencePanel({
  trace,
  references,
  storageId,
  className
}: EvidencePanelProps) {
  const [activeSection, setActiveSection] = useState<SectionKey>('documents')
  const [selectedRefId, setSelectedRefId] = useState<string | null>(null)
  const [pdfBlobUrl, setPdfBlobUrl] = useState<string | null>(null)
  const [pdfLoading, setPdfLoading] = useState(false)
  const [pdfError, setPdfError] = useState<string | null>(null)
  const [resolvedSourceUrl, setResolvedSourceUrl] = useState<string | null>(null)
  const [docxPreviewHtml, setDocxPreviewHtml] = useState<string | null>(null)
  const [docxPreviewLoading, setDocxPreviewLoading] = useState(false)
  const [docxPreviewError, setDocxPreviewError] = useState<string | null>(null)

  const resolvedReferences = useMemo(() => {
    const traceRefs = trace?.data?.references || []
    const refs = traceRefs.length ? traceRefs : (references || [])
    return refs.filter((ref): ref is { reference_id: string; file_path: string; content?: string[] } =>
      Boolean(ref && ref.reference_id && ref.file_path)
    )
  }, [trace, references])

  const selectedReference = useMemo(() => {
    if (!resolvedReferences.length) return null
    if (!selectedRefId) return resolvedReferences[0]
    return resolvedReferences.find((ref) => ref.reference_id === selectedRefId) || resolvedReferences[0]
  }, [resolvedReferences, selectedRefId])
  const selectedReferenceExt = selectedReference ? fileExt(selectedReference.file_path) : ''

  const chunksByRef = useMemo(() => {
    const grouped = new Map<string, Array<{ chunk_id: string; content: string; file_path: string }>>()
    for (const chunk of trace?.data?.chunks || []) {
      const refId = chunk.reference_id || ''
      if (!refId) continue
      if (!grouped.has(refId)) grouped.set(refId, [])
      grouped.get(refId)!.push({
        chunk_id: chunk.chunk_id || '',
        content: chunk.content || '',
        file_path: chunk.file_path || ''
      })
    }
    return grouped
  }, [trace])

  useEffect(() => {
    if (!resolvedReferences.length) {
      setSelectedRefId(null)
      return
    }
    if (!selectedRefId || !resolvedReferences.some((ref) => ref.reference_id === selectedRefId)) {
      setSelectedRefId(resolvedReferences[0].reference_id)
    }
  }, [resolvedReferences, selectedRefId])

  useEffect(() => {
    let cancelled = false
    let createdUrl: string | null = null
    const loadPdf = async () => {
      if (!selectedReference) return
      const isPdf = fileExt(selectedReference.file_path) === 'pdf'
      setPdfError(null)
      setResolvedSourceUrl(null)
      setPdfBlobUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev)
        return null
      })
      if (!isPdf) return

      try {
        setPdfLoading(true)
        const { blob, contentType, sourceUrl } = await fetchDocumentFileBlob(
          selectedReference.file_path,
          storageId
        )
        if (cancelled) return
        setResolvedSourceUrl(sourceUrl)
        if (!contentType.toLowerCase().includes('pdf')) {
          const normalized = contentType.toLowerCase()
          if (normalized.includes('text/html')) {
            setPdfError(
              'Expected PDF, but server returned HTML. This usually means the backend route /documents/file is not loaded yet (restart API) or request was redirected to WebUI/login.'
            )
          } else {
            setPdfError(`Expected PDF but received: ${contentType || 'unknown content type'}`)
          }
          return
        }
        const url = URL.createObjectURL(blob)
        createdUrl = url
        setPdfBlobUrl(url)
      } catch (error) {
        if (cancelled) return
        const message = error instanceof Error ? error.message : ''
        if (message.includes('Expected binary document but received HTML response')) {
          setPdfError(
            'Expected PDF but received HTML. This is usually a proxy/backend routing mismatch. Ensure the document endpoint is reachable from the WebUI host.'
          )
        } else {
          setPdfError('Unable to load PDF preview')
        }
      } finally {
        if (!cancelled) setPdfLoading(false)
      }
    }

    loadPdf()

    return () => {
      cancelled = true
      if (createdUrl) URL.revokeObjectURL(createdUrl)
    }
  }, [selectedReference?.file_path, storageId])

  useEffect(() => {
    let cancelled = false
    const loadDocxPreview = async () => {
      setDocxPreviewHtml(null)
      setDocxPreviewError(null)
      if (!selectedReference || selectedReferenceExt !== 'docx') return

      try {
        setDocxPreviewLoading(true)
        const { blob, contentType } = await fetchDocumentFileBlob(selectedReference.file_path, storageId)
        if (cancelled) return
        if (contentType.toLowerCase().includes('text/html')) {
          setDocxPreviewError('Expected DOCX but received HTML response.')
          return
        }
        const arrayBuffer = await blob.arrayBuffer()
        const mammoth = await import('mammoth/mammoth.browser')
        const result = await mammoth.convertToHtml({ arrayBuffer })
        if (cancelled) return
        const wrappedHtml = (
          "<!doctype html><html><head><meta charset='utf-8' />"
          + "<meta name='viewport' content='width=device-width, initial-scale=1' />"
          + "<style>body{font-family:Arial,sans-serif;margin:16px;line-height:1.5;color:#111;}p{margin:0 0 10px 0;white-space:pre-wrap;}</style>"
          + '</head><body>'
          + (result.value || '<p><em>No textual content found in document.</em></p>')
          + '</body></html>'
        )
        setDocxPreviewHtml(wrappedHtml)
      } catch (error) {
        if (cancelled) return
        setDocxPreviewError('Unable to render DOCX preview')
      } finally {
        if (!cancelled) setDocxPreviewLoading(false)
      }
    }

    loadDocxPreview()
    return () => {
      cancelled = true
    }
  }, [selectedReference?.file_path, selectedReferenceExt, storageId])

  const entities = trace?.data?.entities || []
  const relationships = trace?.data?.relationships || []
  const metadata = trace?.metadata || {}
  const selectedChunks = selectedReference ? (chunksByRef.get(selectedReference.reference_id) || []) : []
  const selectedReferenceContent = selectedReference?.content || []
  const fallbackPreviewChunks = selectedChunks.length
    ? selectedChunks.map((chunk) => chunk.content).filter(Boolean)
    : selectedReferenceContent.filter(Boolean)

  return (
    <div className={cn('h-full flex flex-col border-l bg-card/50', className)}>
      <div className="px-3 py-2 border-b bg-muted/30">
        <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Evidence</h3>
      </div>

      <div className="px-2 py-2 border-b flex items-center gap-1 overflow-x-auto">
        {([
          ['documents', `Docs (${resolvedReferences.length})`, FileText],
          ['chunks', `Chunks (${trace?.data?.chunks?.length || 0})`, Puzzle],
          ['relations', `Relations (${relationships.length})`, Network],
          ['entities', `Entities (${entities.length})`, Link2]
        ] as const).map(([key, label, Icon]) => (
          <Button
            key={key}
            variant={activeSection === key ? 'default' : 'ghost'}
            size="sm"
            className="h-7 text-[11px] whitespace-nowrap"
            onClick={() => setActiveSection(key)}
          >
            <Icon className="h-3.5 w-3.5 mr-1" />
            {label}
          </Button>
        ))}
      </div>

      {activeSection === 'documents' && (
        <div className="flex-1 min-h-0 flex flex-col">
          <div className="p-2 border-b max-h-32 overflow-auto">
            {resolvedReferences.length === 0 ? (
              <div className="text-xs text-muted-foreground p-2">No source documents.</div>
            ) : (
              resolvedReferences.map((ref) => (
                <button
                  key={ref.reference_id}
                  type="button"
                  onClick={() => setSelectedRefId(ref.reference_id)}
                  className={cn(
                    'w-full text-left px-2 py-1.5 rounded text-xs border mb-1',
                    selectedReference?.reference_id === ref.reference_id
                      ? 'bg-primary/10 border-primary/30'
                      : 'bg-background border-border'
                  )}
                >
                  <div className="font-semibold">[{ref.reference_id}] {ref.file_path.split('/').pop() || ref.file_path}</div>
                  <div className="text-[10px] text-muted-foreground truncate">{ref.file_path}</div>
                </button>
              ))
            )}
          </div>

          <div className="flex-1 min-h-0">
            {!selectedReference ? (
              <div className="h-full flex items-center justify-center text-xs text-muted-foreground">Select a document.</div>
            ) : fileExt(selectedReference.file_path) !== 'pdf' ? (
              <div className="h-full min-h-0 p-3 text-xs space-y-2 overflow-auto">
                <div className="text-muted-foreground">
                  Native PDF preview is only available for `.pdf`. Showing text preview for `.{fileExt(selectedReference.file_path) || 'unknown'}` source.
                </div>
                <a
                  href={resolvedSourceUrl || buildDocumentFileUrl(selectedReference.file_path, storageId)}
                  target="_blank"
                  rel="noreferrer"
                  className="underline text-primary"
                >
                  Open source file
                </a>
                {selectedReferenceExt === 'docx' && (
                  <div className="border rounded bg-background min-h-72">
                    {docxPreviewLoading ? (
                      <div className="h-72 flex items-center justify-center text-xs text-muted-foreground">
                        <Loader2 className="h-4 w-4 animate-spin mr-2" />
                        Rendering DOCX preview...
                      </div>
                    ) : docxPreviewError ? (
                      <div className="h-72 p-3 text-xs text-destructive">{docxPreviewError}</div>
                    ) : docxPreviewHtml ? (
                      <iframe
                        title="DOCX Evidence Viewer"
                        srcDoc={docxPreviewHtml}
                        className="w-full h-72 border-0"
                        sandbox=""
                      />
                    ) : (
                      <div className="h-72 p-3 text-xs text-muted-foreground">No DOCX preview available.</div>
                    )}
                  </div>
                )}
                {fallbackPreviewChunks.length > 0 ? (
                  <div className="space-y-2 pt-2 border-t">
                    {fallbackPreviewChunks.map((content, index) => (
                      <details key={`preview-${index}`} className="border rounded bg-background">
                        <summary className="cursor-pointer list-none px-2 py-1.5 text-xs font-semibold flex items-center">
                          <ChevronDown className="h-3.5 w-3.5 mr-1" />
                          Text snippet {index + 1}
                        </summary>
                        <div className="px-2 pb-2 text-[11px] whitespace-pre-wrap text-foreground/90">
                          {content}
                        </div>
                      </details>
                    ))}
                  </div>
                ) : (
                  <div className="text-muted-foreground">No text snippet available for this source.</div>
                )}
              </div>
            ) : pdfLoading ? (
              <div className="h-full flex items-center justify-center text-xs text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin mr-2" />
                Loading PDF...
              </div>
            ) : pdfError ? (
              <div className="h-full p-3 text-xs space-y-2">
                <div className="text-destructive">{pdfError}</div>
                <a
                  href={resolvedSourceUrl || buildDocumentFileUrl(selectedReference.file_path, storageId)}
                  target="_blank"
                  rel="noreferrer"
                  className="underline text-primary"
                >
                  Open source file
                </a>
              </div>
            ) : pdfBlobUrl ? (
              <iframe title="PDF Evidence Viewer" src={pdfBlobUrl} className="w-full h-full border-0" />
            ) : (
              <div className="h-full flex items-center justify-center text-xs text-muted-foreground">No preview available.</div>
            )}
          </div>
        </div>
      )}

      {activeSection === 'chunks' && (
        <div className="flex-1 min-h-0 overflow-auto p-2 space-y-2">
          {selectedReference ? (
            <>
              <div className="text-[11px] font-semibold text-muted-foreground px-1">
                Reference [{selectedReference.reference_id}] chunks ({selectedChunks.length})
              </div>
              {selectedChunks.length === 0 ? (
                <div className="text-xs text-muted-foreground p-2">No chunks available for this reference.</div>
              ) : selectedChunks.map((chunk, index) => (
                <details key={`${chunk.chunk_id || index}`} className="border rounded bg-background">
                  <summary className="cursor-pointer list-none px-2 py-1.5 text-xs font-semibold flex items-center">
                    <ChevronDown className="h-3.5 w-3.5 mr-1" />
                    Chunk {index + 1}{chunk.chunk_id ? ` (${chunk.chunk_id.slice(0, 12)})` : ''}
                  </summary>
                  <div className="px-2 pb-2 text-[11px] whitespace-pre-wrap text-foreground/90">
                    {chunk.content}
                  </div>
                </details>
              ))}
            </>
          ) : (
            <div className="text-xs text-muted-foreground">No reference selected.</div>
          )}
        </div>
      )}

      {activeSection === 'relations' && (
        <div className="flex-1 min-h-0 overflow-auto p-2 space-y-2">
          {relationships.length === 0 ? (
            <div className="text-xs text-muted-foreground">No relations found.</div>
          ) : relationships.map((relation, index) => (
            <div key={`relation-${index}`} className="border rounded bg-background p-2 text-xs">
              <div className="font-semibold">{relation.src_id || '?'} → {relation.tgt_id || '?'}</div>
              {relation.description && <div className="text-[11px] mt-1 text-foreground/80">{relation.description}</div>}
              {relation.weight !== undefined && <div className="text-[10px] mt-1 text-muted-foreground">weight: {relation.weight}</div>}
              {relation.file_path && <div className="text-[10px] mt-1 text-muted-foreground truncate">{relation.file_path}</div>}
            </div>
          ))}
        </div>
      )}

      {activeSection === 'entities' && (
        <div className="flex-1 min-h-0 overflow-auto p-2 space-y-2">
          {entities.length === 0 ? (
            <div className="text-xs text-muted-foreground">No entities found.</div>
          ) : entities.map((entity, index) => (
            <div key={`entity-${index}`} className="border rounded bg-background p-2 text-xs">
              <div className="font-semibold">{entity.entity_name || entity.entity || 'Unknown entity'}</div>
              <div className="text-[10px] mt-1 text-muted-foreground">{entity.entity_type || 'UNKNOWN'}</div>
              {entity.description && <div className="text-[11px] mt-1 text-foreground/80">{entity.description}</div>}
              {entity.file_path && <div className="text-[10px] mt-1 text-muted-foreground truncate">{entity.file_path}</div>}
            </div>
          ))}
        </div>
      )}

      <div className="border-t p-2 text-[10px] text-muted-foreground overflow-auto max-h-20">
        <div className="font-semibold mb-1">Metadata</div>
        {Object.keys(metadata).length === 0 ? (
          <div>No trace metadata.</div>
        ) : (
          <pre className="whitespace-pre-wrap">{JSON.stringify(metadata, null, 2)}</pre>
        )}
      </div>
    </div>
  )
}
