export const DEFAULT_LANGCHAIN_MARKETPLACE_ARCHIVE_URL =
  'https://d2nx8b3pezm5w7.cloudfront.net/public/graphs/LangChain_Storage-storage-export.zip'

export const LANGCHAIN_MARKETPLACE_ARCHIVE_URL =
  import.meta.env.VITE_MARKETPLACE_LANGCHAIN_ARCHIVE_URL ||
  DEFAULT_LANGCHAIN_MARKETPLACE_ARCHIVE_URL
