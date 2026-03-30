export const UPGRADE_URL = 'https://retriqs.com/'

const FREE_EDITION_MAX_STORAGES = 1
const DEV_MODE_VALUES = new Set(['dev', 'development', 'local', 'test'])

const RESTRICTED_STORAGE_PROVIDERS = new Set([
  'Neo4JStorage',
  'MilvusVectorDBStorage',
  'RedisKVStorage',
  'RedisDocStatusStorage'
])

// Keep this indirection so we can swap hardcoded checks for license/DB checks later.
export const isEditionRestricted = (): boolean => {
  const mode = String(import.meta.env.VITE_LIGHTRAG_EDITION_MODE ?? '')
    .trim()
    .toLowerCase()

  if (import.meta.env.DEV || DEV_MODE_VALUES.has(mode)) {
    return false
  }

  return true
}

export const canCreateAnotherStorage = (storageCount: number): boolean => {
  if (!isEditionRestricted()) {
    return true
  }

  return storageCount < FREE_EDITION_MAX_STORAGES
}

export const isRestrictedStorageProvider = (provider: string): boolean => {
  if (!isEditionRestricted()) {
    return false
  }

  return RESTRICTED_STORAGE_PROVIDERS.has(provider)
}

export const redirectToUpgrade = (): void => {
  window.location.href = UPGRADE_URL
}
