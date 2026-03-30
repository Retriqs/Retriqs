import { describe, expect, test } from 'bun:test'

import {
  getTenantCreateActionLabel,
  isStorageArchiveFile
} from '@/components/tenantCreateDialogUtils'

describe('tenantCreateDialogUtils', () => {
  test('accepts zip archives only', () => {
    expect(isStorageArchiveFile(new File(['data'], 'archive.zip'))).toBe(true)
    expect(isStorageArchiveFile(new File(['data'], 'archive.ZIP'))).toBe(true)
    expect(isStorageArchiveFile(new File(['data'], 'archive.json'))).toBe(false)
    expect(isStorageArchiveFile(null)).toBe(false)
  })

  test('returns the correct action label', () => {
    expect(getTenantCreateActionLabel('blank')).toBe('Create Instance')
    expect(getTenantCreateActionLabel('import')).toBe('Import Instance')
  })
})
