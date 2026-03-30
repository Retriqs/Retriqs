import { describe, expect, test } from 'bun:test'

import {
  DEFAULT_LANGCHAIN_MARKETPLACE_ARCHIVE_URL,
  LANGCHAIN_MARKETPLACE_ARCHIVE_URL
} from '@/features/marketplaceConfig'

describe('marketplace config', () => {
  test('uses env override or falls back to default CloudFront URL', () => {
    expect(DEFAULT_LANGCHAIN_MARKETPLACE_ARCHIVE_URL).toBe(
      'https://d2nx8b3pezm5w7.cloudfront.net/public/graphs/LangChain_Storage-storage-export.zip'
    )

    expect(LANGCHAIN_MARKETPLACE_ARCHIVE_URL).toBe(
      import.meta.env.VITE_MARKETPLACE_LANGCHAIN_ARCHIVE_URL ||
        DEFAULT_LANGCHAIN_MARKETPLACE_ARCHIVE_URL
    )
  })
})
