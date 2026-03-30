import { describe, expect, test } from 'bun:test'

const installLocalStorageStub = () => {
  const store = new Map<string, string>()
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => {
        store.set(key, value)
      },
      removeItem: (key: string) => {
        store.delete(key)
      },
      clear: () => {
        store.clear()
      }
    }
  })
}

describe('archive import source handling', () => {
  test('detects absolute HTTP(S) URLs', async () => {
    installLocalStorageStub()
    const { isAbsoluteHttpUrl } = await import('@/api/retriqs')

    expect(isAbsoluteHttpUrl('https://example.com/archive.zip')).toBe(true)
    expect(isAbsoluteHttpUrl('http://example.com/archive.zip')).toBe(true)
    expect(isAbsoluteHttpUrl('/assets/archive.zip')).toBe(false)
  })

  test('appends source_url for absolute HTTP(S) archive URL', async () => {
    installLocalStorageStub()
    const { appendArchiveImportSource } = await import('@/api/retriqs')
    const formData = new FormData()
    const archiveUrl =
      'https://d2nx8b3pezm5w7.cloudfront.net/public/graphs/LangChain_Storage-storage-export.zip'

    await appendArchiveImportSource(formData, archiveUrl, 'ignored.zip')

    expect(formData.get('source_url')).toBe(archiveUrl)
    expect(formData.get('file')).toBe(null)
  })

  test('appends file when provided with a File object', async () => {
    installLocalStorageStub()
    const { appendArchiveImportSource } = await import('@/api/retriqs')
    const formData = new FormData()
    const archiveFile = new File(['test'], 'archive.zip', { type: 'application/zip' })

    await appendArchiveImportSource(formData, archiveFile, 'ignored.zip')

    expect(formData.get('source_url')).toBe(null)
    const file = formData.get('file')
    expect(file).toBeInstanceOf(File)
    expect((file as File).name).toBe('archive.zip')
  })

  test('builds import form data with embedding_import_mode', async () => {
    installLocalStorageStub()
    const { buildImportStorageArchiveFormData } = await import('@/api/retriqs')
    const archiveFile = new File(['test'], 'archive.zip', { type: 'application/zip' })

    const formData = await buildImportStorageArchiveFormData(
      'Imported Pack',
      archiveFile,
      'local_reembed'
    )

    expect(formData.get('name')).toBe('Imported Pack')
    expect(formData.get('embedding_import_mode')).toBe('local_reembed')
    const file = formData.get('file')
    expect(file).toBeInstanceOf(File)
    expect((file as File).name).toBe('archive.zip')
  })

  test('defaults embedding_import_mode to preindexed', async () => {
    installLocalStorageStub()
    const { buildImportStorageArchiveFormData } = await import('@/api/retriqs')
    const archiveFile = new File(['test'], 'archive.zip', { type: 'application/zip' })

    const formData = await buildImportStorageArchiveFormData('Imported Pack', archiveFile)

    expect(formData.get('embedding_import_mode')).toBe('preindexed')
  })
})
