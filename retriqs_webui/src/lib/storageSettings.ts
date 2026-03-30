import { GraphStorage } from '@/api/retriqs'

export const getStorageSettingValue = (
  storage: GraphStorage | undefined,
  key: string
): string | undefined => {
  if (!storage?.storage_settings) return undefined
  const setting = storage.storage_settings.find(
    (entry) => entry.key?.toUpperCase?.() === key.toUpperCase()
  )
  return setting?.value
}

export const isStorageNeedsReembedding = (
  storage: GraphStorage | undefined
): boolean => {
  const value = getStorageSettingValue(storage, 'NEEDS_REEMBEDDING')
  if (!value) return false
  return value.toLowerCase() === 'true'
}
