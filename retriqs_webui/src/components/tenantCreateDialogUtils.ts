export const isStorageArchiveFile = (file: File | null): boolean => {
  if (!file) {
    return false
  }

  const fileName = file.name.toLowerCase()
  return fileName.endsWith('.zip')
}

export const getTenantCreateActionLabel = (
  mode: 'blank' | 'import'
): 'Create Instance' | 'Import Instance' => {
  return mode === 'import' ? 'Import Instance' : 'Create Instance'
}
